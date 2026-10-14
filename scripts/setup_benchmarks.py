#!/usr/bin/env python3
"""Prepare only requested datasets; retain failures and pinned provenance."""
import argparse
import hashlib
import urllib.request
import json
import subprocess
import sys
from pathlib import Path
from jev_benchmark_data import BENCHMARKS, DEFAULT_ROOT, KIT_REVISION, digest, verify_kit

def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(value,indent=2)+'\n'); tmp.replace(path)

TERMS = {
    'bfcl':['https://raw.githubusercontent.com/gorilla-llm/gorilla/916260dfc116bf06793a1af79b4ec8195b0453b6/LICENSE'],
    'api-bank':['https://raw.githubusercontent.com/AlibabaResearch/DAMO-ConvAI/188835d4f9948563a6b9c8ac50cd0f3ae4021ed6/api-bank/LICENSE'],
    'banking77':['https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/LICENSE'],
    'clinc150-oos':['https://raw.githubusercontent.com/clinc/oos-eval/master/LICENSE'],
    'home-appliance':['https://raw.githubusercontent.com/apolinario/decision-index/'+KIT_REVISION+'/LICENSE'],
    'anli':['https://huggingface.co/datasets/facebook/anli/raw/8e4813d81f46d313dac7892e1c28076917cfcdf9/README.md'],
    'routerbench':['https://raw.githubusercontent.com/withmartian/routerbench/main/LICENSE','https://huggingface.co/datasets/withmartian/routerbench/raw/784021482c3f320c6619ed4b3bb3b41a21424fcb/README.md'],
    'phishnchips':['https://huggingface.co/datasets/AreLit/PhishNChips/raw/89afcc39610084298c4679159cb2e27d9ffffa46/SOURCE_LICENSES.md']}

def prepare(root, ids):
    verify_kit(root)
    sys.path.insert(0,str(root/'kit'))
    from decision_index.suite.build import acquire, rebuild, freeze, adapters_added
    from decision_index.suite.build.layout import Layout
    from decision_index.suite.io import read_jsonl
    from decision_index import editions
    layout=Layout(root/'work'); output=[]
    for key in ids:
        number,name,metric,source,terms=BENCHMARKS[key]; folder=root/'datasets'/key
        metadata=dict(id=key,kit_revision=KIT_REVISION,edition='0.2.1',source=source,license=terms,protocol='Decision Index 0.2.1')
        try:
            terms_evidence=[]
            for i,url in enumerate(TERMS[key]):
                folder.mkdir(parents=True,exist_ok=True)
                content=urllib.request.urlopen(url,timeout=60).read()
                (folder/('terms-'+str(i)+'.txt')).write_bytes(content)
                terms_evidence.append(dict(url=url,sha256=hashlib.sha256(content).hexdigest()))
            metadata['terms']=terms_evidence
            if key=='routerbench': metadata.update(terms_status='dataset_terms_unspecified',notes='Dataset terms unspecified; source code MIT; private local evaluation only; no redistribution. Known answer leakage; not in aggregate.')
            if number==56:
                adapters_added.acquire(layout,[56]); target=layout.suite/'phish-selected.jsonl'; adapters_added.build(layout,target,[56]); rows=list(read_jsonl(target))
            else:
                acquire.acquire(layout,[number]); rebuild.normalize(layout,[number]); target=layout.suite/'selected-rebuilt'; freeze.freeze(layout,target,log=lambda x:None); rows=[r for r in read_jsonl(target/'selected-rows.jsonl') if r['_evaluation']['catalog_id']==number and editions.in_edition('0.2.1')(r['_evaluation'])]
            if not rows: raise ValueError('Pinned builder produced no cases')
            folder.mkdir(parents=True,exist_ok=True); temp=folder/'cases.tmp'; temp.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows)); temp.replace(folder/'cases.jsonl')
            metadata.update(status='ready',case_count=len({r['_evaluation']['group_id'] for r in rows}),request_count=len(rows),dataset_revision=digest(rows),max_questions=max(len(r['questions']) for r in rows),max_options=max([len(q.get('criteria',{})) for r in rows for q in r['questions'].values() if q['type']=='choice'] or [0]),source_pins={spec: (acquire.GIT if spec.startswith('git:') else acquire.HF if spec.startswith('hf:') else acquire.HTTP)[spec.split(':',1)[1]] for spec in acquire.NEEDS.get(number,[])},scoring_subsets_sha256=editions.subset_sha256('0.2.1'))
            if number==56: metadata['source_pins']={spec:(adapters_added.HF if spec.startswith('hf:') else adapters_added.GIT)[spec.split(':',1)[1]] for spec in adapters_added.NEEDS[56]}
        except Exception as exc: metadata.update(status='setup_failed',error=str(exc))
        atomic(folder/'manifest.json',metadata); print(json.dumps(metadata),flush=True); output.append(metadata)
    return output

def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,default=DEFAULT_ROOT); p.add_argument('--only',nargs='+',choices=BENCHMARKS,default=list(BENCHMARKS)); p.add_argument('--worker',action='store_true'); a=p.parse_args(); root=a.root
    if sys.version_info < (3,10): raise SystemExit('Benchmark setup requires Python 3.10 or newer; the gateway can continue using Python 3.9.')
    if a.worker: prepare(root,a.only); return
    root.mkdir(parents=True,exist_ok=True); kit=root/'kit'
    if not kit.exists(): subprocess.run(['git','clone','https://github.com/apolinario/decision-index.git',str(kit)],check=True)
    subprocess.run(['git','checkout','--detach',KIT_REVISION],cwd=kit,check=True)
    python=root/'venv/bin/python'
    if not python.exists(): subprocess.run([sys.executable,'-m','venv',str(root/'venv')],check=True)
    subprocess.run([str(python),'-m','pip','install','huggingface_hub>=0.34,<2','httpx>=0.27,<1','pyarrow>=20','pandas>=2','tiktoken>=0.7'],check=True)
    subprocess.run([str(python),str(Path(__file__).resolve()),'--worker','--root',str(root),'--only',*a.only],check=True)
if __name__=='__main__': main()
