#!/usr/bin/env python3
"""Replay saved agent responses through the currently running JEV judge."""

from __future__ import annotations

import json
import os
import random
from collections import Counter
from pathlib import Path

from jev_judge import judge_case


def main() -> None:
    source = json.loads(Path(os.environ.get("SOURCE_RESULTS", "reasoning-results.json")).read_text())
    rng = random.Random(20260926)
    judged = []
    for case in source["cases"]:
        by_label = {label: model for model, label in source["labels"][case["id"]].items()}
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
    output = Path(os.environ.get("REPLAY_OUTPUT", "reasoning-results-replayed.json"))
    output.write_text(json.dumps({"source": "reasoning-results.json", "judge_model": os.environ.get("JEV_JUDGE_MODEL"), "judgements": judged}, indent=2) + "\n")
    print(f"majority_winners={dict(Counter(item['winner_model'] for item in judged))}")
    for item in judged:
        print(f"{item['case_id']}: {item['winner_model']} votes={item['votes']}")
    print(f"results={output.resolve()}")


if __name__ == "__main__":
    main()
