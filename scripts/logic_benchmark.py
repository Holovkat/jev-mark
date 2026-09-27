#!/usr/bin/env python3
"""Run concise-choice logic prompts across local Ollama models and JEV."""

from __future__ import annotations

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import Request, urlopen


TESTS = [
    {
        "id": "car-wash",
        "question": "If I wanted to wash my car at a local facility; should I walk there or drive to achieve the outcome",
        "choices": ["walk", "drive"],
        "expected": "drive",
    },
    {
        "id": "penguin-wings",
        "question": "All birds have wings. A penguin is a bird. Does a penguin have wings?",
        "choices": ["yes", "no"],
        "expected": "yes",
    },
    {
        "id": "transport-distance",
        "question": "A shop is 10 kilometres away and you have a working bicycle. To reach it efficiently, should you walk or cycle?",
        "choices": ["walk", "cycle"],
        "expected": "cycle",
    },
    {
        "id": "ice-warm-room",
        "question": "An ice cube is left in a warm room. Will it melt or freeze?",
        "choices": ["melt", "freeze"],
        "expected": "melt",
    },
    {
        "id": "dead-phone",
        "question": "A phone battery is dead and the goal is to charge it. Should you plug it in or unplug it?",
        "choices": ["plug it in", "unplug it"],
        "expected": "plug it in",
    },
    {
        "id": "square-rectangle",
        "question": "Every square is a rectangle. This object is a square. Is it a rectangle?",
        "choices": ["yes", "no"],
        "expected": "yes",
    },
    {
        "id": "rain-arrival",
        "question": "You need to arrive dry during rain. Should you take an umbrella or leave it behind?",
        "choices": ["take an umbrella", "leave it behind"],
        "expected": "take an umbrella",
    },
    {
        "id": "boiling-water",
        "question": "A recipe requires boiling water, but the water is cold. Should you heat it or chill it?",
        "choices": ["heat it", "chill it"],
        "expected": "heat it",
    },
    {
        "id": "equal-mass",
        "question": "Which is heavier: one kilogram of feathers or one kilogram of steel?",
        "choices": ["feathers", "steel", "they weigh the same"],
        "expected": "they weigh the same",
    },
    {
        "id": "red-light",
        "question": "A traffic light is red. Should a driver stop or accelerate?",
        "choices": ["stop", "accelerate"],
        "expected": "stop",
    },
    {
        "id": "refrigeration",
        "question": "Fresh food needs to stay cold for several hours. Should you put it in a refrigerator or leave it in direct sunlight?",
        "choices": ["refrigerator", "direct sunlight"],
        "expected": "refrigerator",
    },
]


def ollama_models() -> list[str]:
    output = subprocess.check_output(["ollama", "list"], text=True)
    models = []
    for line in output.splitlines():
        if not line.strip() or line.startswith("NAME"):
            continue
        models.append(line.split()[0])
    return models


def post_json(url: str, payload: dict, timeout: int = 180) -> tuple[dict, float]:
    body = json.dumps(payload).encode()
    request = Request(url, data=body, headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    with urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read())
    return result, (time.perf_counter() - started) * 1000


def ollama_call(model: str, test: dict) -> dict:
    choices = ", ".join(test["choices"])
    prompt = (
        "Answer the question using exactly one choice from the list. "
        "Return only the chosen choice, with no explanation or punctuation.\n"
        f"Choices: {choices}\nQuestion: {test['question']}"
    )
    try:
        response, elapsed = post_json(
            "http://127.0.0.1:11434/api/chat",
            {
                "model": model,
                "stream": False,
                "think": False,
                "options": {"temperature": 0},
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        content = response.get("message", {}).get("content", "").strip()
        normalized = content.lower().strip("`.* \t\n\r\"'")
        correct = normalized == test["expected"]
        return {
            "backend": "ollama",
            "model": model,
            "test": test["id"],
            "expected": test["expected"],
            "answer": content,
            "correct": correct,
            "concise": len(content.split()) <= 8,
            "elapsed_ms": round(elapsed, 1),
            "eval_tokens": response.get("eval_count"),
            "error": None,
        }
    except Exception as exc:  # keep other model results useful
        return {
            "backend": "ollama", "model": model, "test": test["id"],
            "expected": test["expected"], "answer": "", "correct": False,
            "concise": False, "elapsed_ms": None, "eval_tokens": None,
            "error": str(exc),
        }


def jev_call(test: dict, base_url: str) -> dict:
    schema = {
        "answer": {
            "type": "enum",
            "choices": test["choices"],
            "description": "Select the single logically correct answer.",
        },
        "confidence": {
            "type": "enum",
            "choices": ["high", "medium", "low"],
            "description": "How clear is the answer from the facts?",
        },
    }
    try:
        response, elapsed = post_json(
            f"{base_url}/v1/decision",
            {
                "model": "gemma4:12b",
                "instructions": "Use absolute logic. Choose only from the supplied values.",
                "schema": schema,
                "contexts": [test["question"]],
            },
        )
        decision = response["results"][0]["decision"]
        answer = str(decision["answer"])
        return {
            "backend": "jev", "model": "gemma4:12b", "test": test["id"],
            "expected": test["expected"], "answer": answer,
            "confidence": decision.get("confidence"),
            "correct": answer == test["expected"], "concise": True,
            "elapsed_ms": round(elapsed, 1),
            "eval_tokens": response.get("usage", {}).get("scored_rows"),
            "error": None,
        }
    except Exception as exc:
        return {
            "backend": "jev", "model": "gemma4:12b", "test": test["id"],
            "expected": test["expected"], "answer": "", "correct": False,
            "concise": False, "elapsed_ms": None, "eval_tokens": None,
            "error": str(exc),
        }


def main() -> None:
    output_path = Path(os.environ.get("BENCHMARK_OUTPUT", "benchmark-results.json"))
    models = ollama_models()
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, min(8, len(models)))) as pool:
        futures = [pool.submit(ollama_call, model, test) for model in models for test in TESTS]
        for future in as_completed(futures):
            results.append(future.result())
    results.extend(jev_call(test, os.environ.get("JEV_LOCAL_BASE_URL", "http://127.0.0.1:8097")) for test in TESTS)
    results.sort(key=lambda item: (item["backend"], item["model"], item["test"]))
    output_path.write_text(json.dumps({"tests": TESTS, "models": models, "results": results}, indent=2) + "\n")

    print(f"models={', '.join(models)}")
    print(f"tests={len(TESTS)} ollama_runs={len(models) * len(TESTS)} jev_runs={len(TESTS)}")
    for backend, model in [("ollama", model) for model in models] + [("jev", "gemma4:12b")]:
        subset = [r for r in results if r["backend"] == backend and r["model"] == model]
        good = sum(r["correct"] for r in subset)
        concise = sum(r["concise"] for r in subset)
        timings = [r["elapsed_ms"] for r in subset if r["elapsed_ms"] is not None]
        avg = sum(timings) / len(timings) if timings else 0
        print(f"{backend:7} {model:34} correct={good}/{len(subset)} concise={concise}/{len(subset)} avg_ms={avg:.1f}")
    print(f"results={output_path.resolve()}")


if __name__ == "__main__":
    main()
