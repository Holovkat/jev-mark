#!/usr/bin/env python3
"""Observed JEV service entry point. Existing decision adapters remain unchanged."""
from __future__ import annotations

import contextvars
import hmac
import importlib.util
import ipaddress
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from jev_analytics import AnalyticsStore, Observation, label

CURRENT = contextvars.ContextVar("jev_request_observation", default=None)
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
NAV_SCRIPT = b'<script src="/analytics/portal.js" defer></script>'


def observe(observation, method, *args, **kwargs):
    """A metadata failure must not alter a decision response or provider call."""
    try:
        return getattr(observation, method)(*args, **kwargs)
    except Exception:
        report = getattr(observation, "report_error", None)
        if report:
            report("metadata_capture_failed")
        return None


def load_gateway():
    directory = Path(__file__).resolve().parent
    path = directory / "jev_gateway_core.py"
    if not path.is_file():
        path = directory / "jev_gateway.py"
    spec = importlib.util.spec_from_file_location("jev_decision_core", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ContextExecutor(ThreadPoolExecutor):
    def submit(self, fn, /, *args, **kwargs):
        return super().submit(contextvars.copy_context().run, fn, *args, **kwargs)


class ContextPool:
    def __init__(self, pool):
        self.pool = pool

    def submit(self, fn, /, *args, **kwargs):
        return self.pool.submit(contextvars.copy_context().run, fn, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.pool, name)


class ObservedResponse:
    def __init__(self, response, observation, started, model):
        self.response, self.observation, self.started, self.model = response, observation, started, model
        self.recorded = False

    def __getattr__(self, name):
        return getattr(self.response, name)

    def __enter__(self):
        self.response.__enter__()
        return self

    def __exit__(self, kind, value, traceback):
        try:
            return self.response.__exit__(kind, value, traceback)
        finally:
            self.record("transport_error" if kind else None)

    def record(self, category=None):
        if not self.recorded:
            self.recorded = True
            observe(self.observation, "attempt", getattr(self.response, "status", None),
                    time.perf_counter() - self.started, self.model, category)

    def close(self):
        try:
            return self.response.close()
        finally:
            self.record()


def instrument(gateway):
    """Instrument this module only, never urllib or executors process-wide."""
    if getattr(gateway, "_analytics_installed", False):
        return
    gateway._analytics_installed = True
    original_open, original_backend = gateway.urlopen, gateway.selected_backend

    def selected_backend():
        backend = original_backend()
        observation = CURRENT.get()
        if observation:
            observation.row["backend"] = label(backend)
            if isinstance(backend, str) and backend.startswith(("local:", "apple:", "clm:")):
                observation.row["model"] = label(backend.split(":", 1)[1])
        return backend

    def urlopen(request, *args, **kwargs):
        observation = CURRENT.get()
        if not observation or not hasattr(request, "get_method") or request.get_method() != "POST":
            return original_open(request, *args, **kwargs)
        model = None
        try:
            body = json.loads(request.data)
            if isinstance(body, dict):
                model = label(body.get("model"), None)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            pass
        started = time.perf_counter()
        try:
            response = original_open(request, *args, **kwargs)
        except HTTPError as error:
            observe(observation, "attempt", error.code, time.perf_counter() - started, model)
            raise
        except Exception:
            observe(observation, "attempt", None, time.perf_counter() - started, model, "transport_error")
            raise
        return ObservedResponse(response, observation, started, model)

    gateway.urlopen = urlopen
    gateway.selected_backend = selected_backend
    if hasattr(gateway, "_REMOTE_POOL"):
        gateway._REMOTE_POOL = ContextPool(gateway._REMOTE_POOL)
    gateway.ThreadPoolExecutor = ContextExecutor


class PayloadReader:
    def __init__(self, stream, observation):
        self.stream, self.observation = stream, observation
        self.inspected = False

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def read(self, *args, **kwargs):
        raw = self.stream.read(*args, **kwargs)
        if not self.inspected:
            self.inspected = True
            try:
                value = json.loads(raw)
            except (ValueError, TypeError, UnicodeError, RecursionError):
                pass
            else:
                observe(self.observation, "payload", value)
        return raw


def make_handler(gateway, store, *, assets=None, token=None):
    instrument(gateway)
    token = token or ""
    remote_token = token if 32 <= len(token) <= 256 and token.isascii() else ""
    roots = [Path(assets)] if assets else [Path(__file__).resolve().parent / "web", gateway.ROOT / "Resources" / "Web"]

    class AnalyticsHandler(gateway.GatewayHandler):
        _observation = None

        def _bytes(self, status, data, content_type="application/json; charset=utf-8", extra=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def _json(self, status, value):
            self._bytes(status, json.dumps(value, ensure_ascii=False, allow_nan=False).encode())

        def _asset(self, name, content_type):
            path = next((root / name for root in roots if (root / name).is_file()), None)
            if path is None:
                self._json(503, {"error": "Analytics assets are not installed."})
            else:
                try:
                    self._bytes(200, path.read_bytes(), content_type)
                except OSError:
                    self._json(503, {"error": "Analytics assets could not be read."})

        def _authorized(self):
            hosts = self.headers.get_all("Host", [])
            if len(hosts) != 1:
                return False
            host = hosts[0]
            try:
                parsed = urlsplit("http://" + host)
                if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or not parsed.hostname:
                    return False
                port = parsed.port or 80
                origin = self.headers.get("Origin")
                if origin and origin not in ("http://" + host, "https://" + host):
                    return False
                if self.headers.get("Sec-Fetch-Site") == "cross-site":
                    return False
                auth = self.headers.get("Authorization", "")
                if token:
                    return bool(remote_token) and len(auth) <= 300 and hmac.compare_digest(auth.encode(), ("Bearer " + remote_token).encode())
                peer = ipaddress.ip_address(self.client_address[0])
                if getattr(peer, "ipv4_mapped", None):
                    peer = peer.ipv4_mapped
                hostname = parsed.hostname
                local_host = hostname == "localhost"
                if not local_host:
                    try:
                        local_host = ipaddress.ip_address(hostname).is_loopback
                    except ValueError:
                        pass
                forwarded = any(self.headers.get(key) for key in ("Forwarded", "X-Forwarded-For", "X-Real-IP", "X-Forwarded-Host"))
                return peer.is_loopback and local_host and port == self.server.server_port and not forwarded
            except (ValueError, UnicodeError):
                return False

        def do_GET(self):
            parsed = urlsplit(self.path)
            path = parsed.path
            if path in ("/analytics", "/analytics/"):
                self._asset("analytics.html", "text/html; charset=utf-8")
                return
            if path == "/analytics/portal.js":
                self._asset("analytics-portal.js", "text/javascript; charset=utf-8")
                return
            if path.startswith("/api/analytics"):
                if not self._authorized():
                    self._json(401, {"error": "Open analytics on localhost on the service Mac, or provide the configured analytics access token."})
                    return
                if path == "/api/analytics/health":
                    self._json(200, store.health())
                    return
                if path not in ("/api/analytics", "/api/analytics/export.csv"):
                    self._json(404, {"error": "Not found"})
                    return
                try:
                    params = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=32)
                    if any(len(values) != 1 for values in params.values()):
                        raise ValueError("Duplicate filters are not supported.")
                    params = {key: values[0] for key, values in params.items()}
                    if store.health()["status"] in ("disabled", "error"):
                        self._json(503, {"error": "Analytics recording is disabled or unavailable.", "health": store.health()})
                        return
                    result = store.query(params, export=path.endswith(".csv"))
                    if isinstance(result, str):
                        self._bytes(200, result.encode("utf-8-sig"), "text/csv; charset=utf-8",
                                    {"Content-Disposition": 'attachment; filename="jev-service-calls.csv"'})
                    else:
                        self._json(200, result)
                except ValueError as error:
                    self._json(400, {"error": str(error)})
                except Exception:
                    self._json(503, {"error": "Analytics could not be read. Decision requests are unaffected.", "health": store.health()})
                return
            if path in ("/", "/index.html", "/landing.html", "/workbench", "/workbench.html"):
                page = gateway.workbench_path() if path.startswith("/workbench") else gateway.landing_path()
                if page:
                    try:
                        data = page.read_bytes()
                        if b"/analytics/portal.js" not in data:
                            data = data.replace(b"</body>", NAV_SCRIPT + b"</body>") if b"</body>" in data else data + NAV_SCRIPT
                        self._bytes(200, data, "text/html; charset=utf-8")
                    except OSError:
                        self._json(503, {"error": "JEV portal could not be read."})
                    return
            super().do_GET()

        def send_response(self, code, message=None):
            if self._observation:
                self._observation.row["http_status"] = code
            return super().send_response(code, message)

        def send_json(self, status, value, headers=None):
            if self._observation:
                observe(self._observation, "response", status, value)
            return super().send_json(status, value, headers)

        def end_headers(self):
            if self._observation:
                self.send_header("X-JEV-Request-ID", self._observation.row["request_id"])
            return super().end_headers()

        def do_POST(self):
            if urlsplit(self.path).path != "/v1/decision" or not store.enabled:
                return super().do_POST()
            try:
                observation = Observation(self.headers)
                observation.report_error = store.lost
                store.enqueue(observation.row)
            except Exception:
                store.lost("request_metadata_failed")
                return super().do_POST()
            self._observation = observation
            context_token = CURRENT.set(observation)
            original = self.rfile
            self.rfile = PayloadReader(original, observation)
            disconnected = unexpected = False
            try:
                return super().do_POST()
            except (BrokenPipeError, ConnectionResetError):
                disconnected = True
                raise
            except Exception:
                unexpected = True
                raise
            finally:
                self.rfile = original
                CURRENT.reset(context_token)
                observe(observation, "finish", disconnected=disconnected, unexpected=unexpected)
                try:
                    store.enqueue(observation.row, observation.attempts)
                except Exception:
                    store.lost("request_metadata_failed")
                self._observation = None

    return AnalyticsHandler


def main():
    gateway = load_gateway()

    def setting(name, default, minimum, maximum):
        try:
            return max(minimum, min(int(os.environ.get(name, default)), maximum))
        except ValueError:
            gateway.log(f"Invalid {name}; using default {default}.")
            return default

    path = os.environ.get("JEV_ANALYTICS_DB", str(Path.home() / "Library/Application Support/JEV Menu Bar/analytics/requests.sqlite3"))
    store = AnalyticsStore(path, enabled=os.environ.get("JEV_ANALYTICS_ENABLED", "1") != "0",
                           retention_days=setting("JEV_ANALYTICS_RETENTION_DAYS", 30, 1, 365),
                           max_rows=setting("JEV_ANALYTICS_MAX_ROWS", 100000, 1, 1000000))
    handler = make_handler(gateway, store, token=os.environ.get("JEV_ANALYTICS_TOKEN"))
    try:
        server = gateway.GatewayServer((gateway.GATEWAY_HOST, gateway.GATEWAY_PORT), handler)
    except OSError:
        store.close()
        raise
    gateway.log(f"gateway listening on {gateway.GATEWAY_HOST}:{gateway.GATEWAY_PORT}; analytics {store.health()['status']}")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()
        gateway.log("gateway stopped")


if __name__ == "__main__":
    main()
