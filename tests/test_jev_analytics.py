"""Metadata recorder and real HTTP boundary tests. No live model or credentials."""
import contextvars
import csv
import io
import json
import sys
import tempfile
import threading
import time
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.client import HTTPConnection, RemoteDisconnected
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from jev_analytics import AnalyticsStore, Observation
from jev_service import ContextExecutor, ObservedResponse, load_gateway, make_handler

PAYLOAD = {'contexts': ['PRIVATE_CONTEXT_456'], 'schema': {'PRIVATE_FIELD_123': {'type': 'choice', 'choices': ['yes', 'no']}}}
TOKEN = 'test-only-analytics-token-0123456789abcdef'


def record(store, *, latency=100, caller='agent', status=200, n=1, done=None, when=None):
    observation = Observation({'X-JEV-Client': caller, 'X-JEV-Purpose': 'routing'})
    observation.payload({'contexts': ['private context'] * n, 'schema': {'private_name': {'type': 'choice'}}})
    observation.row.update(backend='local:test', model='test-model')
    done = n if done is None else done
    observation.response(status, {'results': [{'decision': {'private_name': 'private answer'} if i < done else {}} for i in range(n)]})
    observation.attempt(status, .02)
    observation.finish()
    observation.row['duration_ms'] = latency
    if when is not None:
        observation.row['started_at'] = when
    store.enqueue(observation.row, observation.attempts)
    assert store.flush()
    return observation


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'analytics' / 'calls.sqlite3'
        self.store = AnalyticsStore(self.path)
        self.assertEqual(self.store.health()['status'], 'ok')

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_workload_is_fields_times_contexts(self):
        observation = Observation({})
        observation.payload({'contexts': ['x', 'y'], 'schema': {'a': {'type': 'enum'}, 'b': {'type': 'score'}, 'c': {'type': 'boolean'}}})
        self.assertEqual(observation.row['fields_requested'], 6)
        self.assertEqual([observation.row[k + '_fields'] for k in ('choice', 'score', 'noul')], [2, 2, 2])
        self.assertEqual(observation.row['kind'], 'mixed')

    def test_summary_counts_and_percentiles(self):
        for latency in (100, 200, 300, 400, 500):
            record(self.store, latency=latency, n=2)
        data = self.store.query({})
        self.assertEqual([data['stats'][k] for k in ('requests', 'provider_attempts', 'fields_completed', 'p50_ms', 'p95_ms')], [5, 5, 10, 300, 480])
        self.assertEqual(sum(row['requests'] for row in data['series']), 5)

    def test_partial_fields_survive_error_status(self):
        record(self.store, n=3, done=2, status=429)
        row = self.store.query({})['rows'][0]
        self.assertEqual((row['outcome'], row['fields_completed'], row['error_category']), ('partial', 2, 'rate_limited'))

    def test_incomplete_2xx_is_partial(self):
        record(self.store, n=2, done=1)
        self.assertEqual(self.store.query({})['rows'][0]['outcome'], 'partial')

    def test_missing_usage_is_not_zero(self):
        record(self.store)
        self.assertIsNone(self.store.query({})['stats']['input_tokens'])

    def test_unstructured_success_is_unknown(self):
        observation = Observation({})
        observation.row['http_status'] = 200
        observation.finish()
        self.assertEqual(observation.row['outcome'], 'unknown')
        self.assertIsNone(observation.row['fields_completed'])

    def test_missing_results_success_is_unknown(self):
        observation = Observation({})
        observation.payload(PAYLOAD)
        observation.response(200, {'unexpected': True})
        observation.finish()
        self.assertEqual(observation.row['outcome'], 'unknown')

    def test_labels_reject_scripts_formulas_and_overlong_values(self):
        observation = Observation({'X-JEV-Client': '=cmd|secret', 'X-JEV-Purpose': '<script>x</script>', 'X-JEV-Operation-ID': 'x' * 1000})
        self.assertEqual((observation.row['caller'], observation.row['purpose'], observation.row['operation_id']), ('unknown', 'unknown', None))

    def test_duplicate_and_unknown_contexts_not_double_counted(self):
        observation = Observation({})
        observation.payload({'contexts': ['a', 'b'], 'schema': {'x': {'type': 'choice'}}})
        observation.response(200, {'results': [{'context_index': 0, 'decision': {'x': 1, 'extra': 2}}, {'context_index': 0, 'decision': {'x': 1}}, {'context_index': 99, 'decision': {'x': 1}}]})
        self.assertEqual(observation.row['fields_completed'], 1)

    def test_unhashable_type_does_not_break_telemetry(self):
        observation = Observation({})
        observation.payload({'contexts': ['a'], 'schema': {'x': {'type': []}}})
        self.assertEqual(observation.row['kind'], 'other')

    def test_private_content_never_persisted(self):
        observation = Observation({'Authorization': 'SUPER_SECRET_TOKEN'})
        observation.payload(PAYLOAD)
        observation.response(200, {'results': [{'decision': {'PRIVATE_FIELD_123': 'SECRET_ANSWER'}}], 'error': 'PRIVATE_CONTEXT_456'})
        observation.finish()
        self.store.enqueue(observation.row)
        self.store.flush()
        data = json.dumps(self.store.query({}))
        for secret in ('SUPER_SECRET_TOKEN', 'PRIVATE_FIELD_123', 'PRIVATE_CONTEXT_456', 'SECRET_ANSWER'):
            self.assertNotIn(secret, data)
            for file in self.path.parent.iterdir():
                self.assertNotIn(secret.encode(), file.read_bytes())

    def test_unfinished_start_survives_restart_as_interrupted(self):
        self.store.enqueue(Observation({}).row)
        self.store.flush()
        self.store.close()
        self.store = AnalyticsStore(self.path)
        row = self.store.query({})['rows'][0]
        self.assertEqual(row['outcome'], 'interrupted')
        self.assertIsNone(row['duration_ms'])
        self.assertEqual(self.store.query({})['stats']['latency_samples'], 0)

    def test_snapshot_pagination_excludes_new_arrivals(self):
        for _ in range(3):
            record(self.store)
        first = self.store.query({'limit': '2'})
        record(self.store)
        last = self.store.query({'limit': '2', 'offset': '2', 'snapshot': str(first['snapshot'])})
        self.assertEqual(last['stats']['requests'], 3)
        self.assertEqual(len(last['rows']), 1)
        self.assertFalse(last['has_more'])
        self.assertFalse(set(r['request_id'] for r in first['rows']).intersection(r['request_id'] for r in last['rows']))

    def test_filters_control_summary_breakdown_and_export(self):
        record(self.store, caller='one')
        record(self.store, caller='two')
        data = self.store.query({'caller': 'one'})
        self.assertEqual(data['stats']['requests'], 1)
        self.assertEqual(data['breakdowns']['caller'], [{'label': 'one', 'requests': 1}])
        rows = list(csv.DictReader(io.StringIO(self.store.query({'caller': 'one'}, export=True))))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['caller'], 'one')
        self.assertTrue(rows[0]['started_at'].endswith('Z'))

    def test_invalid_dates_filters_and_pagination_rejected(self):
        cases = ({'caller': "x' OR 1=1--"}, {'limit': '1000000'}, {'offset': '-1'}, {'from': '2026-01-01'}, {'from': '2026-01-01T00:00:00Z', 'to': '2026-12-01T00:00:00Z'}, {'snapshot': '-1'}, {'snapshot': str(2**80)}, {'from': 'not-a-time'})
        for params in cases:
            with self.subTest(params=params), self.assertRaises(ValueError):
                self.store.query(params)

    def test_empty_data_has_no_fabricated_latency(self):
        data = self.store.query({})
        self.assertEqual(data['stats']['requests'], 0)
        self.assertIsNone(data['stats']['p95_ms'])
        self.assertEqual(data['rows'], [])

    def test_private_file_permissions(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)

    def test_attempt_details_bounded_but_total_preserved(self):
        observation = Observation({})
        for _ in range(300):
            observation.attempt(200, .001)
        self.assertEqual((observation.row['attempt_count'], len(observation.attempts), observation.row['attempts_omitted']), (300, 256, 44))

    def test_storage_failure_is_visible(self):
        bad = AnalyticsStore(self.path / 'cannot-create')
        self.assertEqual(bad.health()['status'], 'error')
        bad.enqueue(Observation({}).row)
        self.assertGreater(bad.health()['dropped_updates'], 0)
        bad.close()

    def test_second_writer_rejected_without_harming_first(self):
        other = AnalyticsStore(self.path)
        self.assertEqual(other.health()['status'], 'error')
        other.close()
        record(self.store)
        self.assertEqual(self.store.query({})['stats']['requests'], 1)

    def test_retention_prunes_rows_and_attempts(self):
        record(self.store, when=time.time() - 40 * 86400)
        for _ in range(4):
            record(self.store)
        self.store.close()
        self.store = AnalyticsStore(self.path, max_rows=2)
        deadline = time.monotonic() + 3
        while self.store.query({})['stats']['requests'] > 2 and time.monotonic() < deadline:
            time.sleep(.05)
        with closing(self.store.connect()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM requests').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 2)

    def test_loss_counter_survives_clean_restart(self):
        self.store.lost('queue_full', 3)
        record(self.store)
        self.store.close()
        self.store = AnalyticsStore(self.path)
        self.assertEqual(self.store.health()['dropped_updates'], 3)
        self.assertEqual(self.store.health()['status'], 'degraded')

    def test_full_queue_is_nonblocking(self):
        store = AnalyticsStore(self.path.parent / 'disabled.sqlite3', enabled=False, queue_size=1)
        store.enabled = True
        store.worker = types.SimpleNamespace(is_alive=lambda: True)
        store.enqueue(Observation({}).row)
        store.enqueue(Observation({}).row)
        self.assertEqual((store.dropped, store.queue.qsize()), (1, 1))


class Response:
    def __init__(self, status=200, body=b'{}'):
        self.status, self.body = status, body
        self.headers = {'Content-Type': 'application/json'}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return None
    def read(self):
        return self.body
    def close(self):
        pass


def fake_gateway(root):
    gateway = types.SimpleNamespace(ROOT=root, backend='remote:test', mode='ok')
    gateway.selected_backend = lambda: gateway.backend
    gateway.ThreadPoolExecutor = ThreadPoolExecutor
    gateway._REMOTE_POOL = ThreadPoolExecutor(max_workers=8)

    def open_request(request, *args, **kwargs):
        if gateway.mode == 'http_error':
            raise HTTPError(request.full_url, 429, 'PRIVATE_PROVIDER_ERROR', {}, io.BytesIO(b'secret'))
        if gateway.mode == 'transport_error':
            raise URLError('PRIVATE_ADDRESS')
        return Response()

    gateway.urlopen = open_request
    gateway.workbench_path = lambda: root / 'index.html'
    gateway.landing_path = lambda: root / 'landing.html'

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'
        def log_message(self, *args):
            pass
        def send_json(self, status, value, headers=None):
            raw = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(raw)
        def do_GET(self):
            self.send_json(200, {'status': 'ok'})
        def do_POST(self):
            if self.path.split('?', 1)[0] != '/v1/decision':
                self.send_json(404, {'error': 'Not found'})
                return
            try:
                raw_length = self.headers.get('Content-Length')
                if raw_length is None:
                    self.send_json(411, {'error': 'length required'})
                    return
                length = int(raw_length)
                if length > 16 * 1024 * 1024:
                    self.send_json(413, {'error': 'too large'})
                    return
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict) or not isinstance(payload.get('schema'), dict):
                    raise ValueError
                backend = gateway.selected_backend()
                if gateway.mode == 'disconnect':
                    raise BrokenPipeError()

                def evaluate(index):
                    request = Request('http://provider.invalid/v1/systemone', data=json.dumps({'model': 'test-model'}).encode())
                    with gateway.urlopen(request, timeout=1) as response:
                        response.read()
                    return {'context_index': index, 'decision': {key: 'SECRET_ANSWER' for key in payload['schema']}}

                indices = range(len(payload['contexts']))
                if backend.startswith('clm:'):
                    with gateway.ThreadPoolExecutor(max_workers=4) as pool:
                        results = list(pool.map(evaluate, indices))
                else:
                    results = [future.result() for future in [gateway._REMOTE_POOL.submit(evaluate, i) for i in indices]]
                if gateway.mode == 'partial':
                    results[-1]['decision'] = {}
                    self.send_json(429, {'complete': False, 'results': results, 'error': 'private text'}, {'Retry-After': '3'})
                else:
                    self.send_json(200, {'results': results})
            except HTTPError:
                self.send_json(429, {'error': 'private text'})
            except URLError:
                self.send_json(503, {'error': 'private text'})
            except (ValueError, TypeError, KeyError):
                self.send_json(400, {'error': 'private text'})

    gateway.GatewayHandler = Handler
    return gateway


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / 'index.html').write_text('<html><body>Workbench</body></html>')
        (root / 'landing.html').write_text('<html><body>Portal</body></html>')
        self.store = AnalyticsStore(root / 'data' / 'calls.sqlite3')
        self.gateway = fake_gateway(root)
        handler = make_handler(self.gateway, self.store, assets=ROOT / 'Resources/Web')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.server.handle_error = lambda *args: None
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.gateway._REMOTE_POOL.shutdown(wait=True)
        self.store.close()
        self.temp.cleanup()

    def http(self, method='GET', path='/api/analytics', payload=None, headers=None):
        connection = HTTPConnection('127.0.0.1', self.port, timeout=5)
        body = json.dumps(payload).encode() if isinstance(payload, dict) else payload
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        raw, status, result_headers = response.read(), response.status, dict(response.getheaders())
        connection.close()
        return status, result_headers, json.loads(raw) if 'json' in result_headers.get('Content-Type', '') else raw

    def test_success_preserves_payload_and_adds_request_id(self):
        status, headers, response = self.http('POST', '/v1/decision', PAYLOAD, {'X-JEV-Client': 'external-agent'})
        self.assertEqual(status, 200)
        self.assertEqual(response['results'][0]['decision'], {'PRIVATE_FIELD_123': 'SECRET_ANSWER'})
        self.store.flush()
        row = self.http()[2]['rows'][0]
        self.assertEqual(row['request_id'], headers['X-JEV-Request-ID'])
        self.assertEqual((row['caller'], row['attempt_count'], row['model'], row['outcome']), ('external-agent', 1, 'test-model', 'complete'))

    def test_invalid_json_is_counted_without_attempt(self):
        self.assertEqual(self.http('POST', '/v1/decision', b'not json')[0], 400)
        self.store.flush()
        row = self.http()[2]['rows'][0]
        self.assertEqual((row['outcome'], row['attempt_count'], row['fields_requested']), ('rejected', 0, None))

    def test_partial_response_and_retry_header_preserved(self):
        self.gateway.mode = 'partial'
        status, headers, response = self.http('POST', '/v1/decision', {**PAYLOAD, 'contexts': ['one', 'two']})
        self.assertEqual((status, headers['Retry-After'], response['complete']), (429, '3', False))
        self.store.flush()
        row = self.http()[2]['rows'][0]
        self.assertEqual((row['outcome'], row['fields_completed'], row['attempt_count']), ('partial', 1, 2))

    def test_concurrent_requests_keep_separate_attempts(self):
        payload = {**PAYLOAD, 'contexts': ['x', 'y', 'z']}
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.http('POST', '/v1/decision', payload), range(12)))
        self.assertTrue(all(result[0] == 200 for result in results))
        self.store.flush()
        data = self.http()[2]
        self.assertEqual((data['stats']['requests'], data['stats']['provider_attempts']), (12, 36))
        self.assertTrue(all(row['attempt_count'] == 3 for row in data['rows']))
        self.assertEqual(len(set(row['request_id'] for row in data['rows'])), 12)

    def test_clm_temporary_pool_propagates_context(self):
        self.gateway.backend = 'clm:test'
        self.http('POST', '/v1/decision', {**PAYLOAD, 'contexts': ['a', 'b', 'c']})
        self.store.flush()
        self.assertEqual(self.http()[2]['rows'][0]['attempt_count'], 3)

    def test_http_error_is_attempt(self):
        self.gateway.mode = 'http_error'
        self.assertEqual(self.http('POST', '/v1/decision', PAYLOAD)[0], 429)
        self.store.flush()
        row = self.http()[2]['rows'][0]
        self.assertEqual((row['attempt_count'], row['attempts'][0]['http_status']), (1, 429))

    def test_transport_error_is_attempt(self):
        self.gateway.mode = 'transport_error'
        self.assertEqual(self.http('POST', '/v1/decision', PAYLOAD)[0], 503)
        self.store.flush()
        attempt = self.http()[2]['rows'][0]['attempts'][0]
        self.assertEqual((attempt['error_category'], attempt['http_status']), ('transport_error', None))

    def test_disconnect_recorded(self):
        self.gateway.mode = 'disconnect'
        with self.assertRaises(RemoteDisconnected):
            self.http('POST', '/v1/decision', PAYLOAD)
        self.store.flush()
        self.assertEqual(self.http()[2]['rows'][0]['outcome'], 'disconnected')

    def test_polling_page_loads_and_other_posts_excluded(self):
        for path in ('/', '/workbench', '/analytics', '/health', '/api/analytics', '/api/analytics/health', '/api/analytics/export.csv'):
            self.assertEqual(self.http(path=path)[0], 200, path)
        self.assertEqual(self.http('POST', '/other', PAYLOAD)[0], 404)
        self.store.flush()
        self.assertEqual(self.http()[2]['stats']['requests'], 0)

    def test_navigation_and_assets_served(self):
        self.assertIn(b'/analytics/portal.js', self.http(path='/workbench')[2])
        self.assertIn(b'X-JEV-Client', self.http(path='/analytics/portal.js')[2])
        self.assertIn(b'Service analytics', self.http(path='/analytics')[2])

    def test_rebinding_forwarding_and_cross_site_blocked(self):
        for headers in ({'Host': 'attacker.example'}, {'Origin': 'https://attacker.example'}, {'Sec-Fetch-Site': 'cross-site'}, {'X-Forwarded-For': '10.0.0.2'}, {'X-Real-IP': '10.0.0.2'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.http(headers=headers)[0], 401)

    def test_remote_host_requires_configured_token(self):
        self.server.RequestHandlerClass = make_handler(self.gateway, self.store, assets=ROOT / 'Resources/Web', token=TOKEN)
        for authorization in ('', 'Bearer wrong'):
            self.assertEqual(self.http(headers={'Host': '192.168.1.3:8096', 'Authorization': authorization})[0], 401)
        self.assertEqual(self.http(headers={'Host': '192.168.1.3:8096', 'Authorization': 'Bearer ' + TOKEN})[0], 200)
        self.assertEqual(self.http(headers={'Authorization': 'Bearer ' + TOKEN, 'Origin': 'https://attacker.example'})[0], 401)

    def test_token_required_locally_when_configured(self):
        self.server.RequestHandlerClass = make_handler(self.gateway, self.store, assets=ROOT / 'Resources/Web', token=TOKEN)
        self.assertEqual(self.http()[0], 401)
        self.assertEqual(self.http(headers={'Authorization': 'Bearer ' + TOKEN})[0], 200)

    def test_bad_token_configuration_fails_closed(self):
        self.server.RequestHandlerClass = make_handler(self.gateway, self.store, assets=ROOT / 'Resources/Web', token='short')
        self.assertEqual(self.http()[0], 401)

    def test_export_and_health_protected(self):
        for path in ('/api/analytics/health', '/api/analytics/export.csv'):
            self.assertEqual(self.http(path=path, headers={'Host': 'evil.example'})[0], 401)

    def test_security_headers(self):
        headers = self.http()[1]
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])

    def test_duplicate_filters_rejected(self):
        self.assertEqual(self.http(path='/api/analytics?caller=a&caller=b')[0], 400)

    def test_disabled_recorder_does_not_block_service(self):
        self.store.enabled = False
        self.assertEqual(self.http('POST', '/v1/decision', PAYLOAD)[0], 200)
        self.assertEqual(self.http()[0], 503)
        self.assertEqual(self.http(path='/api/analytics/health')[2]['status'], 'disabled')

    def test_failed_recorder_does_not_block_service(self):
        self.store.close()
        self.assertEqual(self.http('POST', '/v1/decision', PAYLOAD)[0], 200)
        self.assertEqual(self.http()[0], 503)

    def test_metadata_exceptions_do_not_change_decisions(self):
        with patch.object(Observation, 'attempt', side_effect=ValueError('private error')):
            self.assertEqual(self.http('POST', '/v1/decision', PAYLOAD)[0], 200)
        self.store.flush()
        self.assertGreater(self.store.health()['dropped_updates'], 0)


