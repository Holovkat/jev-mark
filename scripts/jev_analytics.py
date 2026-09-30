"""Metadata-only, best-effort request telemetry. No external dependencies."""
from __future__ import annotations

import csv
import io
import json
import math
import os
import queue
import re
import sqlite3
import threading
import time
import uuid
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,95}\Z")
KINDS = {"enum": "choice", "choice": "choice", "score": "score",
         "noul": "noul", "bool": "noul", "boolean": "noul"}
OUTCOMES = {"complete", "partial", "rejected", "failed", "disconnected", "interrupted", "in_progress", "unknown"}
COLUMNS = ("request_id started_at finished_at duration_ms caller purpose operation_id backend model kind "
           "contexts fields_requested fields_completed choice_fields score_fields noul_fields "
           "http_status outcome error_category input_tokens output_tokens attempt_count attempts_omitted").split()


def label(value, default="unknown"):
    return value if isinstance(value, str) and LABEL.fullmatch(value) else default


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z") if value is not None else None


def error_category(status):
    return {400: "invalid_request", 411: "length_required", 413: "request_too_large",
            422: "unsupported_schema", 429: "rate_limited", 500: "internal_error",
            502: "invalid_provider_response", 503: "backend_unavailable"}.get(status, "http_error" if status and status >= 400 else None)


class Observation:
    """Transient request context; only allowlisted scalar metadata reaches SQLite."""
    def __init__(self, headers):
        self.lock = threading.Lock()
        self.clock = time.perf_counter()
        self.row = dict.fromkeys(COLUMNS)
        self.row.update(request_id=uuid.uuid4().hex, started_at=time.time(),
                        caller=label(headers.get("X-JEV-Client")), purpose=label(headers.get("X-JEV-Purpose")),
                        operation_id=label(headers.get("X-JEV-Operation-ID"), None), backend="unknown", model="unknown",
                        kind="unknown", outcome="in_progress", attempt_count=0, attempts_omitted=0)
        self.names = set()
        self.attempts = []
        self.response_seen = False

    def payload(self, value):
        if not isinstance(value, dict):
            return
        schema, contexts = value.get("schema"), value.get("contexts")
        if not isinstance(schema, dict) or not isinstance(contexts, list):
            return
        if len(schema) > 4096 or len(contexts) > 64:
            return
        self.names = set(schema)
        counts = Counter()
        for definition in schema.values():
            kind = definition.get("type") if isinstance(definition, dict) else None
            counts[KINDS.get(kind, "other") if isinstance(kind, str) else "other"] += 1
        self.row.update(contexts=len(contexts), fields_requested=len(schema) * len(contexts),
                        kind=next(iter(counts)) if len(counts) == 1 else "mixed" if counts else "unknown",
                        **{f"{k}_fields": counts[k] * len(contexts) for k in ("choice", "score", "noul")})

    def response(self, status, value):
        self.response_seen = True
        self.row["http_status"] = status
        if not isinstance(value, dict):
            return
        results = value.get("results")
        if isinstance(results, list):
            seen = set()
            completed = 0
            for index, result in enumerate(results[:64]):
                if not isinstance(result, dict):
                    continue
                ci = result.get("context_index", index)
                if not isinstance(ci, int) or isinstance(ci, bool) or ci < 0 or ci in seen or ci >= (self.row["contexts"] or 0):
                    continue
                seen.add(ci)
                decision = result.get("decision")
                if isinstance(decision, dict):
                    completed += len(self.names.intersection(decision))
            self.row["fields_completed"] = completed
        usage = value.get("usage")
        if isinstance(usage, dict):
            for key in ("input_tokens", "output_tokens"):
                n = usage.get(key)
                if isinstance(n, int) and not isinstance(n, bool) and 0 <= n <= 2**63 - 1:
                    self.row[key] = n
        if value.get("complete") is False:
            self.row["outcome"] = "partial"

    def attempt(self, status, duration, model=None, category=None):
        with self.lock:
            self.row["attempt_count"] += 1
            if model:
                self.row["model"] = label(model)
            if len(self.attempts) < 256:
                self.attempts.append({"ordinal": self.row["attempt_count"], "http_status": status,
                                      "duration_ms": round(duration * 1000, 3),
                                      "error_category": category or error_category(status)})
            else:
                self.row["attempts_omitted"] += 1

    def finish(self, disconnected=False, unexpected=False):
        self.row.update(finished_at=time.time(), duration_ms=round((time.perf_counter() - self.clock) * 1000, 3))
        status, completed, expected = self.row["http_status"], self.row["fields_completed"], self.row["fields_requested"]
        self.row["error_category"] = error_category(status)
        if disconnected:
            outcome = "disconnected"
            self.row["error_category"] = "client_disconnected"
        elif unexpected or status is None:
            outcome = "failed"
            self.row["error_category"] = "internal_error"
        elif self.row["outcome"] == "partial" or (completed is not None and completed > 0 and
                                                    (status >= 400 or (expected is not None and completed < expected))):
            outcome = "partial"
        elif 200 <= status < 300 and (not self.response_seen or completed is None or expected is None):
            outcome = "unknown"
            self.row["error_category"] = "unmeasured_completion"
        elif 200 <= status < 300:
            outcome = "partial" if expected and completed == 0 else "complete"
        elif 400 <= status < 500:
            outcome = "rejected"
        else:
            outcome = "failed"
        self.row["outcome"] = outcome
        if not (200 <= (status or 0) < 300) and self.row["fields_completed"] is None:
            self.row["fields_completed"] = 0
        self.names.clear()


