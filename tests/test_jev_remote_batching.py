"""Offline transport checks for batching, completeness, and backpressure."""
from __future__ import annotations
import io
import json
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import jev_gateway as gateway


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.body).encode()


class TestRemoteBatching(unittest.TestCase):
    def setUp(self):
        with gateway._BACKPRESSURE_LOCK:
            gateway._BACKPRESSURE.clear()
        self.config = {"endpoint": "https://offline.invalid/v1/systemone", "api_key": "offline-key", "model": "jev-latest"}
        self.payload = {"contexts": ["Original shared evidence"], "instructions": {"rubric": ["Goal A", "Goal B"]},
                        "schema": {"first": {"type": "noul"}, "second": {"type": "noul"}}}

    def tearDown(self):
        with gateway._BACKPRESSURE_LOCK:
            gateway._BACKPRESSURE.clear()

    @staticmethod
    def success(request):
        body = json.loads(request.data)
        return Response({"answers": {name: {"noul": 0.9} for name in body["questions"]},
                         "usage": {"input_tokens": 10, "output_tokens": 2}})

    def test_more_than_local_field_limit_keeps_one_complete_remote_call(self):
        payload = {**self.payload, "schema": {f"field_{i}": {"type": "noul"} for i in range(40)}}
        with patch.object(gateway, "urlopen", side_effect=lambda request, timeout: self.success(request)) as upstream:
            result = gateway.call_typesafe(self.config, payload)
        self.assertEqual(upstream.call_count, 1)
        self.assertTrue(result["complete"])
        self.assertEqual(list(result["results"][0]["fields"]), list(payload["schema"]))
        adapted = json.loads(upstream.call_args.args[0].data)
        self.assertEqual(adapted["state"], payload["contexts"][0])
        self.assertEqual(adapted["questions"]["jev_field_39"]["instructions"]["caller_instructions"], payload["instructions"])
        self.assertFalse(result["capacity"]["preflight_verified"])
        self.assertEqual(result["capacity"]["capacity_status"], "unknown")
        self.assertNotIn("model", result)

    def test_missing_or_malformed_question_preserves_other_answers_and_usage(self):
        for bad in (None, {"noul": 4}):
            with self.subTest(answer=bad):
                answers = {"jev_field_0": {"noul": 0.9}}
                if bad is not None:
                    answers["jev_field_1"] = bad
                with patch.object(gateway, "urlopen", return_value=Response({"answers": answers, "usage": {"input_tokens": 10}})) as upstream:
                    with self.assertRaises(gateway.GatewayError) as raised:
                        gateway.call_typesafe(self.config, self.payload)
                error = raised.exception
                self.assertEqual(error.status, 502)
                self.assertFalse(error.details["complete"])
                self.assertEqual(error.details["results"][0]["decision"], {"first": True})
                self.assertEqual(error.details["usage"], {"input_tokens": 10})
                self.assertEqual(error.details["failed_work"][0]["fields"], ["second"])
                self.assertEqual(error.details["retry_requests"], [{"context_index": 0, "request": {**self.payload, "schema": {"second": self.payload["schema"]["second"]}}}])
                self.assertEqual(upstream.call_count, 1)

    def test_context_failure_keeps_original_positions_and_narrow_retry(self):
        payload = {**self.payload, "contexts": ["failed context", "successful context"]}

        def upstream(request, timeout):
            if json.loads(request.data)["state"] == "failed context":
                raise HTTPError(request.full_url, 413, "too large", {}, io.BytesIO(b"private provider detail"))
            return self.success(request)

        with patch.object(gateway, "urlopen", side_effect=upstream) as mock:
            with self.assertRaises(gateway.GatewayError) as raised:
                gateway.call_typesafe(self.config, payload)
        error = raised.exception
        self.assertEqual(error.status, 413)
        self.assertEqual([row["context_index"] for row in error.details["results"]], [0, 1])
        self.assertEqual(error.details["results"][0]["decision"], {})
        self.assertEqual(error.details["results"][1]["decision"], {"first": True, "second": True})
        self.assertEqual(error.details["retry_requests"], [{"context_index": 0, "request": {**payload, "contexts": ["failed context"]}}])
        self.assertIn("regroup", error.details["failed_work"][0]["error"])
        self.assertNotIn("private provider detail", json.dumps(error.details))
        self.assertEqual(mock.call_count, 2)

    def test_rate_limit_cooldown_is_shared_across_profiles_and_models(self):
        with patch.object(gateway, "urlopen", side_effect=HTTPError(self.config["endpoint"], 429, "slow", {"Retry-After": "60"}, io.BytesIO(b"secret"))) as mock:
            with self.assertRaises(gateway.GatewayError) as raised:
                gateway.call_typesafe(self.config, self.payload)
            first = raised.exception
            self.assertEqual(first.status, 429)
            self.assertEqual(first.headers["Retry-After"], "60")
            with self.assertRaises(gateway.GatewayError) as raised_again:
                gateway.call_typesafe({**self.config, "id": "other", "model": "other-version"}, self.payload)
        self.assertEqual(mock.call_count, 1)
        self.assertEqual(raised_again.exception.status, 429)
        self.assertGreater(int(raised_again.exception.headers["Retry-After"]), 0)
        self.assertEqual(first.details["retry_requests"][0]["request"], self.payload)

    def test_unknown_retry_timing_stays_explicit_without_automatic_retries(self):
        for headers in ({}, {"Retry-After": "unknown"}, {"Retry-After": "-2"}, {"Retry-After": "inf"}, {"Retry-After": "9" * 400}):
            with self.subTest(headers=headers):
                with patch.object(gateway, "urlopen", side_effect=HTTPError(self.config["endpoint"], 429, "slow", headers, io.BytesIO())) as mock:
                    with self.assertRaises(gateway.GatewayError) as raised:
                        gateway.call_typesafe(self.config, self.payload)
                self.assertEqual(raised.exception.status, 429)
                self.assertIn("cooldown is unknown", raised.exception.details["failed_work"][0]["error"])
                self.assertEqual(mock.call_count, 1)

    def test_http_response_preserves_rate_limit_header_and_partial_contract(self):
        server = gateway.GatewayServer(("127.0.0.1", 0), gateway.GatewayHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        request = Request(f"http://127.0.0.1:{server.server_address[1]}/v1/decision",
                          data=json.dumps(self.payload).encode(), headers={"Content-Type": "application/json"})
        config = {**self.config, "id": "offline"}
        try:
            with patch.object(gateway, "selected_backend", return_value="remote:offline"), \
                 patch.object(gateway, "load_profiles", return_value=[config]), \
                 patch.object(gateway, "urlopen", side_effect=HTTPError(config["endpoint"], 429, "slow", {"Retry-After": "60"}, io.BytesIO(b"secret"))):
                with self.assertRaises(HTTPError) as raised:
                    urlopen(request, timeout=5)
                response = raised.exception
                self.assertEqual(response.code, 429)
                self.assertEqual(response.headers["Retry-After"], "60")
                body = json.loads(response.read())
                response.close()
                self.assertFalse(body["complete"])
                self.assertEqual(body["retry_requests"], [{"context_index": 0, "request": self.payload}])
                self.assertNotIn("secret", json.dumps(body))
        finally:
            server.shutdown()
            server.server_close()

    def test_http_date_retry_after_and_shorter_delay_never_shortens_cooldown(self):
        future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=60), usegmt=True)
        self.assertGreater(gateway._retry_delay(future), 0)
        gateway._record_backpressure(self.config, future)
        deadline = gateway._BACKPRESSURE[gateway._account_key(self.config)][0]
        gateway._record_backpressure(self.config, "0")
        self.assertEqual(gateway._BACKPRESSURE[gateway._account_key(self.config)][0], deadline)
        with self.assertRaises(gateway.GatewayError):
            gateway._check_backpressure(self.config)
        with patch.object(gateway.time, "monotonic", return_value=deadline + 1):
            gateway._check_backpressure(self.config)
        self.assertNotIn(gateway._account_key(self.config), gateway._BACKPRESSURE)

    def test_concurrent_callers_share_existing_worker_bound_and_run_in_parallel(self):
        entered = threading.Event()
        release = threading.Event()
        lock = threading.Lock()
        active = 0
        maximum = 0
        calls = 0

        def upstream(request, timeout):
            nonlocal active, maximum, calls
            with lock:
                active += 1
                maximum = max(maximum, active)
                calls += 1
                if active == gateway.REMOTE_WORKERS:
                    entered.set()
            self.assertTrue(release.wait(5), "test did not release upstream")
            with lock:
                active -= 1
            return self.success(request)

        payload = {**self.payload, "contexts": [f"context {i}" for i in range(gateway.REMOTE_WORKERS)]}
        with patch.object(gateway, "urlopen", side_effect=upstream):
            with ThreadPoolExecutor(max_workers=2) as callers:
                pending = [callers.submit(gateway.call_typesafe, self.config, payload) for _ in range(2)]
                try:
                    self.assertTrue(entered.wait(5), "parallel gateway work was not admitted")
                    with lock:
                        self.assertEqual(calls, gateway.REMOTE_WORKERS)
                finally:
                    release.set()
                results = [future.result(timeout=5) for future in pending]
        self.assertEqual(maximum, gateway.REMOTE_WORKERS)
        self.assertTrue(all(result["complete"] for result in results))
        self.assertEqual(calls, 2 * gateway.REMOTE_WORKERS)


if __name__ == "__main__":
    unittest.main()