class HelpersTests(unittest.TestCase):
    def test_response_exit_and_close_count_once(self):
        observation = Observation({})
        with ObservedResponse(Response(), observation, time.perf_counter(), 'model') as response:
            response.read()
        response.close()
        self.assertEqual(observation.row['attempt_count'], 1)

    def test_context_executor_isolation(self):
        marker = contextvars.ContextVar('test', default=None)
        with ContextExecutor(max_workers=2) as pool:
            marker.set('a')
            a = pool.submit(marker.get)
            marker.set('b')
            b = pool.submit(marker.get)
        self.assertEqual((a.result(), b.result()), ('a', 'b'))

    def test_source_and_bundled_core_resolution(self):
        import jev_service
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'jev_gateway.py').write_text("identity='source'\n")
            with patch.object(jev_service, '__file__', str(root / 'jev_service.py')):
                self.assertEqual(load_gateway().identity, 'source')
                (root / 'jev_gateway_core.py').write_text("identity='bundled'\n")
                self.assertEqual(load_gateway().identity, 'bundled')

    def test_original_gateway_handler_integration(self):
        gateway = load_gateway()
        with tempfile.TemporaryDirectory() as directory:
            store = AnalyticsStore(Path(directory) / 'calls.sqlite3')
            response_body = {'results': [{'decision': {'PRIVATE_FIELD_123': 'yes'}}]}
            with patch.object(gateway, 'selected_backend', return_value='local:test'), patch.object(gateway, 'local_payload', side_effect=lambda value: value), patch.object(gateway, 'adapt_local_response', side_effect=lambda payload, value: value), patch.object(gateway, 'urlopen', return_value=Response(body=json.dumps(response_body).encode())):
                server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(gateway, store))
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                    connection.request('POST', '/v1/decision', json.dumps(PAYLOAD), {'Content-Type': 'application/json'})
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.loads(response.read()), response_body)
                    connection.close()
                    store.flush()
                    row = store.query({})['rows'][0]
                    self.assertEqual((row['outcome'], row['attempt_count'], row['fields_completed']), ('complete', 1, 1))
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()
                    store.close()
                    gateway._REMOTE_POOL.shutdown(wait=True)


if __name__ == '__main__':
    unittest.main()
