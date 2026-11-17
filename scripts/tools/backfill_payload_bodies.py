#!/usr/bin/env python3
"""One-time offline pass: dedupe existing payload bodies and reclaim freed pages.

Run with the gateway stopped (the tool refuses while the analytics file lock is
held). Moves every stored payload body into the content-addressed
`payload_bodies` table, blanks the inline copies, then VACUUMs so the freed
pages return to the filesystem. New requests are deduplicated by the gateway
itself; this pass covers history.
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path


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

    before = db_path.stat().st_size
    db = sqlite3.connect(db_path, timeout=10)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("CREATE TABLE IF NOT EXISTS payload_bodies ("
                         "body_hash TEXT PRIMARY KEY, body TEXT NOT NULL, bytes INTEGER NOT NULL, first_seen REAL NOT NULL);")
        if "body_hash" not in {row[1] for row in db.execute("PRAGMA table_info(payloads)")}:
            db.execute("ALTER TABLE payloads ADD COLUMN body_hash TEXT")

        rows = db.execute("SELECT request_id, started_at, bodies, bytes FROM payloads WHERE bodies != ''").fetchall()
        moved = duplicate = 0
        for request_id, started_at, bodies, size in rows:
            body_hash = hashlib.sha256(bodies.encode("utf-8")).hexdigest()
            cursor = db.execute("INSERT OR IGNORE INTO payload_bodies VALUES (?, ?, ?, ?)",
                                (body_hash, bodies, size, started_at))
            moved += cursor.rowcount
            duplicate += 1 - cursor.rowcount
            db.execute("UPDATE payloads SET bodies='', body_hash=? WHERE request_id=?", (body_hash, request_id))
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.execute("VACUUM")
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        after = db_path.stat().st_size
        print(f"payload rows processed: {len(rows)} (bodies moved: {moved}, duplicates collapsed: {duplicate})")
        print(f"distinct bodies stored: {db.execute('SELECT COUNT(*) FROM payload_bodies').fetchone()[0]}")
        print(f"DB size: {before // 1024} KiB -> {after // 1024} KiB (reclaimed {(before - after) // 1024} KiB)")
        if before == after:
            print("note: size unchanged; run again once retention has freed pages, or the freelist was already reclaimed")
    except sqlite3.Error as error:
        print(f"sqlite error: {error}", file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
