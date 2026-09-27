#!/usr/bin/env python3
"""Run longer, common-knowledge reasoning questions through local agents and JEV."""

from __future__ import annotations

import json
import os
import random
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from fair_judge_benchmark import raw_answer
from jev_judge import judge_case
from logic_benchmark import ollama_models

MODELS = [
    "gemma4:12b",
    "ornith-1.5:9b",
    "SparkLLM/Spark-X2.5-4B:latest",
    "granite4.2:latest",
]

TESTS = [
    {"id": "dead-battery", "question": "You turn a car key and hear a slow clicking sound. The cabin lights were accidentally left on overnight, the dashboard is now dim, and the engine does not turn over. You have access to another car and jumper cables, but no replacement parts. What is the most direct action that addresses the likely cause?", "choices": ["jump-start or recharge the battery", "replace the tyres", "add fuel to the tank", "adjust the headlights"], "expected": "jump-start or recharge the battery", "rubric": "Connect the overnight electrical drain and dim dashboard to a discharged battery; choose the available action that restores starting power."},
    {"id": "sealed-balloon", "question": "A rubber balloon is tied shut and left in a warm car. Several hours later it is larger, but no material has been added and the knot is still intact. Which explanation best accounts for the change?", "choices": ["the trapped air expanded when warmed", "the balloon created more air", "the rubber converted into fuel", "the air disappeared through the knot"], "expected": "the trapped air expanded when warmed", "rubric": "Use the facts that the balloon is sealed and warmed; distinguish expansion from adding mass or leakage."},
    {"id": "wet-towel", "question": "Two identical wet towels are hung outside. One is spread fully open in sunlight and wind; the other is folded into a thick bundle in the shade. Assuming the same starting amount of water, which towel will normally dry first, and why?", "choices": ["the spread towel because more water is exposed to moving warm air", "the folded towel because it stores heat", "both must dry at exactly the same time", "the spread towel because sunlight creates water"], "expected": "the spread towel because more water is exposed to moving warm air", "rubric": "Reason from exposed surface area, airflow, and heat; reject claims that water is created or timing must be identical."},
    {"id": "ice-salt", "question": "A person packs ice around a drink and sprinkles salt over the ice. The ice begins melting faster and the mixture becomes colder than the original ice-water mixture. What is the best explanation?", "choices": ["salt lowers the freezing point, so melting absorbs heat", "salt generates cold without changing the ice", "the drink transfers all of its mass into the ice", "the ice becomes warmer because salt is hot"], "expected": "salt lowers the freezing point, so melting absorbs heat", "rubric": "Explain the combined freezing-point and heat-absorption effect; do not treat cold as being generated from nothing."},
    {"id": "blocked-laptop", "question": "A laptop becomes unusually hot and slows down only when used on a soft blanket. The same laptop performs normally on a hard desk, and no software changes were made. Which first response is most justified?", "choices": ["move it to a hard surface and clear its ventilation", "install a larger screen", "delete unrelated documents", "increase the display brightness"], "expected": "move it to a hard surface and clear its ventilation", "rubric": "Use the observed surface-dependent heat and performance change to identify blocked airflow as the first intervention."},
    {"id": "smoke-alarm", "question": "A smoke alarm gives one short chirp every minute, but there is no smoke, heat, or burning smell. The alarm has been installed for years and its test button has not been used recently. What should be checked first?", "choices": ["the alarm battery and its maintenance state", "whether the walls need repainting", "whether the door is locked", "whether the room needs more furniture"], "expected": "the alarm battery and its maintenance state", "rubric": "A periodic chirp from an old alarm commonly indicates a low battery or maintenance/end-of-life condition; do not ignore a safety device."},
    {"id": "plant-window", "question": "A houseplant sits in a dark room. Its soil is already wet, but its leaves are pale and new growth is weak. Someone suggests adding even more water because the plant looks unhealthy. Which change most directly addresses the stated environmental clue?", "choices": ["provide suitable light", "add more water immediately", "remove all leaves", "seal the pot in plastic"], "expected": "provide suitable light", "rubric": "Connect pale weak growth and a dark room to insufficient light; the already-wet soil argues against adding more water first."},
    {"id": "short-route-delay", "question": "A delivery driver takes a route that is two kilometres shorter than the usual route but arrives later. The shorter route includes several traffic lights and a temporary road closure, while the longer route is a clear highway. What conclusion is best supported?", "choices": ["shorter distance does not guarantee shorter travel time", "the driver must have taken a wrong turn", "highways are always shorter", "traffic lights make distance disappear"], "expected": "shorter distance does not guarantee shorter travel time", "rubric": "Use the stated delays and distinguish route length from elapsed travel time; do not invent a wrong turn."},
    {"id": "thermos-choice", "question": "You need to keep soup hot for a three-hour trip. One container is a sealed vacuum flask with a tight lid; the other is an uncovered metal bowl. Both start at the same temperature and contain the same soup. Which container is better for the stated goal?", "choices": ["the sealed vacuum flask", "the uncovered metal bowl", "both must retain heat equally", "the bowl because it is uncovered"], "expected": "the sealed vacuum flask", "rubric": "Choose the container that reduces heat transfer and evaporation; being uncovered does not preserve heat."},
    {"id": "shadow-sun", "question": "At noon, a flagpole casts a short shadow toward the east. Later in the afternoon, the same pole casts a longer shadow in a different direction. The pole has not moved. What most directly explains the change?", "choices": ["the Sun's apparent position changed as Earth rotated", "the pole grew and then shrank", "the ground moved independently of Earth", "the flagpole produced extra sunlight"], "expected": "the Sun's apparent position changed as Earth rotated", "rubric": "Use the fixed object and changing shadow direction/length to reason about the Sun's apparent movement caused by Earth's rotation."},
]


def main() -> None:
    available = set(ollama_models())
    models = [model for model in MODELS if model in available]
    rng = random.Random(20260925)
    generated = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(raw_answer, model, test) for model in models for test in TESTS]
        for future in as_completed(futures):
            generated.append(future.result())
    by_test = {test["id"]: [] for test in TESTS}
    for item in generated:
        by_test[item["test"]["id"]].append(item)

    cases, labels = [], {}
    for test in TESTS:
        items = by_test[test["id"]]
        ids = [f"candidate_{n}" for n in rng.sample(range(1000, 9999), len(items))]
        labels[test["id"]] = {item["model"]: candidate_id for item, candidate_id in zip(items, ids)}
        candidates = [{"id": labels[test["id"]][item["model"]], "response": item["response"]} for item in items]
        rng.shuffle(candidates)
        cases.append({"id": test["id"], "question": test["question"], "reference_answer": test["expected"], "rubric": test["rubric"], "candidates": candidates})

    judgements = []
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
        judgements.append({"case_id": case["id"], "winner_model": votes.most_common(1)[0][0], "votes": dict(votes), "passes": passes})

    output = Path(os.environ.get("REASONING_OUTPUT", "reasoning-results.json"))
    output.write_text(json.dumps({"models": models, "cases": cases, "labels": labels, "judgements": judgements}, indent=2) + "\n")
    print(f"models={', '.join(models)} questions={len(cases)} judgements={len(cases) * 3}")
    print(f"majority_winners={dict(Counter(item['winner_model'] for item in judgements))}")
    for item in judgements:
        print(f"{item['case_id']}: {item['winner_model']} votes={item['votes']}")
    print(f"results={output.resolve()}")


if __name__ == "__main__":
    main()
