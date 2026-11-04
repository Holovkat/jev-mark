"""Durable native System One benchmark jobs, isolated from menu selection."""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import math
import os
import platform
import re
import statistics
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def private_json(path, value):
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    os.chmod(path, 0o600)


class BenchmarkService:
    def __init__(self, gateway, store_root=None, data=None):
        self.gateway = gateway
        self.root = Path(store_root or os.environ.get('JEV_BENCHMARK_DIR') or
                         Path.home() / 'Library/Application Support/JEV Menu Bar/benchmarks')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        if data is None:
            from jev_benchmark_data import BenchmarkData
            data = BenchmarkData(self.root)
        self.data = data
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='jev-benchmarks')
        self.active = {}
        for path in self.root.glob('*/manifest.json'):
            try:
                row = json.loads(path.read_text())
                if row['status'] in {'queued', 'running'}:
                    row['status'] = 'interrupted'
                    row['updated_at'] = time.time()
                    private_json(path, row)
            except (OSError, ValueError, KeyError):
                continue

    def catalog(self):
        return self.data.catalog()

    def profiles(self):
        return [self._public_profile(p) for p in self.gateway.load_profiles()]

    @staticmethod
    def _public_profile(profile):
        # Endpoint is required for exact attribution; credentials never enter evidence.
        endpoint = urlsplit(profile['endpoint'])
        safe_endpoint = endpoint._replace(query='', fragment='', netloc=endpoint.hostname or '').geturl()
        if endpoint.port:
            host = endpoint.hostname or ''
            if ':' in host:
                host = '[' + host + ']'
            safe_endpoint = endpoint._replace(query='', fragment='', netloc=f'{host}:{endpoint.port}').geturl()
        return {k: profile[k] for k in ('id', 'name', 'model')} | {'endpoint': safe_endpoint, 'endpoint_hash': hashlib.sha256(profile['endpoint'].encode()).hexdigest(),
                **({'protocol': 'openai_decisions'} if profile.get('protocol') == 'openai_decisions' else {})}

    @staticmethod
    def _is_ollama(profile):
        endpoint = urlsplit(profile['endpoint'])
        return endpoint.hostname in {'localhost', '127.0.0.1', '::1'} and endpoint.port == 11434

    def _model_revision(self, profile):
        endpoint = urlsplit(profile['endpoint'])
        if endpoint.hostname not in {'localhost', '127.0.0.1', '::1'} or endpoint.port != 11434:
            return None
        try:
            url = endpoint._replace(path='/api/tags', query='', fragment='').geturl()
            with self.gateway.urlopen(url, timeout=3) as response:
                models = json.loads(response.read(1024 * 1024)).get('models', [])
            for model in models:
                if model.get('name') == profile['model'] or model.get('model') == profile['model']:
                    digest = model.get('digest')
                    return digest if isinstance(digest, str) and re.fullmatch('[a-fA-F0-9]{64}', digest) else None
        except Exception:
            pass
        return None

    def _path(self, run_id):
        if not isinstance(run_id, str) or not re.fullmatch('[a-f0-9]{32}', run_id):
            raise ValueError('Invalid run ID')
        path = self.root / run_id
        if not path.is_dir():
            raise ValueError('Run not found')
        return path

    def get_run(self, run_id, evidence=False):
        with self.lock:
            path = self._path(run_id)
            row = json.loads((path / 'manifest.json').read_text())
            if evidence:
                row['evidence'] = self._records(path)
            return row

    def list_runs(self):
        rows = []
        for path in self.root.glob('*/manifest.json'):
            try:
                rows.append(self.get_run(path.parent.name))
            except (ValueError, OSError):
                continue
        return sorted(rows, key=lambda x: x['created_at'], reverse=True)

    def start(self, options):
        with self.lock:
            return self._start(options)

    def _start(self, options):
        if not isinstance(options, dict):
            raise ValueError('Run options must be an object')
        benchmarks, profile_ids = options.get('benchmark_ids'), options.get('profile_ids')
        if not isinstance(benchmarks, list) or not benchmarks or not all(isinstance(x, str) for x in benchmarks):
            raise ValueError('Select benchmark IDs')
        if not isinstance(profile_ids, list) or not profile_ids or not all(isinstance(x, str) for x in profile_ids):
            raise ValueError('Select profile IDs')
        mode, size, seed = options.get('mode', 'sample'), options.get('sample_size', 10), options.get('seed', 0)
        if mode not in {'sample', 'full'} or type(size) is not int or not 1 <= size <= 10000 or type(seed) is not int:
            raise ValueError('Invalid cohort settings')
        profiles = {p['id']: p for p in self.gateway.load_profiles()}
        if any(p not in profiles for p in profile_ids):
            raise ValueError('A selected profile is unavailable')
        with self.lock:
            if len(self.active) >= 4:
                raise ValueError('Benchmark queue is full; wait for an active job')
        cohorts = [dict(self.data.load_cases(b, mode=mode, sample_size=size, seed=seed), benchmark_id=b) for b in dict.fromkeys(benchmarks)]
        run_id = uuid.uuid4().hex
        directory = self.root / run_id
        public = [self._public_profile(profiles[p]) for p in dict.fromkeys(profile_ids)]
        for p in public:
            p['model_revision'] = self._model_revision(profiles[p['id']])
            if self._is_ollama(profiles[p['id']]) and not p['model_revision']:
                raise ValueError('Cannot freeze local model revision')
        directory.mkdir(mode=0o700)
        now = time.time()
        row = {'id': run_id, 'status': 'queued', 'created_at': now, 'updated_at': now,
               'mode': mode, 'sample_size': size, 'seed': seed, 'profiles': public,
               'protocol': {'concurrency': 1, 'requests_per_case': 1, 'warmup': 0,
                            'timing': 'client HTTP wall clock; successful requests only',
                            'host': platform.platform(), 'p95': 'nearest rank',
                            'hosted_revision': 'Requested alias only; provider resolved revision unavailable'},
               'cohorts': [{k: v for k, v in c.items() if k != 'cases'} for c in cohorts],
               'results': []}
        for c in cohorts:
            for p in public:
                row['results'].append({'benchmark_id': c['benchmark_id'], 'profile_id': p['id'],
                    'model': p['model'], 'status': 'queued', 'total': len(c['cases']),
                    'completed': 0, 'failed': 0, 'unsupported': 0, 'score': None,
                    'median_ms': None, 'p95_ms': None, 'cohort_hash': c['cohort_hash']})
        private_json(directory / 'cohorts.json', cohorts)
        private_json(directory / 'manifest.json', row)
        self._schedule(row, cohorts, {p: copy.deepcopy(profiles[p]) for p in profile_ids})
        return row

    def _schedule(self, row, cohorts, profiles):
        event = threading.Event()
        with self.lock:
            self.active[row['id']] = event
            self.pool.submit(self._run, row['id'], cohorts, profiles, event)

    def cancel(self, run_id):
        with self.lock:
            row = self.get_run(run_id)
            if run_id in self.active:
                self.active[run_id].set()
                row['status'] = 'cancelling'
                self._save(row)
            return row

    def resume(self, run_id):
        with self.lock:
            row = self.get_run(run_id)
            if run_id in self.active:
                raise ValueError('Run is already active')
            if len(self.active) >= 4:
                raise ValueError('Benchmark queue is full; wait for an active job')
            if row['status'] not in {'cancelled', 'interrupted', 'failed'}:
                raise ValueError('Only interrupted or cancelled jobs can resume')
            current = {p['id']: p for p in self.gateway.load_profiles()}
            for p in row['profiles']:
                if p['id'] in current and self._is_ollama(current[p['id']]) and not p.get('model_revision'):
                    raise ValueError('Cannot freeze local model revision')
                if (p['id'] not in current or
                        self._public_profile(current[p['id']]) != {k: v for k, v in p.items() if k != 'model_revision'} or
                        (p.get('model_revision') and self._model_revision(current[p['id']]) != p['model_revision'])):
                    raise ValueError('Frozen model profile changed; start a new run')
            cohorts = json.loads((self._path(run_id) / 'cohorts.json').read_text())
            if any(fingerprint(c['cases']) != c.get('cohort_hash') for c in cohorts):
                raise ValueError('Frozen cohort hash mismatch; start a new run')
            row['status'] = 'queued'
            self._save(row)
            self._schedule(row, cohorts, {p['id']: copy.deepcopy(current[p['id']]) for p in row['profiles']})
            return row

    def _save(self, row):
        row['updated_at'] = time.time()
        private_json(self._path(row['id']) / 'manifest.json', row)

    @staticmethod
    def _records(path):
        records = []
        try:
            with (path / 'evidence.jsonl').open() as stream:
                for line in stream:
                    try:
                        records.append(json.loads(line))
                    except ValueError:
                        break  # Interrupted final append; earlier evidence remains usable.
        except FileNotFoundError:
            pass
        return records

    def _append(self, path, record):
        fd = os.open(path / 'evidence.jsonl', os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    @staticmethod
    def _capacity(profile, payload):
        endpoint = urlsplit(profile['endpoint'])
        if endpoint.hostname not in {'localhost', '127.0.0.1', '::1'} or endpoint.port != 11434:
            return None
        questions = payload.get('questions', {})
        if len(questions) > 64:
            return 'Native case exceeds Ollama 64-question limit'
        if len(json.dumps(payload, ensure_ascii=False).encode()) > 65536:
            return 'Native case exceeds Ollama 64 KiB body limit'
        for question in questions.values():
            criteria = question.get('criteria', {}) if isinstance(question, dict) else {}
            if question.get('type') in {'choice', 'score'} and len(criteria) > 26:
                return 'Native case exceeds Ollama 26-option limit'
        return None

    @staticmethod
    def _valid_response(questions, response):
        # Mirrors the pinned engine's Choice/Noul validation; strict finite numbers.
        answers = response.get('answers')
        if not isinstance(answers, dict) or set(answers) != set(questions):
            return False
        def probability(value):
            return type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 1
        for key, question in questions.items():
            item = answers[key]
            kind = question.get('type')
            if not isinstance(item, dict) or item.get('type') != kind:
                return False
            if kind == 'noul':
                if not probability(item.get('noul')):
                    return False
            elif kind in {'choice', 'score'}:
                criteria = question.get('criteria', {})
                expected = set(criteria) if kind == 'choice' else {str(i) for i in range(len(criteria))}
                probabilities = item.get('probabilities')
                if (not isinstance(probabilities, dict) or set(probabilities) != expected or
                        any(not probability(v) for v in probabilities.values()) or
                        abs(sum(probabilities.values()) - 1) > .01):
                    return False
                if kind == 'choice' and item.get('choice') not in expected:
                    return False
                if kind == 'score':
                    value = item.get('score')
                    if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= len(criteria) - 1:
                        return False
            else:
                return False
        return True

    @staticmethod
    def _usage(value):
        if not isinstance(value, dict):
            return {}
        return {key: count for key, count in value.items()
                if key in {'input_tokens', 'output_tokens', 'total_tokens'}
                and type(count) in {int, float} and math.isfinite(count) and count >= 0}

    def _call(self, profile, case):
        payload = {'state': case['state'], 'questions': case['questions'], 'model': profile['model']}
        unsupported = self._capacity(profile, payload)
        if unsupported:
            return {'status': 'unsupported', 'error': unsupported}
        request = Request(profile['endpoint'], data=json.dumps(payload, ensure_ascii=False).encode(),
                          headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + profile['api_key']})
        started = time.perf_counter()
        try:
            if profile.get('protocol') == 'openai_decisions':
                raw = json.dumps(self.gateway.call_openai(profile, case['state'], case['questions'])).encode()
            else:
                with self.gateway.urlopen(request, timeout=self.gateway.REQUEST_TIMEOUT) as response:
                    raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                return {'status': 'failed', 'error': 'Provider response exceeds limit'}
            answer = json.loads(raw)
            if not isinstance(answer, dict):
                return {'status': 'failed', 'error': 'Invalid response object'}
            if not self._valid_response(case['questions'], answer):
                return {'status': 'failed', 'error': 'Invalid native answer or probability distribution'}
            return {'status': 'complete', 'response': {'answers': answer['answers'], 'usage': self._usage(answer.get('usage'))}, 'latency_ms': (time.perf_counter() - started) * 1000}
        except HTTPError as error:
            status = error.code
            capacity = False
            if status in {400, 413, 422}:
                try:
                    text = error.read(4096).decode('utf-8', errors='replace').lower()
                    capacity = any(marker in text for marker in ('options per choice', 'maximum context length',
                        'maximum model length', 'context window', 'too many tokens', 'input is never truncated',
                        'the canvas holds', 'a score takes 2 to 10 levels'))
                except Exception:
                    pass
            error.close()
            return {'status': 'unsupported' if capacity else 'failed', 'http_status': status,
                    'error': 'Provider refused native case capacity' if capacity else f'Provider HTTP {status}'}
        except Exception:
            # Never persist exception text: URLs/credentials/provider bodies may be present.
            return {'status': 'failed', 'error': 'Transport or response decoding failed'}

    def _run(self, run_id, cohorts, profiles, cancelled):
        path = self._path(run_id)
        records = self._records(path)
        evidence_path = path / 'evidence.jsonl'
        if evidence_path.exists():
            raw = evidence_path.read_bytes()
            if raw and not raw.endswith(b'\n'):
                fd = os.open(evidence_path, os.O_RDWR)
                with os.fdopen(fd, 'r+b') as stream:
                    stream.truncate(raw.rfind(b'\n') + 1)
        seen = {(r['benchmark_id'], r['profile_id'], r['case_id']) for r in records}
        try:
            with self.lock:
                row = self.get_run(run_id)
                row['status'] = 'running'
                self._save(row)
            for cohort in cohorts:
                for profile_id, profile in profiles.items():
                    for case in cohort['cases']:
                        if cancelled.is_set():
                            break
                        key = (cohort['benchmark_id'], profile_id, case['id'])
                        if key in seen:
                            continue
                        result = self._call(profile, case)
                        result.update(benchmark_id=key[0], profile_id=profile_id, case_id=case['id'], run_id=case['id'],
                                      total_wall_ms=result.get('latency_ms', 0), finished_at=time.time())
                        self._append(path, result)
                        records.append(result)
                        seen.add(key)
                        with self.lock:
                            row = self.get_run(run_id)
                            self._summarize(row, cohorts, records, final=False)
                            self._save(row)
                    if cancelled.is_set():
                        break
                if cancelled.is_set():
                    break
            with self.lock:
                row = self.get_run(run_id)
                self._summarize(row, cohorts, records, final=True)
                row['status'] = ('cancelled' if cancelled.is_set() else
                                 'complete' if all(r['status'] == 'complete' for r in row['results']) else 'incomplete')
                self._save(row)
        except Exception:
            with self.lock:
                row = self.get_run(run_id)
                row['status'] = 'failed'
                row['error'] = 'Benchmark execution or native scoring failed; evidence retained'
                self._save(row)
        finally:
            with self.lock:
                self.active.pop(run_id, None)

    def _summarize(self, row, cohorts, records, final):
        by_id = {c['benchmark_id']: c for c in cohorts}
        for result in row['results']:
            subset = [r for r in records if r['benchmark_id'] == result['benchmark_id'] and r['profile_id'] == result['profile_id']]
            for key, status in [('completed', 'complete'), ('failed', 'failed'), ('unsupported', 'unsupported')]:
                result[key] = sum(r['status'] == status for r in subset)
            durations = sorted(r['latency_ms'] for r in subset if r['status'] == 'complete')
            result['median_ms'] = statistics.median(durations) if durations else None
            result['p95_ms'] = durations[math.ceil(len(durations) * .95) - 1] if durations else None
            result['status'] = 'running'
            if final:
                if len(subset) < result['total']:
                    result['status'] = 'partial'
                elif result['unsupported']:
                    result['status'] = 'unsupported'
                elif result['failed']:
                    result['status'] = 'failed'
                else:
                    score = self.data.score(result['benchmark_id'], by_id[result['benchmark_id']]['cases'], subset)
                    result.update(score)
                    result['status'] = 'complete'

    def export(self, run_id, format='json'):
        row = self.get_run(run_id, evidence=format == 'json')
        if format == 'json':
            return json.dumps(row, ensure_ascii=False, allow_nan=False)
        if format != 'csv':
            raise ValueError('Export must be json or csv')
        output = io.StringIO()
        fields = ['benchmark_id', 'profile_id', 'model', 'status', 'score', 'metric', 'total', 'completed', 'failed', 'unsupported', 'median_ms', 'p95_ms', 'cohort_hash']
        writer = csv.DictWriter(output, fields, extrasaction='ignore')
        writer.writeheader()
        for result in row['results']:
            writer.writerow({k: ('\'' + str(v) if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v) for k, v in result.items()})
        return output.getvalue()
