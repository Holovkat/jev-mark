from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import jev_gateway as gateway
import typesafe_benchmark


class SystemOneProfileTests(unittest.TestCase):
    def test_only_typesafe_json_supplies_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            secure = Path(directory)
            row = {"id": "canonical", "name": "Canonical", "base_url": "https://example.invalid/v1/systemone",
                   "api_key": "test-placeholder", "model": "test-model"}
            (secure / "typesafe.json").write_text(json.dumps({"configs": [row]}))
            legacy = dict(row, id="legacy")
            (secure / "typesafe-config.json").write_text(json.dumps({"configs": [legacy]}))
            (secure / "env.dev").write_text("Jev_url=https://example.invalid\nJevapi=test-placeholder\n")
            with patch.object(gateway, "SECURE_DIR", secure), patch.dict(os.environ, {"TYPESAFE_SECURE_DIR": directory}):
                self.assertEqual([p["id"] for p in gateway.load_profiles()], ["canonical"])
                self.assertEqual([p["id"] for p in typesafe_benchmark.load_profiles()], ["canonical"])
                (secure / "typesafe.json").unlink()
                self.assertEqual(gateway.load_profiles(), [])
                self.assertEqual(typesafe_benchmark.load_profiles(), [])

    def test_provider_endpoints_preserve_explicit_decision_routes(self):
        for endpoint in (
            "http://127.0.0.1:11434/v1/systemone",
            "https://openrouter.ai/api/alpha/decisions",
            "https://api.typesafe.ai/v1/systemone",
        ):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(gateway.normalize_endpoint(endpoint + "/"), endpoint)
                self.assertEqual(typesafe_benchmark.normalize_endpoint(endpoint + "/"), endpoint)

    def test_existing_base_url_expansion(self):
        self.assertEqual(gateway.normalize_endpoint("https://api.typesafe.ai/v1"),
                         "https://api.typesafe.ai/v1/systemone")
        self.assertIsNone(gateway.normalize_endpoint("file:///tmp/profile"))


