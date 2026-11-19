import json
from types import SimpleNamespace

import pytest

from core.classify import local_bge
from core.classify.bge import BgeStage


def test_local_worker_roundtrip_preserves_scores_and_model_identity(monkeypatch):
    monkeypatch.setenv('CLASSIFY_BASE_URL','')
    for key,value in {'CLASSIFY_PYTHON':'python','CLASSIFY_ENCODER':'encoder','CLASSIFY_HEAD':'head'}.items():monkeypatch.setenv(key,value)
    calls=[]
    def run(argv,**kwargs):
        calls.append((argv,json.loads(kwargs['input'])))
        assert kwargs['env']['HF_HUB_OFFLINE']=='1'
        return SimpleNamespace(returncode=0,stdout=json.dumps({'model':{'head_sha256':'verified-test'},
            'results':[{'id':'a','category':'教育管理','confidence':.75}]}))
    monkeypatch.setattr(local_bge.subprocess,'run',run)
    result=local_bge.predict_bge([{'id':'a','title':'标题','summary':'摘要'}])
    assert calls[0][1]['items'][0]['text']=='标题\n摘要'
    assert result[0].confidence==.75 and result[0].model['head_sha256']=='verified-test'


@pytest.mark.parametrize('confidence',[float('nan'),float('inf'),-0.01,1.01])
def test_invalid_probability_rejected_by_remote_contract(confidence):
    with pytest.raises(ValueError,match='out_of_range'):
        BgeStage._parse_results({'results':[{'id':'a','category':'教育管理','confidence':confidence}]})


def test_duplicate_result_ids_rejected():
    item={'id':'a','category':'教育管理','confidence':.9}
    with pytest.raises(ValueError,match='duplicate'):
        BgeStage._parse_results({'results':[item,item]})


def test_local_worker_failure_keeps_unresolved_reason(monkeypatch):
    monkeypatch.setenv('CLASSIFY_BASE_URL','')
    for key in ('CLASSIFY_PYTHON','CLASSIFY_ENCODER','CLASSIFY_HEAD'):monkeypatch.setenv(key,'test')
    monkeypatch.setattr(local_bge.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(returncode=1,stdout=''))
    result=local_bge.predict_bge([{'id':'a','title':'标题'}])
    assert not result[0].decided and result[0].reason.startswith('bge_unavailable')