class Percentile:
    def __init__(self):
        self.values = []
        self.p = 0.5

    def step(self, value, p):
        if value is not None:
            self.values.append(value)
        self.p = p

    def finalize(self):
        if not self.values:
            return None
        values = sorted(self.values)
        x = (len(values) - 1) * self.p
        a = int(x)
        return round(values[a] + (values[min(a + 1, len(values) - 1)] - values[a]) * (x - a), 3)


class AnalyticsStore:
    def __init__(self, path, *, enabled=True, retention_days=30, max_rows=100000, queue_size=4096):
        self.path = Path(path).expanduser()
        self.enabled = enabled
        self.retention_days = max(1, min(int(retention_days), 365))
        self.max_rows = max(1, min(int(max_rows), 1000000))
        self.queue = queue.Queue(maxsize=queue_size)
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.dropped = 0
        self.previous_dropped = 0
        self.last_error = None
        self.started = time.time()
        self.collection_started = None
        self.ready = threading.Event()
        self.worker = None
        self.file_lock = None
        if enabled:
            self.worker = threading.Thread(target=self._write_loop, name="jev-analytics", daemon=True)
            self.worker.start()
            self.ready.wait(3)

    def lost(self, category="queue_full", n=1):
        with self.lock:
            self.dropped += n
            self.last_error = category

    def enqueue(self, row, attempts=()):
        if not self.enabled:
            return
        if not self.worker or not self.worker.is_alive():
            self.lost("writer_unavailable")
            return
        try:
            self.queue.put_nowait((dict(row), list(attempts)))
        except queue.Full:
            self.lost()

    def _write_loop(self):
        db = None
        try:
            import fcntl
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.file_lock = open(str(self.path) + ".lock", "a")
            os.chmod(str(self.path) + ".lock", 0o600)
            fcntl.flock(self.file_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            os.chmod(self.path, 0o600)
            db = sqlite3.connect(self.path, timeout=2)
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript('''
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT UNIQUE NOT NULL,
                  started_at REAL NOT NULL, finished_at REAL, duration_ms REAL, caller TEXT, purpose TEXT,
                  operation_id TEXT, backend TEXT, model TEXT, kind TEXT, contexts INTEGER,
                  fields_requested INTEGER, fields_completed INTEGER, choice_fields INTEGER, score_fields INTEGER,
                  noul_fields INTEGER, http_status INTEGER, outcome TEXT, error_category TEXT,
                  input_tokens INTEGER, output_tokens INTEGER, attempt_count INTEGER, attempts_omitted INTEGER);
                CREATE INDEX IF NOT EXISTS requests_time ON requests(started_at);
                CREATE INDEX IF NOT EXISTS requests_caller_time ON requests(caller, started_at);
                CREATE INDEX IF NOT EXISTS requests_backend_time ON requests(backend, started_at);
                CREATE TABLE IF NOT EXISTS attempts (
                  request_id TEXT REFERENCES requests(request_id) ON DELETE CASCADE,
                  ordinal INTEGER, http_status INTEGER, duration_ms REAL, error_category TEXT,
                  PRIMARY KEY(request_id, ordinal));
            ''')
            db.execute("INSERT OR IGNORE INTO meta VALUES ('collection_started', ?)", (str(self.started),))
            db.execute("INSERT OR IGNORE INTO meta VALUES ('dropped_updates', '0')")
            db.execute("INSERT OR IGNORE INTO meta SELECT 'coverage_start', value FROM meta WHERE key='collection_started'")
            self.collection_started = float(db.execute("SELECT value FROM meta WHERE key='collection_started'").fetchone()[0])
            self.previous_dropped = int(db.execute("SELECT value FROM meta WHERE key='dropped_updates'").fetchone()[0])
            db.execute("UPDATE requests SET outcome='interrupted', error_category='service_interrupted' WHERE outcome='in_progress'")
            db.commit()
            for suffix in ("-wal", "-shm"):
                if Path(str(self.path) + suffix).exists():
                    os.chmod(str(self.path) + suffix, 0o600)
            self.ready.set()
            next_prune = 0
            sql = ("INSERT INTO requests (" + ",".join(COLUMNS) + ") VALUES (" + ",".join("?" for _ in COLUMNS) +
                   ") ON CONFLICT(request_id) DO UPDATE SET " + ",".join(f"{c}=excluded.{c}" for c in COLUMNS[1:]))
            while not self.stop.is_set() or not self.queue.empty():
                batch = []
                try:
                    batch.append(self.queue.get(timeout=0.2))
                    while len(batch) < 64:
                        try:
                            batch.append(self.queue.get_nowait())
                        except queue.Empty:
                            break
                except queue.Empty:
                    pass
                try:
                    with db:
                        for row, attempts in batch:
                            db.execute(sql, [row.get(c) for c in COLUMNS])
                            for attempt in attempts:
                                db.execute("INSERT OR REPLACE INTO attempts VALUES (?, ?, ?, ?, ?)",
                                           (row["request_id"], attempt["ordinal"], attempt["http_status"],
                                            attempt["duration_ms"], attempt["error_category"]))
                        db.execute("UPDATE meta SET value=? WHERE key='dropped_updates'", (str(self.previous_dropped + self.dropped),))
                        if time.time() >= next_prune:
                            cutoff = time.time() - self.retention_days * 86400
                            dropped_before = db.execute("SELECT MAX(started_at) FROM (SELECT started_at FROM requests WHERE outcome != 'in_progress' "
                                                        "ORDER BY started_at DESC, seq DESC LIMIT -1 OFFSET ?)", (self.max_rows,)).fetchone()[0]
                            coverage = float(db.execute("SELECT value FROM meta WHERE key='coverage_start'").fetchone()[0])
                            coverage = max(coverage, cutoff, dropped_before or coverage)
                            db.execute("UPDATE meta SET value=? WHERE key='coverage_start'", (str(coverage),))
                            db.execute("DELETE FROM requests WHERE started_at < ? AND outcome != 'in_progress'", (cutoff,))
                            db.execute("DELETE FROM requests WHERE seq IN (SELECT seq FROM requests WHERE outcome != 'in_progress' "
                                       "ORDER BY started_at DESC, seq DESC LIMIT -1 OFFSET ?)", (self.max_rows,))
                            next_prune = time.time() + 60
                except sqlite3.Error:
                    self.lost("sqlite_write_failed", len(batch))
                finally:
                    for _ in batch:
                        self.queue.task_done()
        except (OSError, sqlite3.Error, ValueError):
            self.last_error = "storage_unavailable"
        finally:
            self.ready.set()
            if db:
                db.close()
            if self.file_lock:
                self.file_lock.close()

    def close(self):
        self.stop.set()
        if self.worker:
            self.worker.join(5)

    def flush(self, timeout=3):
        deadline = time.monotonic() + timeout
        while self.queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        return not self.queue.unfinished_tasks

    def health(self):
        alive = bool(self.worker and self.worker.is_alive() and self.collection_started is not None)
        return {"status": "disabled" if not self.enabled else "error" if not alive else "degraded" if self.previous_dropped + self.dropped or self.last_error else "ok",
                "collection_started_at": utc(self.collection_started), "process_started_at": utc(self.started),
                "dropped_updates": self.previous_dropped + self.dropped, "last_error": self.last_error,
                "queued_updates": self.queue.qsize(), "retention_days": self.retention_days, "max_rows": self.max_rows,
                "collection_scope": "POST /v1/decision through this gateway only"}

    def connect(self):
        if not self.enabled or not self.collection_started:
            raise ValueError("Analytics storage is unavailable or disabled.")
        db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        db.create_aggregate("percentile", 2, Percentile)
        return db

    @staticmethod
    def filters(params):
        def timestamp(name, default):
            text = params.get(name)
            if not text:
                return default
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError
                return parsed.timestamp()
            except (TypeError, ValueError, OverflowError):
                raise ValueError(f"{name} must be an ISO timestamp with a timezone.") from None
        end = timestamp("to", time.time())
        start = timestamp("from", end - 86400)
        if not math.isfinite(start) or not math.isfinite(end) or start >= end or end - start > 90 * 86400:
            raise ValueError("Choose an increasing date range of at most 90 days.")
        clauses, args = ["started_at >= ?", "started_at < ?"], [start, end]
        for key in ("caller", "purpose", "backend", "model", "kind", "outcome", "operation_id", "request_id"):
            value = params.get(key)
            if value:
                if label(value, None) is None:
                    raise ValueError("Invalid filter value.")
                clauses.append(f"{key} = ?")
                args.append(value)
        return " AND ".join(clauses), args, start, end

    def query(self, params, *, export=False):
        where, args, start, end = self.filters(params)
        try:
            offset = int(params.get("offset", "0"))
            limit = int(params.get("limit", "50"))
            snapshot = int(params["snapshot"]) if params.get("snapshot") else None
        except (TypeError, ValueError):
            raise ValueError("Pagination values must be integers.") from None
        if offset < 0 or offset > 1000000 or not 1 <= limit <= 200 or (snapshot is not None and not 0 <= snapshot <= 2**63 - 1):
            raise ValueError("Invalid pagination bounds.")
        with closing(self.connect()) as db:
            db.execute("BEGIN")
            if snapshot is None:
                snapshot = db.execute("SELECT COALESCE(MAX(seq),0) FROM requests").fetchone()[0]
            where += " AND seq <= ?"
            args.append(snapshot)
            if export:
                count = db.execute("SELECT COUNT(*) FROM requests WHERE " + where, args).fetchone()[0]
                if count > 10000:
                    raise ValueError("Export is limited to 10,000 rows. Narrow the date range or filters.")
                rows = db.execute("SELECT " + ",".join(COLUMNS) + " FROM requests WHERE " + where + " ORDER BY started_at DESC, seq DESC", args).fetchall()
                stream = io.StringIO(newline="")
                writer = csv.writer(stream)
                writer.writerow(COLUMNS)
                for row in rows:
                    values = dict(row)
                    for key in ("started_at", "finished_at"):
                        values[key] = utc(values[key])
                    writer.writerow([("'" + str(values[c])) if isinstance(values[c], str) and values[c].startswith(("=", "+", "-", "@", "\t", "\r")) else values[c] for c in COLUMNS])
                return stream.getvalue()
            stats = dict(db.execute("SELECT COUNT(*) AS requests, COALESCE(SUM(attempt_count),0) AS provider_attempts, "
                                    "SUM(fields_requested) AS fields_requested, SUM(fields_completed) AS fields_completed, "
                                    "SUM(choice_fields) AS choice_fields, SUM(score_fields) AS score_fields, SUM(noul_fields) AS noul_fields, "
                                    "SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, "
                                    "COUNT(duration_ms) AS latency_samples, percentile(duration_ms,0.5) AS p50_ms, percentile(duration_ms,0.95) AS p95_ms, "
                                    "SUM(CASE WHEN fields_completed IS NULL THEN 1 ELSE 0 END) AS completion_unknown "
                                    "FROM requests WHERE " + where, args).fetchone())
            outcomes = {r[0]: r[1] for r in db.execute("SELECT outcome,COUNT(*) FROM requests WHERE " + where + " GROUP BY outcome", args)}
            stats["outcomes"] = {key: outcomes.get(key, 0) for key in sorted(OUTCOMES)}
            bucket = 3600 if end - start <= 2 * 86400 else 86400
            series = [dict(r) for r in db.execute("SELECT CAST(started_at / ? AS INTEGER) * ? AS timestamp, COUNT(*) AS requests "
                                                "FROM requests WHERE " + where + " GROUP BY timestamp ORDER BY timestamp", [bucket, bucket, *args])]
            breakdowns = {}
            for key in ("caller", "purpose", "backend", "model", "kind"):
                breakdowns[key] = [dict(r) for r in db.execute(f"SELECT {key} AS label, COUNT(*) AS requests FROM requests WHERE " + where +
                                                              f" GROUP BY {key} ORDER BY requests DESC, label LIMIT 20", args)]
            rows = [dict(r) for r in db.execute("SELECT " + ",".join(COLUMNS) + " FROM requests WHERE " + where +
                                               " ORDER BY started_at DESC, seq DESC LIMIT ? OFFSET ?", [*args, limit, offset])]
            for row in rows:
                row["attempts"] = [dict(r) for r in db.execute("SELECT ordinal,http_status,duration_ms,error_category FROM attempts WHERE request_id=? ORDER BY ordinal", (row["request_id"],))]
            retained = db.execute("SELECT MIN(started_at) FROM requests").fetchone()[0]
            updated = db.execute("SELECT MAX(finished_at) FROM requests").fetchone()[0]
            coverage = float(db.execute("SELECT value FROM meta WHERE key='coverage_start'").fetchone()[0])
            return {"health": self.health(), "from": utc(start), "to": utc(end), "snapshot": snapshot,
                    "retained_from": utc(retained), "coverage_from": utc(coverage), "last_completed_at": utc(updated), "stats": stats,
                    "bucket_seconds": bucket, "series": series, "breakdowns": breakdowns, "rows": rows,
                    "offset": offset, "limit": limit, "has_more": offset + len(rows) < stats["requests"]}
