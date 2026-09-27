#!/usr/bin/env python3
"""Generate raw local-model answers, randomize agent labels, and judge with JEV."""

from __future__ import annotations

import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from logic_benchmark import TESTS, ollama_models, post_json  # noqa: E402
from jev_judge import judge_case  # noqa: E402


AGENT_MODELS = [
    "gemma4:12b",
    "granite4.2:latest",
    "ornith-1.5:9b",
    "SparkLLM/Spark-X2.5-4B:latest",
]


def raw_answer(model: str, test: dict) -> dict:
    choices = ", ".join(test["choices"])
    prompt = (
        "Answer this question naturally. Think through the facts in 1-3 concise sentences, "
        "then end with exactly one line in the form FINAL: <choice>. "
        "The final choice must be one of the listed choices. Do not mention this evaluation.\n\n"
        f"Choices: {choices}\nQuestion: {test['question']}"
    )
    response, elapsed = post_json("http://127.0.0.1:11434/api/chat", {
        "model": model,
        "stream": False,
        "think": False,
        "options": {"temperature": 0},
        "messages": [{"role": "user", "content": prompt}],
    })
    return {"model": model, "test": test, "response": response["message"]["content"], "elapsed_ms": round(elapsed, 1)}


def main() -> None:
    available = set(ollama_models())
    models = [model for model in AGENT_MODELS if model in available]
    if len(models) < 3:
        raise SystemExit(f"Need three configured agent models; available={sorted(available)}")

    generated = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(raw_answer, model, test) for model in models for test in TESTS]
        for future in as_completed(futures):
            generated.append(future.result())

    by_test = {test["id"]: [] for test in TESTS}
    for item in generated:
        by_test[item["test"]["id"]].append(item)

    rng = random.Random(20260922)
    cases = []
    label_maps = {}
    for test in TESTS:
        items = by_test[test["id"]]
        labels = [f"candidate_{number}" for number in rng.sample(range(1000, 10000), len(items))]
        rng.shuffle(labels)
        label_maps[test["id"]] = {item["model"]: label for item, label in zip(items, labels)}
        candidates = [
            {"id": label_maps[test["id"]][item["model"]], "response": item["response"]}
            for item in items
        ]
        rng.shuffle(candidates)
        cases.append({
            "id": test["id"],
            "question": test["question"],
            "reference_answer": test["expected"],
            "rubric": "Check the facts and whether the final choice achieves the stated outcome. Judge the reasoning, not writing style.",
            "candidates": candidates,
        })

    output = Path("fair-judge-results.json")
    result_items = []
    for case in cases:
        result_items.append(judge_case(case, os.environ.get("JEV_LOCAL_BASE_URL", "http://127.0.0.1:8097")))
    output.write_text(json.dumps({"models": models, "cases": cases, "labels": label_maps, "judgements": result_items}, indent=2) + "\n")

    print(f"agent_models={', '.join(models)} cases={len(cases)}")
    for result in result_items:
        decision = result["decision"]
        print(f"{result['case_id']}: winner={decision['winner']} confidence={decision['confidence']} p={result['fields']['winner']['probability']:.3f}")
    print(f"results={output.resolve()}")


if __name__ == "__main__":
    main()
