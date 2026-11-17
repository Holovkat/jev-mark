#!/usr/bin/env python3
"""Measure whether batch composition changes decision answers.

The stored full-batch response in the analytics DB is the free baseline. This
tool replays the same task+rubric against the live gateway in two variant
shapes — the candidates split into sub-batches, and the full batch with
shuffled candidate order — then reports, per candidate, whether the verdict
survives the change in composition. Baseline and variants use the same model,
so any disagreement isolates batch-composition effects.

Re-run triggers (the report header is compared against the previous report and
a stale warning is printed when they drift): a different model, changed
instructions/rubric, or a different candidate count.

Dry run by default; pass --yes to make the live calls (each variant carries the
X-JEV-No-Cache header so the replay cache is neither used nor populated).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3
import sys
import time
import urllib.request
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"


def load_baseline(db_path, min_contexts):
    """Newest captured payload large enough to ablate, with a complete response."""
    with closing(sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT p.request_id, COALESCE(NULLIF(p.bodies, ''), pb.body) AS bodies, "
                          "r.backend, r.model, r.started_at "
                          "FROM payloads p LEFT JOIN payload_bodies pb ON pb.body_hash = p.body_hash "
                          "JOIN requests r ON r.request_id = p.request_id "
                          "ORDER BY p.started_at DESC LIMIT 200").fetchall()
    for row in rows:
        try:
            bodies = json.loads(row["bodies"])
            request = json.loads(bodies["request"]["text"])
            response = json.loads(bodies["response"]["text"])
        except (KeyError, TypeError, ValueError):
            continue
        contexts = request.get("contexts")
        if not isinstance(contexts, list) or len(contexts) < min_contexts:
            continue
        results = response.get("results")
        if not isinstance(results, list) or len(results) < len(contexts):
            continue
        return {"request_id": row["request_id"], "backend": row["backend"], "model": row["model"],
                "request": request, "response": response, "contexts": contexts, "started_at": row["started_at"]}
    return None


def verdict_by_context(contexts, response):
    """Map each context's hash to its decision dict, via context_index."""
    by_index = {}
    for index, result in enumerate(response.get("results") or []):
        if isinstance(result, dict):
            ci = result.get("context_index", index)
            if isinstance(ci, int) and 0 <= ci < len(contexts):
                by_index[ci] = result.get("decision")
    return {hashlib.sha256(contexts[i].encode()).hexdigest(): by_index.get(i) for i in range(len(contexts))}


def call_variant(base_url, request, contexts):
    body = {"instructions": request.get("instructions"), "schema": request.get("schema"), "contexts": contexts}
    req = urllib.request.Request(base_url.rstrip("/") + "/v1/decision",
                                 data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "X-JEV-No-Cache": "1",
                                          "X-JEV-Client": "ablation", "X-JEV-Purpose": "ablation"})
    with urllib.request.urlopen(req, timeout=300) as response:
        return json.loads(response.read())


def compare(baseline_map, contexts, response):
    """Per-candidate agreement between the baseline and one variant. Only the
    candidates present in this variant are scored."""
    variant_map = verdict_by_context(contexts, response)
    rows = []
    for context in contexts:
        context_hash = hashlib.sha256(context.encode()).hexdigest()
        base = baseline_map.get(context_hash)
        rows.append({"context": context_hash[:12], "baseline": base, "variant": variant_map.get(context_hash),
                     "agree": base == variant_map.get(context_hash)})
    return rows


