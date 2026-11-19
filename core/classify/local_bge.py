"""Run a trusted, locally trained BGE encoder/head in its own Python environment."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from core.classify import Verdict
from core.classify.bge import BgeStage


def deployment_identity():
    """Non-secret configuration identity used to invalidate classification checkpoints."""
    result={key:os.getenv(key,'') for key in (
        'CLASSIFY_BASE_URL','CLASSIFY_PYTHON','CLASSIFY_ENCODER','CLASSIFY_HEAD')}
    for key in ('CLASSIFY_ENCODER','CLASSIFY_HEAD'):
        path=Path(result[key]) if result[key] else None
        target=path/'model.safetensors' if path and path.is_dir() else path
        if target and target.is_file():
            stat=target.stat()
            result[key+'_stat']=[stat.st_size,stat.st_mtime_ns]
    return result


def predict_bge(records):
    if not records:return []
    base_url=os.getenv('CLASSIFY_BASE_URL','')
    if base_url:
        from core.classify import StageSpec
        return BgeStage(base_url=base_url,api_key=os.getenv('CLASSIFY_API_KEY',''),
                        timeout=float(os.getenv('CLASSIFY_TIMEOUT','30'))).classify(
                            records,StageSpec('bge',options={'batch_size':int(os.getenv('CLASSIFY_BATCH','100'))}))
    python=os.getenv('CLASSIFY_PYTHON','')
    encoder=os.getenv('CLASSIFY_ENCODER','')
    head=os.getenv('CLASSIFY_HEAD','')
    if not all((python,encoder,head)):
        return [Verdict(str(r['id']),reason='bge_not_configured',borderline=True) for r in records]
    worker=Path(__file__).resolve().parents[2]/'scripts'/'bge_classify_worker.py'
    env={**os.environ,'PYTHONIOENCODING':'utf-8','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
         'OMP_NUM_THREADS':os.getenv('CLASSIFY_THREADS','4'), 'MKL_NUM_THREADS':os.getenv('CLASSIFY_THREADS','4')}
    payload={'encoder':encoder,'head':head,'batch_size':int(os.getenv('CLASSIFY_BATCH','32')),
             'threads':int(os.getenv('CLASSIFY_THREADS','4')),
             'items':[{'id':str(r['id']),'text':(r.get('title','')+'\n'+r.get('summary','')).strip()} for r in records]}
    try:
        result=subprocess.run([python,'-B',str(worker)],input=json.dumps(payload,ensure_ascii=False),
            text=True,encoding='utf-8',capture_output=True,env=env,
            timeout=float(os.getenv('CLASSIFY_TIMEOUT','600')),
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise RuntimeError('bge_worker_failed')
        data=json.loads(result.stdout)
        by_id=BgeStage._parse_results(data)
        if set(by_id)!={str(r['id']) for r in records}:raise ValueError('bge_coverage_invalid')
        return [by_id[str(r['id'])] for r in records]
    except Exception as exc:
        # Keep the transport failure distinct from a semantic uncertainty.
        return [Verdict(str(r['id']),reason='bge_unavailable:'+type(exc).__name__,borderline=True) for r in records]
