#!/usr/bin/env python3
"""Backfill avoided-cost metrics for cache entries and hits created before
they were recorded (safe to re-run; skips anything already filled).

Part A — entries: a `decision_cache` entry created by a live replay miss has
no stored request body, but its originating call is recoverable when exactly
one `complete` request row matches the entry's backend, model and creation
time (±30 s). Those entries gain exact metrics.

Part B — hit rows: legacy `cache_hit` rows (zero tokens) get an estimated
avoided input count from their captured request size (~4 bytes per token) and
an estimated avoided duration from the backend's mean live-call duration.
Such rows are marked `estimated=1` so exact rows stay distinguishable.

Run with the gateway stopped (the tool refuses while the analytics lock is
held). The gateway also estimates at hit time going forward, so this tool is
only needed to repair history.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jev_analytics import decision_cache_key


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(Path.home() / "Library/Application Support/JEV Menu Bar/analytics/requests.sqlite3"))
    args = ap.parse_args()

    db_path = Path(args.db).expanduser()
    if not db_path.is_file():
        print(f"no analytics DB at {db_path}", file=sys.stderr)
        return 1
    lock_path = Path(str(db_path) + ".lock")
    if lock_path.exists():
        import fcntl
        try:
            with open(lock_path, "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("analytics DB is locked — the gateway appears to be running; stop it first", file=sys.stderr)
            return 1

    db = sqlite3.connect(db_path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        # Same migration the gateway applies at startup, so the tool can also
        # repair a database that has never met the new gateway.
        if "estimated" not in {row[1] for row in db.execute("PRAGMA table_info(requests)")}:
            db.execute("ALTER TABLE requests ADD COLUMN estimated INTEGER NOT NULL DEFAULT 0")
        for column, decl in (("input_tokens", "INTEGER NOT NULL DEFAULT 0"),
                             ("output_tokens", "INTEGER NOT NULL DEFAULT 0"),
                             ("duration_ms", "REAL NOT NULL DEFAULT 0")):
            if column not in {row[1] for row in db.execute("PRAGMA table_info(decision_cache)")}:
                db.execute(f"ALTER TABLE decision_cache ADD COLUMN {column} {decl}")
        db.commit()

        # Part A2: metric-less entries can still be priced — their backend maps
        # to exactly one model in typesafe.json, and that is the model whose
        # rate their hits must carry. Tokens stay 0 (hit-time estimation covers
        # them); duration stays untouched.
        profile_models = {}
        typesafe = Path.home() / "Library/Application Support/JEV Menu Bar/.secure/typesafe.json"
        if typesafe.is_file():
            try:
                root = json.loads(typesafe.read_text())
                rows = root.get("configs", []) if isinstance(root, dict) else root
                for row in rows:
                    profile_id, model = row.get("id"), row.get("model")
                    if profile_id and model and not str(row.get("base_url") or row.get("endpoint") or "").startswith(
                            ("http://127.0.0.1:11434", "http://localhost:11434")):
                        profile_models["remote:" + str(profile_id)] = model
            except (ValueError, AttributeError):
                pass
        entry_model_fixed = 0
        for profile_backend, model in profile_models.items():
            cursor = db.execute("UPDATE decision_cache SET model=? WHERE backend=? AND model='unknown'",
                                (model, profile_backend))
            entry_model_fixed += cursor.rowcount

        # Part A: entries whose originating live call is uniquely recoverable.
        entry_total = entry_fixed = 0
        for entry in db.execute("SELECT request_hash, backend, model, created_at FROM decision_cache "
                                "WHERE input_tokens = 0 AND output_tokens = 0 AND duration_ms = 0").fetchall():
            entry_total += 1
            candidates = db.execute("SELECT request_id, input_tokens, output_tokens, duration_ms FROM requests "
                                    "WHERE outcome='complete' AND backend=? AND model=? "
                                    "AND ABS(started_at - ?) <= 30", (entry["backend"], entry["model"], entry["created_at"])).fetchall()
            if len(candidates) != 1:
                continue
            origin = candidates[0]
            db.execute("UPDATE decision_cache SET input_tokens=?, output_tokens=?, duration_ms=? WHERE request_hash=?",
                       (origin["input_tokens"] or 0, origin["output_tokens"] or 0,
                        origin["duration_ms"] or 0, entry["request_hash"]))
            entry_fixed += 1

        # Part B: legacy hit rows — recover the model and exact metrics from
        # the matched cache entry (key recomputed from the captured request),
        # falling back to a byte estimate when the entry is gone or itself
        # metric-less. Repaired rows without exact metrics are estimated=1.
        hit_total = hit_fixed = 0
        means = {row["backend"]: row["ms"] for row in db.execute(
            "SELECT backend, AVG(duration_ms) AS ms FROM requests WHERE outcome='complete' AND duration_ms > 0 "
            "GROUP BY backend").fetchall()}
        for hit in db.execute("SELECT r.request_id, r.backend, COALESCE(pb.body, p.bodies) AS body, "
                              "COALESCE(pb.bytes, LENGTH(p.bodies)) AS bytes "
                              "FROM requests r LEFT JOIN payloads p ON p.request_id = r.request_id "
                              "LEFT JOIN payload_bodies pb ON pb.body_hash = p.body_hash "
                              "WHERE r.outcome='cache_hit' AND (COALESCE(r.input_tokens, 0) = 0 OR r.model='unknown')").fetchall():
            hit_total += 1
            size = hit["bytes"] or 0
            model, tokens, duration, exact = None, 0, 0.0, False
            if hit["body"]:
                try:
                    body = json.loads(hit["body"])
                    request = json.loads(body["request"]["text"])
                    entry = db.execute("SELECT model, input_tokens, output_tokens, duration_ms FROM decision_cache "
                                       "WHERE request_hash=?",
                                       (decision_cache_key(request, hit["backend"]),)).fetchone()
                    if entry is not None:
                        if entry["model"] and entry["model"] != "unknown":
                            model = entry["model"]
                        if (entry["input_tokens"] or 0) > 0:
                            tokens = entry["input_tokens"]
                            duration = entry["duration_ms"] or 0.0
                            exact = True
                except (KeyError, TypeError, ValueError):
                    pass
            if tokens == 0 and size > 0:
                tokens = size // 4  # ~4 bytes per input token
            if tokens == 0 and model is None:
                continue
            db.execute("UPDATE requests SET input_tokens=?, duration_ms=COALESCE(?, duration_ms), model=COALESCE(?, model), "
                       "estimated=? WHERE request_id=?",
                       (tokens, duration if exact else means.get(hit["backend"]),
                        model, 0 if exact else 1, hit["request_id"]))
            hit_fixed += 1
        db.commit()
        print(f"entries: {entry_total} lacked metrics, {entry_fixed} recovered from unique originating calls")
        print(f"entry models: {entry_model_fixed} priced from their backend profile")
        print(f"hit rows: {hit_total} lacked tokens, {hit_fixed} backfilled with estimates (estimated=1)")
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error as error:
        print(f"sqlite error: {error}", file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
