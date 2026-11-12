"""第二轮 verifier 发现的高危项回归：读取期异常、id=0、reason 语义。"""

from __future__ import annotations

import http.client

import pytest

from core.classify import SOURCE_BGE, SOURCE_UNRESOLVED, StageSpec
from core.classify.bge import BgeStage


class _Resp:
    def __init__(self, body=None, raise_exc=None):
        self._body = body
        self._exc = raise_exc

    def read(self):
        if self._exc:
            raise self._exc
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch(monkeypatch, resp):
    import core.classify.bge as mod
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *a, **k: resp)


@pytest.mark.parametrize("exc", [
    http.client.IncompleteRead(b"partial", 190),   # 反代半包：HTTPException，非 OSError
    http.client.BadStatusLine("garbage"),
    ConnectionResetError("reset"),
])
def test_read_phase_exceptions_never_escape(monkeypatch, exc):
    """`resp.read()` 抛的 HTTPException 早先会穿出 classify()（verifier 实测 RAISED）。"""
    _patch(monkeypatch, _Resp(raise_exc=exc))

    verdicts = BgeStage(base_url="http://fake", api_key="k", timeout=1).classify(
        [{"id": "1"}, {"id": "2"}], StageSpec(kind="bge")
    )

    assert len(verdicts) == 2
    assert all(v.borderline is True and v.source == SOURCE_UNRESOLVED for v in verdicts)
    assert all(v.reason for v in verdicts), "退化成边界时必须给 reason，便于审计"


def test_id_zero_is_not_treated_as_missing(monkeypatch):
    """`id=0` 是合法主键；早先用 `or ""` 会把它当空串，导致永远回填不上。"""
    _patch(monkeypatch, _Resp(b'{"results":[{"id":0,"category":"\xe4\xba\xa4\xe9\x80\x9a","confidence":0.9}]}'))

    verdicts = BgeStage(base_url="http://fake", api_key="k", timeout=1).classify(
        [{"id": 0}], StageSpec(kind="bge")
    )

    assert verdicts[0].source == SOURCE_BGE, f"id=0 必须能回填：{verdicts[0]}"
    assert verdicts[0].category == "交通"
    assert verdicts[0].reason == ""


def test_empty_category_has_distinguishable_reason(monkeypatch):
    """模型明确返回空类别 → reason 必须能区分「没返回类别」与「判为新簇」。"""
    _patch(monkeypatch, _Resp(b'{"results":[{"id":"1","category":null,"confidence":0.5}]}'))

    verdict = BgeStage(base_url="http://fake", api_key="k", timeout=1).classify(
        [{"id": "1"}], StageSpec(kind="bge")
    )[0]

    assert verdict.source == SOURCE_UNRESOLVED
    assert verdict.reason == "no_category_returned"
    assert verdict.borderline is False, "空类别不是新簇，不该标 borderline"
