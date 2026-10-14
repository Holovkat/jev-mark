"""Pinned Decision Index data and native scoring boundary (gateway needs stdlib only)."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

KIT_REVISION = '87d4650b42b377c0291a89c1f1a879f9b31082bf'
# Frozen subset hashes from Decision Index edition 0.2.1 at KIT_REVISION.
SCORING_SUBSETS_SHA256 = {
    'acos_subset_sha256': '3b20eea1613ae3e1644339e6f89a4287b307a5750a86239bb8bca6f8238b8e45',
    'retrieval_subsets_sha256': '9228a9492ea40c499d8bb024417f566d0c0ced62c71ed4c1bf908e87ed50d8df',
    'toolret_subset_sha256': 'c301d5503955c14d99485e284d434bb1533f51229c34da1edc19dd8388116f01',
    'bright_subset_sha256': 'ed3a05220e09be2b96c02514345c61894f7a0ffc73e6884a100392d23692cfb8',
    'home_appliances_subset_sha256': 'd2d0df922a47a9757bef17f382a4ed4c5c3bfff953f941c29404e93a490bce2c',
}

DEFAULT_ROOT = Path.home() / 'Library/Application Support/JEV Menu Bar/benchmarks'
BENCHMARKS = {
    'bfcl': (1, 'BFCL', 'case exact accuracy', 'https://github.com/gorilla-llm/gorilla', 'Apache-2.0'),
    'api-bank': (3, 'API-Bank', 'accuracy', 'https://github.com/AlibabaResearch/DAMO-ConvAI/tree/main/api-bank', 'Apache-2.0'),
    'banking77': (4, 'BANKING77', 'macro-F1', 'https://github.com/PolyAI-LDN/task-specific-datasets', 'CC BY 4.0'),
    'clinc150-oos': (5, 'CLINC150+OOS', 'macro-F1', 'https://github.com/clinc/oos-eval', 'CC BY 3.0'),
    'home-appliance': (9, 'Home appliance simulator', 'case exact accuracy', 'https://github.com/apolinario/decision-index', 'MIT'),
    'anli': (12, 'ANLI', 'macro-F1', 'https://huggingface.co/datasets/facebook/anli', 'CC BY-NC 4.0'),
    'routerbench': (6, 'RouterBench', 'selected quality', 'https://huggingface.co/datasets/withmartian/routerbench', 'Dataset terms unspecified; source code MIT; no redistribution'),
    'phishnchips': (56, 'PhishNChips', 'accuracy', 'https://huggingface.co/datasets/AreLit/PhishNChips', 'Mixed source terms; local evaluation only; no redistribution'),
}

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

def verify_kit(root):
    kit=Path(root)/'kit'
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=str(kit),text=True).strip()
    if head!=KIT_REVISION: raise ValueError('Decision Index kit revision mismatch; run setup again')
    subprocess.run(['git','diff','--exit-code','--quiet','HEAD'],cwd=str(kit),check=True)

def validate_manifest(metadata):
    if metadata.get('kit_revision') != KIT_REVISION:
        raise ValueError('Prepared dataset kit revision mismatch; run setup again')
    if metadata.get('edition') != '0.2.1':
        raise ValueError('Prepared dataset edition mismatch; run setup again')
    if metadata.get('scoring_subsets_sha256') != SCORING_SUBSETS_SHA256:
        raise ValueError('Prepared dataset scoring subset hashes mismatch; run setup again')

class BenchmarkData:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get('JEV_BENCHMARK_ROOT', DEFAULT_ROOT))
    def catalog(self):
        items = []
        for key, (number, name, metric, source, license_) in BENCHMARKS.items():
            path = self.root / 'datasets' / key / 'manifest.json'
            try:
                metadata = json.loads(path.read_text()) if path.exists() else {}
                if metadata.get('status') == 'ready':
                    validate_manifest(metadata)
            except (ValueError, TypeError) as exc:
                metadata = {'status': 'setup_failed', 'error': str(exc)}
            ready = metadata.get('status') == 'ready' and (path.parent / 'cases.jsonl').exists()
            items.append(dict(id=key, catalog_id=number, name=name, metric=metric, source=source, license=license_, revision=KIT_REVISION, edition='0.2.1', status=metadata.get('status','not_prepared'), ready=ready, case_count=metadata.get('case_count',0), request_count=metadata.get('request_count',0), error=metadata.get('error'), dataset_revision=metadata.get('dataset_revision'), protocol=metadata.get('protocol','Decision Index 0.2.1'), max_questions=metadata.get('max_questions'), max_options=metadata.get('max_options'), terms=metadata.get('terms',[]), terms_status=metadata.get('terms_status','recorded'), notes=metadata.get('notes','')))
        return items
    def load_cases(self, benchmark_id, mode='sample', sample_size=10, seed=0):
        if benchmark_id not in BENCHMARKS: raise ValueError('Unknown benchmark')
        if mode not in ('sample','full'): raise ValueError('Mode must be sample or full')
        entry = next(x for x in self.catalog() if x['id']==benchmark_id)
        if not entry['ready']: raise ValueError(entry.get('error') or 'Dataset is not prepared')
        folder = self.root / 'datasets' / benchmark_id
        rows = [json.loads(line) for line in (folder/'cases.jsonl').read_text().splitlines() if line.strip()]
        manifest = json.loads((folder/'manifest.json').read_text())
        validate_manifest(manifest)
        if digest(rows) != manifest['dataset_revision']: raise ValueError('Prepared dataset hash mismatch; prepare again')
        groups = {}
        for r in rows:
            e = r['_evaluation']; r['id']=e['run_id']; r['group_id']=e['group_id']; groups.setdefault(e['group_id'],[]).append(r)
        if mode=='sample':
            if isinstance(sample_size,bool) or int(sample_size)<1: raise ValueError('Sample size must be positive')
            chosen = sorted(groups, key=lambda g:digest([int(seed),benchmark_id,g]))[:int(sample_size)]
        else: chosen = sorted(groups)
        cases = [r for g in chosen for r in groups[g]]
        return dict(benchmark_id=benchmark_id,cases=cases, cohort_hash=digest(cases), revision=entry['dataset_revision'], dataset_revision=entry['dataset_revision'], kit_revision=KIT_REVISION, scorer_revision=KIT_REVISION, edition='0.2.1', protocol='Decision Index 0.2.1; complete groups; raw System One', mode=mode, seed=int(seed), total_groups=len(groups), selected_groups=len(chosen), group_ids=chosen)
    def score(self, benchmark_id, cases, records):
        payload=json.dumps(dict(benchmark_id=benchmark_id,cases=cases,records=records))
        verify_kit(self.root)
        proc=subprocess.run([str(self.root/'venv/bin/python'),str(Path(__file__).resolve()),'--score',str(self.root)],input=payload,text=True,capture_output=True,timeout=120)
        if proc.returncode: raise RuntimeError('Native scorer failed: '+proc.stderr[-1500:])
        return json.loads(proc.stdout)

def score_worker(root, data):
    import sys
    sys.path.insert(0,str(Path(root)/'kit'))
    from decision_index.scoring import report, added
    cases=data['cases']; number=BENCHMARKS[data['benchmark_id']][0]
    records=data['records']; records=list(records.values()) if isinstance(records,dict) else records
    results={}
    for r in records:
        rr=dict(r); rr['run_id']=r.get('run_id',r.get('id',r.get('case_id'))); rr['status']={'complete':'ok','failed':'error'}.get(rr.get('status'),rr.get('status')); rr.setdefault('total_wall_ms',r.get('latency_ms',r.get('duration_ms',0))); results[rr['run_id']]=rr
    complete = all(results.get(r['_evaluation']['run_id'],{}).get('status')=='ok' for r in cases)
    if number==56:
        detail=added.report(number,cases,results); observed=detail['score']; metric=detail['metric']
    else:
        groups={}
        for r in cases: groups.setdefault(r['_evaluation']['group_id'],[]).append(r)
        supported=[r for rs in groups.values() if all(results.get(x['_evaluation']['run_id'],{}).get('status')=='ok' for x in rs) for r in rs]
        detail=report.score(supported,results) if supported else {}; observed=detail.get('primary_value'); metric=detail.get('primary_metric',BENCHMARKS[data['benchmark_id']][2])
    return dict(metric=metric,value=observed if complete else None,score=observed if complete else None,observed_score=observed,complete=complete,detail=detail,scorer_revision=KIT_REVISION)

if __name__=='__main__':
    import sys
    if len(sys.argv)>1 and sys.argv[1]=='--score': print(json.dumps(score_worker(sys.argv[2],json.load(sys.stdin))))
