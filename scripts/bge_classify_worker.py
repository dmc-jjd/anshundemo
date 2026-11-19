"""JSON stdin/stdout protocol; execute with the environment that owns BGE/sklearn."""
from __future__ import annotations

import contextlib
import hashlib
import json
from pathlib import Path
import sys


def classify(payload):
    import joblib
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(max(1,min(int(payload.get('threads',4)),8)))
    head_path=Path(payload['head']).resolve(strict=True)
    bundle=joblib.load(head_path)
    clf=bundle['clf'] if isinstance(bundle,dict) else bundle
    encoder=Path(payload['encoder']).resolve(strict=True)
    # A head trained on a different encoder cannot produce meaningful probabilities.
    if isinstance(bundle,dict) and bundle.get('encoder'):
        if Path(bundle['encoder']).resolve()!=encoder:raise ValueError('classifier_encoder_mismatch')
    model=SentenceTransformer(str(encoder),device='cpu',local_files_only=True)
    items=payload['items']
    vectors=model.encode([r['text'] for r in items],batch_size=max(1,int(payload.get('batch_size',32))),
        convert_to_numpy=True,normalize_embeddings=True,show_progress_bar=False)
    probabilities=np.asarray(clf.predict_proba(vectors))
    if probabilities.shape!=(len(items),len(clf.classes_)):raise ValueError('invalid_probability_shape')
    if not np.isfinite(probabilities).all():raise ValueError('non_finite_probability')
    indices=probabilities.argmax(axis=1)
    return {'model':{'kind':bundle.get('kind','') if isinstance(bundle,dict) else type(clf).__name__,
                     'head_sha256':hashlib.sha256(head_path.read_bytes()).hexdigest(),
                     'encoder':str(encoder),'head':str(head_path)},
        'results':[{'id':r['id'],'category':str(clf.classes_[idx]),'confidence':float(probabilities[i,idx])}
                   for i,(r,idx) in enumerate(zip(items,indices))]}


if __name__=='__main__':
    try:
        payload=json.load(sys.stdin)
        with contextlib.redirect_stdout(sys.stderr):result=classify(payload)
        sys.stdout.write(json.dumps(result,ensure_ascii=False))
    except Exception as exc:
        print(type(exc).__name__+': '+str(exc),file=sys.stderr)
        raise SystemExit(1)
