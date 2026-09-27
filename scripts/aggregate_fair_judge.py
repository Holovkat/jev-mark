#!/usr/bin/env python3
"""Repeat fair JEV judgements with shuffled candidate order and aggregate them."""

from __future__ import annotations

import json
import os
import random
from collections import Counter
from pathlib import Path

from jev_judge import judge_case


def main() -> None:
    source = Path("fair-judge-results.json")
    payload = json.loads(source.read_text())
    rng = random.Random(20260923)
    passes = 5
    aggregate = []
    for case in payload["cases"]:
        by_label = {label: model for model, label in payload["labels"][case["id"]].items()}
        judgements = []
        for _ in range(passes):
            shuffled = dict(case)
            shuffled["candidates"] = list(case["candidates"])
            rng.shuffle(shuffled["candidates"])
            result = judge_case(shuffled, os.environ.get("JEV_LOCAL_BASE_URL", "http://127.0.0.1:8097"))
            result["winner_model"] = by_label.get(result["decision"]["winner"], "abstain")
            result["winner_position"] = next(
                (index + 1 for index, candidate in enumerate(shuffled["candidates"])
                 if candidate["id"] == result["decision"]["winner"]),
                None,
            )
            judgements.append(result)
        model_counts = Counter(item["winner_model"] for item in judgements)
        aggregate.append({
            "case_id": case["id"],
            "winner_model": model_counts.most_common(1)[0][0],
            "votes": dict(model_counts),
            "winner_positions": [item["winner_position"] for item in judgements],
            "passes": judgements,
        })
    output = Path("fair-judge-aggregate.json")
    output.write_text(json.dumps({"passes": passes, "cases": aggregate}, indent=2) + "\n")
    all_models = Counter(item["winner_model"] for item in aggregate)
    positions = Counter(position for item in aggregate for position in item["winner_positions"])
    print(f"passes_per_case={passes} cases={len(aggregate)}")
    print(f"majority_winners={dict(all_models)}")
    print(f"winner_positions={dict(positions)}")
    print(f"results={output.resolve()}")


if __name__ == "__main__":
    main()
