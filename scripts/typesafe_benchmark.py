#!/usr/bin/env python3
"""Compare direct TypeSafe JEV API profiles with local JEV/Gemma."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

from logic_benchmark import TESTS, jev_call


def normalize_endpoint(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("invalid TypeSafe endpoint")
    path = parsed.path.rstrip("/")
    if not path.endswith(("/v1/systemone", "/alpha/decisions")):
        path = f"{path}/systemone" if path.endswith("/v1") else f"{path}/v1/systemone"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", parsed.query, ""))


def clean(value: object) -> str:
    return str(value).strip().strip("{}[],\"'")


def parse_pairs(text: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip().strip("{},")
        if not line or line.startswith("#") or line.startswith("["):
            continue
        match = re.match(r"([^:=]+)\s*[:=]\s*(.+)$", line)
        if not match:
            continue
        pairs[clean(match.group(1))] = clean(match.group(2))
    return pairs


def profile(raw: dict[str, object], fallback_id: str) -> dict[str, str] | None:
    endpoint = raw.get("base_url") or raw.get("baseURL") or raw.get("endpoint") or raw.get("url")
    api_key = raw.get("api_key") or raw.get("apiKey") or raw.get("key")
    if not endpoint or not api_key:
        return None
    try:
        endpoint = normalize_endpoint(str(endpoint))
    except ValueError:
        return None
    identifier = clean(raw.get("id") or fallback_id)
    return {
        "id": identifier,
        "name": clean(raw.get("name") or identifier),
        "endpoint": endpoint,
        "api_key": clean(api_key),
        "model": clean(raw.get("model") or "jev-latest"),
    }


def load_profiles() -> list[dict[str, str]]:
    secure = Path(os.environ.get("TYPESAFE_SECURE_DIR", ".secure"))
    profiles: list[dict[str, str]] = []
    for filename in ("typesafe.json", "typesafe-config.json"):
        path = secure / filename
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        rows = payload.get("configs", []) if isinstance(payload, dict) else payload
        if isinstance(rows, list):
            profiles.extend(
                candidate for index, item in enumerate(rows)
                if isinstance(item, dict)
                for candidate in [profile(item, f"{filename}-{index + 1}")]
                if candidate is not None
            )

    for filename in ("typesafe.env", "env.dev", ".env"):
        path = secure / filename
        if not path.exists():
            continue
        try:
            pairs = parse_pairs(path.read_text())
        except OSError:
            continue
        lowered = {key.lower(): value for key, value in pairs.items()}
        generic = profile(
            {
                "id": f"typesafe-{filename.replace('.', '-')}",
                "name": f"TypeSafe {filename}",
                "endpoint": lowered.get("jev_url") or lowered.get("typesafe_base_url") or lowered.get("typesafe_url") or lowered.get("typesafe_endpoint") or lowered.get("api_url"),
                "api_key": lowered.get("jevapi") or lowered.get("typesafe_api_key") or lowered.get("typesafe_key") or lowered.get("api_key"),
                "model": lowered.get("typesafe_model"),
            },
            filename,
        )
        if generic:
            profiles.append(generic)

        grouped: dict[str, dict[str, str]] = {}
        for key, value in pairs.items():
            match = re.fullmatch(r"TYPESAFE_(.+)_(API_KEY|KEY|BASE_URL|URL|ENDPOINT|MODEL|NAME)", key.upper())
            if match:
                grouped.setdefault(match.group(1), {})[match.group(2)] = value
        for identifier, values in grouped.items():
            candidate = profile(
                {
                    "id": f"typesafe-{identifier.lower()}",
                    "name": values.get("NAME") or f"TypeSafe {identifier}",
                    "endpoint": values.get("BASE_URL") or values.get("ENDPOINT") or values.get("URL"),
                    "api_key": values.get("API_KEY") or values.get("KEY"),
                    "model": values.get("MODEL"),
                },
                identifier,
            )
            if candidate:
                profiles.append(candidate)

    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for candidate in profiles:
        if candidate["id"] in seen:
            continue
        seen.add(candidate["id"])
        unique.append(candidate)
    return unique


def typesafe_call(config: dict[str, str], test: dict) -> dict:
    choices = test["choices"]
    payload = {
        "state": test["question"],
        "model": config["model"],
        "questions": {
            "answer": {
                "type": "choice",
                "instructions": "Choose the single logically correct answer from the supplied choices.",
                "criteria": {choice: f"The answer is {choice}." for choice in choices},
            }
        },
    }
    started = time.perf_counter()
    try:
        request = Request(
            config["endpoint"],
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {config['api_key']}",
                "Content-Type": "application/json",
            },
        )
        request_started = time.perf_counter()
        with urlopen(request, timeout=60) as response_stream:
            response = json.loads(response_stream.read())
        elapsed = (time.perf_counter() - request_started) * 1000
        answer = str(response["answers"]["answer"]["choice"])
        usage = response.get("usage", {})
        return {
            "backend": "typesafe",
            "config_id": config["id"],
            "model": config["model"],
            "test": test["id"],
            "expected": test["expected"],
            "answer": answer,
            "confidence": response.get("answers", {}).get("answer", {}).get("confidence"),
            "correct": answer == test["expected"],
            "concise": True,
            "elapsed_ms": round(elapsed, 1),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "error": None,
        }
    except Exception as exc:
        return {
            "backend": "typesafe",
            "config_id": config["id"],
            "model": config["model"],
            "test": test["id"],
            "expected": test["expected"],
            "answer": "",
            "correct": False,
            "concise": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "input_tokens": None,
            "output_tokens": None,
            "error": str(exc),
        }


def summarize(results: list[dict], backend: str, key: str) -> None:
    subset = [item for item in results if item["backend"] == backend and item.get("config_id", item["model"]) == key]
    timings = [item["elapsed_ms"] for item in subset if item["elapsed_ms"] is not None]
    correct = sum(item["correct"] for item in subset)
    mean = sum(timings) / len(timings) if timings else 0
    print(f"{backend:9} {key:28} correct={correct}/{len(subset)} avg_ms={mean:.1f}")


def main() -> None:
    profiles = load_profiles()
    if not profiles:
        raise SystemExit("No TypeSafe profiles found under .secure")

    results = [jev_call(test, os.environ.get("JEV_LOCAL_BASE_URL", "http://127.0.0.1:8097")) for test in TESTS]
    for config in profiles:
        results.extend(typesafe_call(config, test) for test in TESTS)

    output = Path(os.environ.get("TYPESAFE_BENCHMARK_OUTPUT", "typesafe-benchmark-results.json"))
    output.write_text(json.dumps({
        "profiles": [{key: value for key, value in config.items() if key != "api_key"} for config in profiles],
        "tests": TESTS,
        "results": results,
    }, indent=2) + "\n")

    print(f"profiles={', '.join(config['id'] for config in profiles)} tests={len(TESTS)}")
    summarize(results, "jev", "gemma4:12b")
    for config in profiles:
        summarize(results, "typesafe", config["id"])
    print(f"results={output.resolve()}")


if __name__ == "__main__":
    main()