def stale_warning(current_header):
    """Compare against the newest previous report; drift means the ablation is stale."""
    reports = sorted(OUTPUT_DIR.glob("ablation-batch-size-*.json"))
    if not reports:
        return "no previous ablation report; this run establishes the baseline"
    try:
        previous = json.loads(reports[-1].read_text())["header"]
    except (KeyError, ValueError, OSError):
        return f"previous report {reports[-1].name} is unreadable; treat this run as the baseline"
    for key in ("model", "instruction_sha256", "candidate_count"):
        if previous.get(key) != current_header.get(key):
            return (f"ablation stale — {key} changed since {reports[-1].name} "
                    f"({previous.get(key)!r} -> {current_header.get(key)!r}); results below supersede it")
    return f"consistent with {reports[-1].name} ({previous.get('generated_at')})"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(Path.home() / "Library/Application Support/JEV Menu Bar/analytics/requests.sqlite3"))
    ap.add_argument("--base-url", default="http://127.0.0.1:8096")
    ap.add_argument("--sub-size", type=int, default=10, help="candidates per sub-batch (default 10)")
    ap.add_argument("--shuffles", type=int, default=3, help="shuffled-order full-batch replays (default 3)")
    ap.add_argument("--yes", action="store_true", help="make the live variant calls (default is a dry run)")
    args = ap.parse_args()

    baseline = load_baseline(Path(args.db).expanduser(), min_contexts=3 * args.sub_size)
    if baseline is None:
        print("no captured payload with enough contexts and a complete response; capture one first", file=sys.stderr)
        return 1

    request, contexts = baseline["request"], baseline["contexts"]
    baseline_map = verdict_by_context(contexts, baseline["response"])
    header = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "model": baseline["model"], "backend": baseline["backend"],
              "instruction_sha256": hashlib.sha256(str(request.get("instructions")).encode()).hexdigest()[:16],
              "candidate_count": len(contexts), "sub_size": args.sub_size, "shuffles": args.shuffles,
              "baseline_request_id": baseline["request_id"]}

    sub_batches = [contexts[i:i + args.sub_size] for i in range(0, len(contexts), args.sub_size)]
    rng = random.Random(0)
    shuffles = [rng.sample(contexts, len(contexts)) for _ in range(max(0, args.shuffles))]
    variants = [("sub-batch", i + 1, batch) for i, batch in enumerate(sub_batches)]
    variants += [("shuffle", i + 1, order) for i, order in enumerate(shuffles)]

    estimate = sum(len(json.dumps({"instructions": request.get("instructions"), "schema": request.get("schema"),
                                   "contexts": batch}).encode()) for _, _, batch in variants) // 4
    print(f"baseline: request {baseline['request_id']} ({len(contexts)} candidates, model {baseline['model']})")
    print(f"variants: {len(sub_batches)} sub-batches of <= {args.sub_size} + {len(shuffles)} shuffled full batches")
    print(f"estimated live input: ~{estimate:,} tokens (rough, chars/4)")
    print(f"stale check: {stale_warning(header)}")

    if not args.yes:
        print("dry run: no calls made; pass --yes to execute")
        return 0

    subset_rows, order_rows = [], []
    for kind, ordinal, batch in variants:
        started = time.time()
        response = call_variant(args.base_url, request, batch)
        rows = compare(baseline_map, batch, response)
        agreed = sum(1 for row in rows if row["agree"])
        print(f"  {kind} {ordinal}: {agreed}/{len(rows)} candidates agree ({time.time() - started:.1f}s)")
        (subset_rows if kind == "sub-batch" else order_rows).extend(
            {**row, "variant_id": f"{kind}-{ordinal}"} for row in rows)

    per_candidate = {}
    for row in subset_rows + order_rows:
        entry = per_candidate.setdefault(row["context"], {"agree": 0, "total": 0, "baseline": row["baseline"]})
        entry["total"] += 1
        entry["agree"] += row["agree"]
    stable = [c for c, e in per_candidate.items() if e["agree"] == e["total"]]
    unstable = sorted(c for c, e in per_candidate.items() if e["agree"] < e["total"])
    stability = len(stable) / len(per_candidate) if per_candidate else 0.0

    report = {"header": header,
              "summary": {"candidates": len(per_candidate), "stable": len(stable), "unstable": unstable,
                          "stability_ratio": round(stability, 3),
                          "subset_agreement": round(sum(r["agree"] for r in subset_rows) / max(1, len(subset_rows)), 3),
                          "order_agreement": round(sum(r["agree"] for r in order_rows) / max(1, len(order_rows)), 3),
                          "reading": ("batch composition is safe; keep full-size batches and let the replay cache absorb repeats"
                                      if stability >= 0.9 else
                                      "batch composition changes answers; cache admission needs consensus for the unstable candidates")},
              "subset_variants": subset_rows, "order_variants": order_rows}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"ablation-batch-size-{time.strftime('%Y%m%d-%H%M')}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"stability: {len(stable)}/{len(per_candidate)} candidates stable across all variants ({stability:.0%})")
    print(f"report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
