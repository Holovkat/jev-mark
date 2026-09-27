#!/usr/bin/env python3
"""Run ambiguous raw questions across local models and aggregate JEV judgements."""

from __future__ import annotations

import json
import os
import random
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from fair_judge_benchmark import raw_answer, post_json  # noqa: F401
from jev_judge import judge_case

MODELS = [
    "gemma4:12b",
    "ornith-1.5:9b",
    "SparkLLM/Spark-X2.5-4B:latest",
    "granite4.2:latest",
]

TESTS = [
    {"id": "tallest", "question": "A is taller than B, and C is taller than B. Who is tallest?", "choices": ["A", "B", "C", "cannot determine"], "expected": "cannot determine", "rubric": "Do not infer a relationship between A and C that is not stated."},
    {"id": "coffee-safety", "question": "A cup of coffee has been sitting on a desk for two hours. Is it safe to drink?", "choices": ["yes", "no", "cannot determine"], "expected": "cannot determine", "rubric": "The answer depends on temperature, ingredients, contamination, and other missing facts."},
    {"id": "telescope", "question": "I saw the man with the telescope. Who had the telescope?", "choices": ["I did", "the man did", "cannot determine"], "expected": "cannot determine", "rubric": "The sentence is grammatically ambiguous; either person could have the telescope."},
    {"id": "airport", "question": "Your flight leaves at 11:00. The drive normally takes 30 minutes, but traffic and airport security are unknown. Should you leave at 9:00 or 9:30?", "choices": ["9:00", "9:30", "cannot determine from the facts"], "expected": "cannot determine from the facts", "rubric": "A reliable departure time requires traffic, airport, check-in, and baggage assumptions."},
    {"id": "road-sign", "question": "A sign says 'No entry except local access'. You need to visit a friend who lives on that street. May you enter?", "choices": ["yes", "no", "depends on the legal meaning of local access"], "expected": "depends on the legal meaning of local access", "rubric": "Interpretation depends on the jurisdiction and whether visiting a resident qualifies as local access."},
    {"id": "lights-off", "question": "The lights are off in a building. Is the building empty?", "choices": ["yes", "no", "cannot determine"], "expected": "cannot determine", "rubric": "Lights being off does not establish occupancy."},
    {"id": "store-closing", "question": "A store is advertised as open from 9:00 to 17:00. If you arrive exactly at 17:00, can you shop?", "choices": ["yes", "no", "cannot determine"], "expected": "cannot determine", "rubric": "The closing policy, clock tolerance, and whether entry is allowed at closing are unstated."},
    {"id": "medication", "question": "A label says to take a medicine twice daily. Is 8:00 and 20:00 always the correct schedule?", "choices": ["yes", "no", "follow the prescriber or label instructions"], "expected": "follow the prescriber or label instructions", "rubric": "Twice daily does not justify inventing a universal schedule; medication-specific instructions control."},
    {"id": "fastest-route", "question": "Route A is shorter than Route B. Is Route A always faster?", "choices": ["yes", "no", "cannot determine"], "expected": "no", "rubric": "Traffic, speed limits, road type, and delays can make a longer route faster."},
    {"id": "empty-box", "question": "A sealed box is light when lifted. Is it empty?", "choices": ["yes", "no", "cannot determine"], "expected": "cannot determine", "rubric": "A light box may contain light contents; weight alone does not establish emptiness."},
]


def call_raw(model: str, test: dict) -> dict:
    return raw_answer(model, test)


def main() -> None:
    available = set(__import__("logic_benchmark").ollama_models())
    models = [model for model in MODELS if model in available]
    missing = [model for model in MODELS if model not in available]
    if missing:
        print(f"warning: unavailable models skipped: {missing}")
    generated = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(call_raw, model, test) for model in models for test in TESTS]
        for future in as_completed(futures):
            generated.append(future.result())

    by_test = {test["id"]: [] for test in TESTS}
    for item in generated:
        by_test[item["test"]["id"]].append(item)
    rng = random.Random(20260924)
    cases, labels = [], {}
    for test in TESTS:
        items = by_test[test["id"]]
        ids = [f"candidate_{n}" for n in rng.sample(range(1000, 9999), len(items))]
        labels[test["id"]] = {item["model"]: candidate_id for item, candidate_id in zip(items, ids)}
        candidates = [{"id": labels[test["id"]][item["model"]], "response": item["response"]} for item in items]
        rng.shuffle(candidates)
        cases.append({"id": test["id"], "question": test["question"], "reference_answer": test["expected"], "rubric": test["rubric"], "candidates": candidates})

    judged = []
    for case in cases:
        by_label = {label: model for model, label in labels[case["id"]].items()}
        passes = []
        for _ in range(3):
            shuffled = dict(case)
            shuffled["candidates"] = list(case["candidates"])
            rng.shuffle(shuffled["candidates"])
            result = judge_case(shuffled, os.environ.get("JEV_LOCAL_BASE_URL", "http://127.0.0.1:8097"))
            result["winner_model"] = by_label.get(result["decision"]["winner"], "abstain")
            passes.append(result)
        votes = Counter(item["winner_model"] for item in passes)
        judged.append({"case_id": case["id"], "winner_model": votes.most_common(1)[0][0], "votes": dict(votes), "passes": passes})

    output = Path("ambiguity-results.json")
    output.write_text(json.dumps({"models": models, "cases": cases, "labels": labels, "judgements": judged}, indent=2) + "\n")
    print(f"models={', '.join(models)} questions={len(cases)} judgements={len(cases) * 3}")
    print(f"majority_winners={dict(Counter(item['winner_model'] for item in judged))}")
    for item in judged:
        print(f"{item['case_id']}: {item['winner_model']} votes={item['votes']}")
    print(f"results={output.resolve()}")


if __name__ == "__main__":
    main()
