#!/usr/bin/env python3
"""Seed the decision replay cache from captured gateway payloads.

The analytics DB stores captured request/response bodies for recent /v1/decision
calls. This tool replays them into `decision_cache` as bootstrap entries so the
replay cache is warm immediately after deployment. Requests whose recorded
backend is unknown are skipped: their cache keys could never match a live
request. Mercury-era answers were never captured (payload capture began after
the mercury backend was retired), so nothing is attributable to mercury here;
every seeded entry carries the model that actually produced it.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jev_analytics import decision_cache_key  # noqa: E402

VALID_BACKENDS = ("remote:", "local:", "apple:", "clm:")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(Path.home() / "Library/Application Support/JEV Menu Bar/analytics/requests.sqlite3"))
    ap.add_argument("--dry-run", action="store_true", help="report what would be seeded without writing")
    args = ap.parse_args()

    db_path = Path(args.db).expanduser()
    if not db_path.is_file():
        print(f"no analytics DB at {db_path}", file=sys.stderr)
        return 1
    with closing(sqlite3.connect("file:" + db_path.resolve().as_uri().removeprefix("file:") + "?mode=ro", uri=True)) as src:
        src.row_factory = sqlite3.Row
        rows = src.execute("SELECT p.request_id, COALESCE(NULLIF(p.bodies, ''), pb.body) AS bodies, "
                           "r.backend, r.model, r.input_tokens, r.output_tokens, r.duration_ms FROM payloads p "
                           "LEFT JOIN payload_bodies pb ON pb.body_hash = p.body_hash "
                           "JOIN requests r ON r.request_id = p.request_id "
                           "ORDER BY p.started_at DESC LIMIT 5000").fetchall()

    seeded = duplicate = skipped_body = skipped_backend = 0
    unique = {}
    for row in rows:
        try:
            bodies = json.loads(row["bodies"])
            request = json.loads(bodies["request"]["text"])
            response = bodies["response"]["text"]
            json.loads(response)
        except (KeyError, TypeError, ValueError):
            skipped_body += 1
            continue
        backend = row["backend"] or ""
        if not backend.startswith(VALID_BACKENDS):
            skipped_backend += 1
            continue
        key = decision_cache_key(request, backend)
        if key in unique:
            duplicate += 1
            continue
        unique[key] = (key, backend, row["model"] or "unknown", response, time.time(), "bootstrap-luna",
                       row["input_tokens"] or 0, row["output_tokens"] or 0, row["duration_ms"] or 0.0)

    print(f"captured payloads scanned: {len(rows)}")
    print(f"  usable (known backend, complete bodies): {len(unique) + duplicate}")
    print(f"  unique requests to seed: {len(unique)} (duplicates collapsed: {duplicate})")
    print(f"  skipped, unparsable bodies: {skipped_body}; unknown backend: {skipped_backend}")

    if args.dry_run:
        print("dry run: nothing written")
        return 0
    with closing(sqlite3.connect(db_path, timeout=5)) as db:
        db.execute("BEGIN")
        db.executemany("INSERT INTO decision_cache (request_hash, backend, model, response, created_at, hits, admitted_via, "
                       "input_tokens, output_tokens, duration_ms) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?) "
                       "ON CONFLICT(request_hash) DO UPDATE SET input_tokens=excluded.input_tokens, "
                       "output_tokens=excluded.output_tokens, duration_ms=excluded.duration_ms, "
                       "model=excluded.model, backend=excluded.backend", list(unique.values()))
        db.commit()
    print(f"seeded {len(unique)} bootstrap entries into decision_cache")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