class FakeUpstreamHandler(BaseHTTPRequestHandler):
    received: list[dict] = []
    response_body = b'{"upstream":"ok"}'
    health_body = b'{"service":"jev-apple-provider","available":true}'

    def log_message(self, _format: str, *_args) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        self.__class__.received.append(json.loads(self.rfile.read(length)))
        body = self.__class__.response_body
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        body = self.__class__.health_body
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FakeTypesafeHandler(BaseHTTPRequestHandler):
    received: list[dict] = []
    authorization: list[str] = []

    def log_message(self, _format: str, *_args) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        self.__class__.received.append(body)
        self.__class__.authorization.append(self.headers.get("Authorization", ""))
        answers = {}
        for name, question in body["questions"].items():
            if question["type"] == "choice":
                choices = list(question["criteria"])
                choice = choices[0]
                remaining = 0.2 / max(1, len(choices) - 1)
                probabilities = {item: 0.8 if item == choice else remaining for item in choices}
                answers[name] = {
                    "type": "choice",
                    "choice": choice,
                    "confidence": 0.8,
                    "probabilities": probabilities,
                }
            elif question["type"] == "score":
                criteria = question["criteria"]
                if len(criteria) == 3:
                    probabilities = {"0": 0.1, "1": 0.2, "2": 0.7}
                else:
                    probabilities = {str(index): 1 / len(criteria) for index in range(len(criteria))}
                score = round(sum(index * probabilities[str(index)] for index in range(len(criteria))), 6)
                answers[name] = {
                    "type": "score",
                    "score": score,
                    "confidence": 0.6,
                    "legend": {str(index): criterion for index, criterion in enumerate(criteria)},
                    "probabilities": probabilities,
                }
            else:
                answers[name] = {"type": "noul", "noul": 0.8}
        response = json.dumps({"model": body["model"], "answers": answers}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


class TestJEVGateway(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp_dir.name)
        self.old_settings = gateway.SETTINGS_PATH
        self.old_secure = gateway.SECURE_DIR
        self.old_local_port = gateway.LOCAL_PORT
        self.old_apple_port = gateway.APPLE_PORT
        gateway.SETTINGS_PATH = self.directory / "settings.json"
        gateway.SECURE_DIR = self.directory / ".secure"
        self.directory.joinpath(".secure").mkdir()
        FakeUpstreamHandler.received = []
        FakeUpstreamHandler.response_body = b'{"upstream":"ok"}'
        FakeUpstreamHandler.health_body = b'{"service":"jev-apple-provider","available":true}'
        FakeTypesafeHandler.received = []
        FakeTypesafeHandler.authorization = []
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstreamHandler)
        gateway.LOCAL_PORT = self.upstream.server_address[1]
        gateway.APPLE_PORT = self.upstream.server_address[1]
        self.upstream_thread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        self.upstream_thread.start()
        self.gateway = ThreadingHTTPServer(("127.0.0.1", 0), gateway.GatewayHandler)
        self.gateway_thread = threading.Thread(target=self.gateway.serve_forever, daemon=True)
        self.gateway_thread.start()

    def tearDown(self) -> None:
        self.gateway.shutdown()
        self.gateway.server_close()
        self.upstream.shutdown()
        self.upstream.server_close()
        gateway.SETTINGS_PATH = self.old_settings
        gateway.SECURE_DIR = self.old_secure
        gateway.LOCAL_PORT = self.old_local_port
        gateway.APPLE_PORT = self.old_apple_port
        self.temp_dir.cleanup()

    def _settings(self, backend: str) -> None:
        gateway.SETTINGS_PATH.write_text(json.dumps({"selected_backend": backend}), encoding="utf-8")

    def _post(self, payload: dict) -> tuple[int, dict]:
        data = json.dumps(payload).encode()
        request = Request(
            f"http://127.0.0.1:{self.gateway.server_address[1]}/v1/decision",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            body = json.loads(error.read())
            error.close()
            return error.code, body

    def _get(self, path: str) -> tuple[int, dict | bytes, str]:
        request = Request(f"http://127.0.0.1:{self.gateway.server_address[1]}{path}")
        with urlopen(request, timeout=3) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "")
            if content_type.startswith("application/json"):
                return response.status, json.loads(body), content_type
            return response.status, body, content_type

    def test_landing_and_workbench_keep_distinct_routes_and_health(self) -> None:
        landing = self.directory / "landing.html"
        workbench = self.directory / "index.html"
        landing.write_text("<!doctype html><title>JEV Landing</title>", encoding="utf-8")
        workbench.write_text("<!doctype html><title>JEV Workbench</title>", encoding="utf-8")
        with patch.object(gateway, "landing_path", return_value=landing), \
             patch.object(gateway, "workbench_path", return_value=workbench):
            status, body, content_type = self._get("/")
            self.assertEqual(status, 200)
            self.assertIn("text/html", content_type)
            self.assertEqual(body, landing.read_bytes())
            status, body, content_type = self._get("/workbench")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertEqual(body, workbench.read_bytes())

        status, body, content_type = self._get("/health")
        self.assertEqual(status, 200)
        self.assertIn("application/json", content_type)
        self.assertEqual(body["service"], "jev-gateway")

    def test_example_catalog_reuses_existing_question_suites_and_adds_primitive_demos(self) -> None:
        status, body, _ = self._get("/examples")
        self.assertEqual(status, 200)
        suites = {suite["id"]: suite for suite in body["suites"]}
        self.assertEqual(len(suites["logic"]["cases"]), 11)
        self.assertEqual(len(suites["ambiguity"]["cases"]), 10)
        self.assertEqual(len(suites["reasoning"]["cases"]), 10)
        car_wash = next(case for case in suites["logic"]["cases"] if case["id"] == "car-wash")
        self.assertEqual(car_wash["expected"], "drive")
        primitives = {case["type"] for case in suites["primitives"]["cases"]}
        self.assertEqual(primitives, {"score", "noul"})
        patterns = suites["agentic-patterns"]["cases"]
        baseline_batch = next(case for case in patterns if case["id"] == "logic-baselines-parallel")
        self.assertIn("at most four sessions in flight", baseline_batch["workflow"]["note"])
        self.assertIn("one request", baseline_batch["workflow"]["note"])
        expected = {
            case["id"].replace("-", "_"): case["expected"]
            for case in suites["logic"]["cases"]
        }
        self.assertEqual(baseline_batch["workflow"]["reference_answers"], expected)
        self.assertEqual(set(baseline_batch["schema"]), set(expected))
        self.assertEqual(set(baseline_batch["workflow"]["question_contexts"]), set(expected))
        self.assertTrue(all(
            "Question:" in context
            for context in baseline_batch["workflow"]["question_contexts"].values()
        ))
        self.assertTrue(all(field["type"] == "choice" for field in baseline_batch["schema"].values()))

        quiz = next(case for case in suites["agentic-patterns"]["cases"] if case["id"] == "logic-100-parallel")
        self.assertIn("at most four sessions in flight", quiz["workflow"]["note"])
        self.assertEqual(len(quiz["schema"]), 100)
        self.assertEqual(len(quiz["workflow"]["reference_answers"]), 100)
        self.assertEqual(len(quiz["workflow"]["question_contexts"]), 100)
        self.assertEqual(set(quiz["schema"]), set(quiz["workflow"]["reference_answers"]))
        self.assertEqual(set(quiz["schema"]), set(quiz["workflow"]["question_contexts"]))
        self.assertTrue(all(field["type"] == "choice" for field in quiz["schema"].values()))
        scoring = quiz["workflow"]["question_scoring"]
        self.assertEqual(set(scoring), set(quiz["schema"]))
        # Definite questions add a hedge choice only when their answer is concrete;
        # judgment questions keep three choices with at least one defensible commit.
        for name, field in quiz["schema"].items():
            entry = scoring[name]
            self.assertIn(entry["kind"], {"definite", "judgment"})
            if entry["kind"] == "definite":
                self.assertEqual(len(field["criteria"]), 4 if entry["hedge"] else 3)
                if entry["hedge"]:
                    self.assertIn(entry["hedge"], field["criteria"])
            else:
                self.assertEqual(len(field["criteria"]), 3)
                self.assertTrue(entry["reasonable"])
                self.assertTrue(set(entry["reasonable"]) <= set(field["criteria"]))
                self.assertNotIn(quiz["workflow"]["reference_answers"][name], entry["reasonable"])
        self.assertEqual(scoring["q004"], {"kind": "judgment", "reasonable": ["Open the red box"]})
        self.assertEqual(scoring["q016"], {"kind": "definite", "hedge": None})
        self.assertEqual(scoring["q002"], {"kind": "definite", "hedge": None})
        # Choices are substantive answers to their own question, never generic filler:
        # no template text survives anywhere, and every field has 3 distinct choices.
        generic_templates = (
            "The facts do not establish a definite answer.",
            "Assume a likely interpretation and answer definitively.",
            "Give a definite answer without resolving the missing information.",
            "Ask for clarification even though the facts determine the answer.",
        )
        self.assertTrue(all(
            template not in field["criteria"] for field in quiz["schema"].values() for template in generic_templates
        ))
        self.assertTrue(all(
            len({choice.casefold() for choice in field["criteria"]}) == len(field["criteria"]) for field in quiz["schema"].values()
        ))
        self.assertEqual(
            set(quiz["schema"]["q016"]["criteria"]),
            {'Ambiguous: "she" could be the doctor or the patient', "The doctor", "The patient"},
        )
        self.assertEqual(
            quiz["workflow"]["reference_answers"]["q016"],
            'Ambiguous: "she" could be the doctor or the patient',
        )
        self.assertEqual(set(quiz["schema"]["q019"]["criteria"]), {"Ambiguous", "The chicken", "The egg"})
        self.assertEqual(
            set(quiz["schema"]["q056"]["criteria"]),
            {"Either qualifies, unless another criterion matters",
             "Stop and ask which exit to take before moving.",
             "Take the left exit, since left is always the safer default.",
             "Neither exit, since no single exit is the nearest"},
        )

    def test_agentic_pattern_examples_are_multi_field_and_use_one_typesafe_call_each(self) -> None:
        status, body, _ = self._get("/examples")
        self.assertEqual(status, 200)
        suite = next(item for item in body["suites"] if item["id"] == "agentic-patterns")
        cases = suite["cases"]
        self.assertEqual(
            {case["workflow"]["type"] for case in cases},
            {"parallel-questions", "intent-routing", "composite-scoring", "confidence-routing", "fan-out"},
        )
        for case in cases:
            self.assertEqual(case["type"], "parallel")
            self.assertGreaterEqual(len(case["schema"]), 2)
            self.assertTrue(set(definition["type"] for definition in case["schema"].values()) <= {"choice", "score", "noul"})

        typesafe = ThreadingHTTPServer(("127.0.0.1", 0), FakeTypesafeHandler)
        typesafe_thread = threading.Thread(target=typesafe.serve_forever, daemon=True)
        typesafe_thread.start()
        gateway.SECURE_DIR.joinpath("typesafe.json").write_text(json.dumps({
            "configs": [{
                "id": "selected",
                "name": "Test profile",
                "base_url": f"http://127.0.0.1:{typesafe.server_address[1]}",
                "api_key": "test-secret",
                "model": "jev-test",
            }]
        }), encoding="utf-8")
        self._settings("remote:selected")
        try:
            for case in cases:
                payload = {
                    "instructions": f"{case['question']}\n\n{case['guidance']}",
                    "schema": case["schema"],
                    "contexts": [case["context"]],
                }
                expected_fields = set(case["schema"])
                self.assertEqual(set(gateway.local_payload(payload)["schema"]), expected_fields)
                self.assertEqual(set(gateway.apple_payload(payload)["schema"]), expected_fields)
                before = len(FakeTypesafeHandler.received)
                status, response = self._post(payload)
                self.assertEqual(status, 200, case["id"])
                self.assertEqual(set(response["results"][0]["fields"]), expected_fields)
                self.assertEqual(len(FakeTypesafeHandler.received), before + 1)
                sent_questions = FakeTypesafeHandler.received[-1]["questions"]
                self.assertEqual(len(sent_questions), len(case["schema"]))
                self.assertNotIn("workflow", FakeTypesafeHandler.received[-1])
        finally:
            typesafe.shutdown()
            typesafe.server_close()
        self.assertEqual(FakeUpstreamHandler.received, [])

    def test_local_selection_overrides_caller_model_and_forwards_to_engine(self) -> None:
        self._settings("local:granite4.2:latest")
        status, response = self._post({
            "model": "gemma4:12b",
            "schema": {"answer": {"type": "enum", "choices": ["yes", "no"]}},
            "contexts": ["test"],
        })
        self.assertEqual(status, 200)
        self.assertEqual(response, {"upstream": "ok"})
        self.assertEqual(FakeUpstreamHandler.received[0]["model"], "granite4.2:latest")
        self.assertNotIn("instructions", FakeUpstreamHandler.received[0])

    def test_local_selection_keeps_structured_rubric_as_text(self) -> None:
        self._settings("local:granite4.2:latest")
        status, _ = self._post({
            "instructions": {"purpose": "Assess the test evidence."},
            "schema": {
                "relevance": {
                    "type": "enum",
                    "choices": ["supporting", "irrelevant"],
                    "instructions": {"question": "Does this assertion support R3?"},
                    "criteria": {
                        "supporting": {"what": "Checks a necessary workflow step"},
                        "irrelevant": {"not_for": "Checks the Schedule action"},
                    },
                },
            },
            "contexts": ["Schedule button invokes callback"],
        })
        self.assertEqual(status, 200)
        field = FakeUpstreamHandler.received[0]["schema"]["relevance"]
        self.assertIn("necessary workflow step", field["description"])
        self.assertIn("Does this assertion support R3?", field["description"])
        self.assertNotIn("criteria", field)
        self.assertNotIn("instructions", field)
        self.assertEqual(FakeUpstreamHandler.received[0]["instructions"], '{"purpose": "Assess the test evidence."}')

    def test_local_score_maps_to_ordered_integer_levels(self) -> None:
        self._settings("local:granite4.2:latest")
        FakeUpstreamHandler.response_body = json.dumps({
            "results": [{
                "decision": {"adequacy": 2},
                "fields": {"adequacy": {
                    "value": 2,
                    "probability": 0.6,
                    "probabilities": {"0": 0.1, "1": 0.3, "2": 0.6},
                    "tree": True,
                }},
            }],
        }).encode()
        status, response = self._post({
            "instructions": {"purpose": "Rate test adequacy."},
            "mode": "auto",
            "tree_max": 1,
            "schema": {
                "adequacy": {
                    "type": "score",
                    "instructions": {"question": "How adequate is this test?"},
                    "criteria": [
                        {"label": "weak", "meaning": "Does not establish the behavior."},
                        {"label": "partial", "meaning": "Establishes only part of the behavior."},
                        {"label": "strong", "meaning": "Establishes the complete behavior."},
                    ],
                },
            },
            "contexts": ["The test checks the callback."],
        })
        self.assertEqual(status, 200)
        forwarded = FakeUpstreamHandler.received[0]
        field = forwarded["schema"]["adequacy"]
        self.assertEqual(field["type"], "integer")
        self.assertEqual((field["minimum"], field["maximum"]), (0, 2))
        self.assertIn('"meaning": "Establishes the complete behavior."', field["description"])
        self.assertEqual(forwarded["tree_max"], 3)
        self.assertEqual(response["results"][0]["decision"]["adequacy"], 1.5)
        self.assertEqual(response["results"][0]["fields"]["adequacy"]["score"], 1.5)

    def test_local_response_restores_score_distribution_and_noul_value(self) -> None:
        response = {
            "results": [{
                "decision": {"verdict": "supporting", "adequacy": 2, "supported": False},
                "fields": {
                    "verdict": {
                        "value": "supporting",
                        "probability": 0.7,
                        "probabilities": {"supporting": 0.7, "irrelevant": 0.3},
                    },
                    "adequacy": {
                        "value": 2,
                        "probability": 0.6,
                        "probabilities": {"0": 0.1, "1": 0.3, "2": 0.6},
                        "tree": True,
                    },
                    "supported": {
                        "value": False,
                        "probability": 0.8,
                        "probabilities": {"true": 0.2, "false": 0.8},
                    },
                },
            }],
        }
        adapted = gateway.adapt_local_response({
            "schema": {
                "verdict": {"type": "choice", "choices": ["supporting", "irrelevant"]},
                "adequacy": {"type": "score", "criteria": ["weak", "partial", "strong"]},
                "supported": {"type": "noul"},
            },
        }, response)
        result = adapted["results"][0]
        self.assertEqual(result["fields"]["verdict"]["probabilities"], {"supporting": 0.7, "irrelevant": 0.3})
        self.assertEqual(result["decision"]["adequacy"], 1.5)
        self.assertEqual(result["fields"]["adequacy"]["score"], 1.5)
        self.assertEqual(result["fields"]["adequacy"]["legend"], {"0": "weak", "1": "partial", "2": "strong"})
        self.assertNotIn("probability", result["fields"]["adequacy"])
        self.assertEqual(result["fields"]["adequacy"]["most_likely_level_probability"], 0.6)
        self.assertEqual(result["decision"]["supported"], False)
        self.assertEqual(result["fields"]["supported"]["noul"], 0.2)

    def test_missing_remote_profile_fails_without_local_fallback(self) -> None:
        self._settings("remote:missing-profile")
        status, response = self._post({
            "schema": {"answer": {"type": "enum", "choices": ["yes", "no"]}},
            "contexts": ["test"],
        })
        self.assertEqual(status, 503)
        self.assertIn("System One profile", response["error"])
        self.assertEqual(FakeUpstreamHandler.received, [])

    def test_apple_backend_forwards_normalized_request_without_inventing_probabilities(self) -> None:
        self._settings(gateway.APPLE_BACKEND)
        FakeUpstreamHandler.response_body = json.dumps({
            "results": [{
                "decision": {"answer": "drive", "adequacy": 2, "supported": False},
                "fields": {
                    "answer": {"value": "drive"},
                    "adequacy": {"value": 2, "score": 2, "legend": {"0": "weak", "1": "partial", "2": "strong"}},
                    "supported": {"value": False},
                },
            }],
        }).encode()
        status, response = self._post({
            "instructions": "Choose the answer supported by the facts.",
            "schema": {
                "answer": {
                    "type": "choice",
                    "criteria": {
                        "walk": {"meaning": "The car is not taken."},
                        "drive": {"meaning": "The car is present at the wash."},
                    },
                    "instructions": {"question": "How should the car get there?"},
                },
                "adequacy": {
                    "type": "score",
                    "criteria": ["weak", "partial", "strong"],
                },
                "supported": {
                    "type": "noul",
                    "criteria": {"true": "The evidence supports it.", "false": "The evidence does not support it."},
                },
            },
            "contexts": ["The car must be physically washed at the facility."],
        })

        self.assertEqual(status, 200)
        self.assertEqual(response["results"][0]["decision"], {"answer": "drive", "adequacy": 2, "supported": False})
        self.assertEqual(response["results"][0]["fields"]["answer"], {"value": "drive"})
        self.assertEqual(response["results"][0]["fields"]["adequacy"]["score"], 2)
        self.assertNotIn("probabilities", response["results"][0]["fields"]["adequacy"])
        self.assertNotIn("confidence", response["results"][0]["fields"]["supported"])
        self.assertNotIn("provider", response)
        self.assertNotIn("model", response)
        forwarded = FakeUpstreamHandler.received[0]
        self.assertEqual(forwarded["schema"]["answer"]["type"], "choice")
        self.assertEqual(forwarded["schema"]["answer"]["choices"], ["walk", "drive"])
        self.assertEqual(forwarded["schema"]["answer"]["criteria"]["drive"]["meaning"], "The car is present at the wash.")
        self.assertEqual(forwarded["schema"]["adequacy"]["type"], "score")
        self.assertEqual(forwarded["schema"]["adequacy"]["criteria"], ["weak", "partial", "strong"])
        self.assertEqual(forwarded["schema"]["supported"]["type"], "noul")
        self.assertEqual(forwarded["schema"]["supported"]["criteria"]["false"], "The evidence does not support it.")
        self.assertEqual(forwarded["contexts"], ["The car must be physically washed at the facility."])
        self.assertNotIn("model", forwarded)

    def test_apple_health_reports_unavailable_state(self) -> None:
        self._settings(gateway.APPLE_BACKEND)
        FakeUpstreamHandler.health_body = json.dumps({
            "service": "jev-apple-provider",
            "available": False,
            "message": "Apple Intelligence is disabled.",
        }).encode()
        with urlopen(f"http://127.0.0.1:{self.gateway.server_address[1]}/health", timeout=3) as response:
            health = json.loads(response.read())
        self.assertEqual(health["backend_status"], "unavailable")
        self.assertEqual(health["message"], "Apple Intelligence is disabled.")

    def test_apple_backend_fails_closed_without_falling_back_to_local(self) -> None:
        self._settings(gateway.APPLE_BACKEND)
        gateway.APPLE_PORT = 0
        status, response = self._post({
            "schema": {"answer": {"type": "enum", "choices": ["yes", "no"]}},
            "contexts": ["test"],
        })
        self.assertEqual(status, 503)
        self.assertIn("Apple Foundation Models provider", response["error"])
        self.assertEqual(FakeUpstreamHandler.received, [])

    def test_remote_selection_routes_to_typesafe_instead_of_local_engine(self) -> None:
        typesafe = ThreadingHTTPServer(("127.0.0.1", 0), FakeTypesafeHandler)
        typesafe_thread = threading.Thread(target=typesafe.serve_forever, daemon=True)
        typesafe_thread.start()
        gateway.SECURE_DIR.joinpath("typesafe.json").write_text(json.dumps({
            "configs": [{
                "id": "selected",
                "name": "Test profile",
                "base_url": f"http://127.0.0.1:{typesafe.server_address[1]}",
                "api_key": "test-secret",
                "model": "jev-test",
            }]
        }), encoding="utf-8")
        self._settings("remote:selected")
        try:
            with urlopen(
                f"http://127.0.0.1:{self.gateway.server_address[1]}/providers",
                timeout=3,
            ) as provider_response:
                providers_body = provider_response.read()
            self.assertIn(b"selected", providers_body)
            self.assertIn(b"Test profile", providers_body)
            self.assertIn(b"jev-test", providers_body)
            self.assertNotIn(b"test-secret", providers_body)
            status, response = self._post({
                "model": "gemma4:12b",
                "instructions": {"purpose": "Adjudicate the evidence."},
                "schema": {
                    "verdict": {
                        "type": "choice",
                        "instructions": {"question": "Which verdict fits?"},
                        "criteria": {
                            "correct": {"what": "Supported by the evidence."},
                            "incorrect": {"what": "Contradicted by the evidence."},
                        },
                    },
                    "adequacy": {
                        "type": "score",
                        "instructions": ["Rate the test against the requirement."],
                        "criteria": ["Does not establish it", "Establishes part", "Establishes all of it"],
                    },
                    "supported": {
                        "type": "noul",
                        "instructions": {"question": "Is the claim supported?"},
                        "criteria": {"true": "The source supports it.", "false": "The source does not support it."},
                    },
                },
                "contexts": ["A candidate response."],
            })
        finally:
            typesafe.shutdown()
            typesafe.server_close()

        self.assertEqual(status, 200)
        self.assertNotIn("provider", response)
        self.assertNotIn("model", response)
        self.assertEqual(response["results"][0]["decision"], {
            "verdict": "correct", "adequacy": 1.6, "supported": True,
        })
        fields = response["results"][0]["fields"]
        self.assertEqual(fields["verdict"]["probabilities"], {"correct": 0.8, "incorrect": 0.2})
        self.assertEqual(fields["verdict"]["confidence"], 0.8)
        self.assertEqual(fields["adequacy"]["probabilities"], {"0": 0.1, "1": 0.2, "2": 0.7})
        self.assertEqual(fields["adequacy"]["legend"]["2"], "Establishes all of it")
        self.assertEqual(fields["supported"]["noul"], 0.8)
        self.assertEqual(len(FakeTypesafeHandler.received), 1)
        questions = FakeTypesafeHandler.received[0]["questions"]
        self.assertEqual([question["type"] for question in questions.values()], ["choice", "score", "noul"])
        self.assertEqual(questions["jev_field_0"]["criteria"]["correct"], {"what": "Supported by the evidence."})
        self.assertEqual(questions["jev_field_0"]["instructions"]["caller_instructions"], {"purpose": "Adjudicate the evidence."})
        self.assertEqual(FakeTypesafeHandler.authorization, ["Bearer test-secret"])
        self.assertEqual(FakeTypesafeHandler.received[0]["model"], "jev-test")
        self.assertEqual(FakeUpstreamHandler.received, [])

    def test_typesafe_adapter_maps_enum_and_boolean_to_jev_response(self) -> None:
        received: dict = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "model": "jev-test",
                    "answers": {
                        "jev_field_0": {
                            "choice": "drive",
                            "confidence": 0.9,
                            "probabilities": {"drive": 0.9, "walk": 0.1},
                        },
                        "jev_field_1": {"noul": 0.82},
                    },
                    "usage": {"input_tokens": 12, "output_tokens": 4},
                }).encode()

        def fake_urlopen(request, timeout):
            received["body"] = json.loads(request.data)
            received["auth"] = request.headers.get("Authorization")
            received["timeout"] = timeout
            return Response()

        config = {
            "id": "test",
            "name": "Test",
            "endpoint": "https://example.invalid/v1/systemone",
            "api_key": "test-secret",
            "model": "jev-test",
        }
        payload = {
            "model": "must-not-override-provider",
            "instructions": "Judge the intended outcome.",
            "schema": {
                "answer": {"type": "enum", "choices": ["walk", "drive"], "description": "Best way to bring the car."},
                "has_vehicle": {"type": "boolean", "description": "The car must be present at the facility."},
            },
            "contexts": ["Should I wash the car there?"],
        }
        with patch.object(gateway, "urlopen", fake_urlopen):
            response = gateway.call_typesafe(config, payload)

        self.assertEqual(received["auth"], "Bearer test-secret")
        self.assertEqual(received["body"]["model"], "jev-test")
        self.assertNotIn("must-not-override-provider", json.dumps(received["body"]))
        self.assertEqual(received["body"]["questions"]["jev_field_0"]["type"], "choice")
        self.assertEqual(received["body"]["questions"]["jev_field_1"]["type"], "noul")
        result = response["results"][0]
        self.assertEqual(result["decision"], {"answer": "drive", "has_vehicle": True})
        self.assertEqual(result["fields"]["answer"]["probability"], 0.9)
        self.assertEqual(result["fields"]["has_vehicle"]["probability"], 0.82)
        self.assertEqual(response["usage"], {"input_tokens": 12, "output_tokens": 4})

    def test_typesafe_adapter_preserves_structured_question_guidance(self) -> None:
        received = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "answers": {
                        "jev_field_0": {
                            "type": "choice",
                            "choice": "supporting",
                            "confidence": 0.7,
                            "probabilities": {"supporting": 0.7, "irrelevant": 0.3},
                        },
                        "jev_field_1": {"type": "noul", "noul": 0.8},
                    },
                }).encode()

        def fake_urlopen(request, timeout):
            received.append(json.loads(request.data))
            return Response()

        payload = {
            "instructions": "Assess one requirement-test pair.",
            "contexts": ["Pair P3: Schedule callback is asserted."],
            "schema": {
                "relevance": {
                    "type": "enum",
                    "choices": ["supporting", "irrelevant"],
                    "instructions": {"question": "Does P3 support R3?", "focus": "Schedule step"},
                    "criteria": {
                        "supporting": {"what": "A necessary Schedule interaction", "not_for": "Full Calendar projection"},
                        "irrelevant": {"what": "A separate behavior", "not_for": "A necessary workflow step"},
                    },
                },
                "has_result": {
                    "type": "boolean",
                    "instructions": {"question": "Is there a current test result?"},
                    "criteria": {"true": {"what": "A recorded current run"}, "false": {"what": "No current run"}},
                },
            },
        }
        config = {"endpoint": "https://example.invalid/v1/systemone", "api_key": "test", "model": "jev-test"}
        with patch.object(gateway, "urlopen", fake_urlopen):
            result = gateway.call_typesafe(config, payload)
        self.assertEqual(len(received), 1)
        questions = received[0]["questions"]
        self.assertEqual(questions["jev_field_0"]["criteria"]["supporting"]["what"], "A necessary Schedule interaction")
        self.assertEqual(questions["jev_field_0"]["instructions"]["question"]["focus"], "Schedule step")
        self.assertEqual(
            questions["jev_field_0"]["instructions"]["caller_instructions"],
            "Assess one requirement-test pair.",
        )
        self.assertEqual(questions["jev_field_1"]["criteria"]["false"]["what"], "No current run")
        self.assertEqual(result["results"][0]["fields"]["relevance"]["probabilities"], {
            "supporting": 0.7, "irrelevant": 0.3,
        })

    def test_clm_adapter_sends_plain_question_and_collapses_templated_criteria(self) -> None:
        received = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({"answers": {
                    "jev_field_0": {"type": "choice", "choice": "drive", "confidence": 0.6,
                                    "probabilities": {"walk": 0.2, "drive": 0.8}},
                    "jev_field_1": {"type": "choice", "choice": "billing", "confidence": 0.6,
                                    "probabilities": {"billing": 0.8, "tech": 0.2}},
                }}).encode()

        def fake_urlopen(request, timeout):
            received.append(json.loads(request.data))
            return Response()

        payload = {
            "instructions": "Treat each prompt independently.",
            "contexts": ["1. car-wash\nQuestion: Walk or drive to wash the car?"],
            "schema": {
                "car_wash": {
                    "type": "choice",
                    "instructions": "Answer only the 'car-wash' prompt.",
                    "criteria": {c: f"Select '{c}' as the best answer." for c in ("walk", "drive")},
                },
                "team": {
                    "type": "choice",
                    "instructions": "Which team should handle this?",
                    "criteria": {"billing": "Charges and refunds", "tech": "Bugs and outages"},
                },
            },
        }
        with patch.object(gateway, "urlopen", fake_urlopen):
            result = gateway.call_typesafe(gateway.CLM_CONFIG, payload)
        questions = received[0]["questions"]
        self.assertEqual(questions["jev_field_0"]["instructions"], "Answer only the 'car-wash' prompt.")
        self.assertEqual(questions["jev_field_0"]["criteria"], {"walk": None, "drive": None})
        self.assertEqual(questions["jev_field_1"]["criteria"], {"billing": "Charges and refunds", "tech": "Bugs and outages"})
        self.assertEqual(result["results"][0]["decision"]["car_wash"], "drive")

    def test_clm_criteria_only_collapses_when_descriptions_match(self) -> None:
        identical = {"a": "Listed answer choice.", "b": "Listed answer choice."}
        self.assertEqual(gateway._clm_criteria(identical), {"a": None, "b": None})
        short_keys = {"a": "Pick 'a' because apples", "b": "Pick 'b' because bananas"}
        self.assertEqual(gateway._clm_criteria(short_keys), short_keys)

    def test_clm_instructions_add_no_filler_when_field_has_none(self) -> None:
        self.assertIsNone(gateway._clm_instructions("q001", {"type": "choice"}, "Batch guidance."))
        self.assertEqual(gateway._clm_instructions("q001", {"description": "Is it late?"}, None), "Is it late?")


if __name__ == "__main__":
    unittest.main()
