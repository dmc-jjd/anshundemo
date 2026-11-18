"""WP-S2-B：records / locality / metrics 三域搬到 core.tools 后，守住"薄壳 re-export"与筛选语义。"""

from __future__ import annotations

from types import SimpleNamespace

import app.tool as tool
from app.storage import Store
from app.tool import filter_records
from app.tool_executor import RunContext
from core.tools import locality, metrics, records

DOMAIN_MODULES = {
    'import_records': 'core.tools.records',
    'filter_records': 'core.tools.records',
    'classify_records': 'core.tools.records',
    'select_materials': 'core.tools.records',
    'read_evidence': 'core.tools.records',
    'resolve_locality': 'core.tools.locality',
    'calculate_metrics': 'core.tools.metrics',
    'build_table': 'core.tools.metrics',
}

RECORDS = [
    {'id': 'r1', 'sentiment': '负面', 'warning': '已预警'},
    {'id': 'r2', 'sentiment': '负面', 'warning': '未预警'},
    {'id': 'r3', 'sentiment': '正面', 'warning': '未预警'},
    {'id': 'r4', 'sentiment': '中性', 'warning': '未预警'},
    {'id': 'r5', 'sentiment': '正面', 'warning': '已预警'},
]


def test_domain_handlers_live_in_core_modules():
    """8 个名字经 app.tool 拿到时，函数定义在哪个域模块——薄壳不能变成二次实现。"""
    assert {name: getattr(tool, name).__module__ for name in DOMAIN_MODULES} == DOMAIN_MODULES
    assert set(records.HANDLERS) == {'import_records', 'filter_records', 'classify_records',
                                     'select_materials', 'read_evidence'}
    assert set(locality.HANDLERS) == {'resolve_locality'}
    assert set(metrics.HANDLERS) == {'calculate_metrics', 'build_table'}


def test_filter_records_five_scopes_keep_original_selection(tmp_path):
    """五档 scope 的选中条数与原实现在同一批记录上一致。"""
    store = Store(tmp_path / 'data')
    ctx = RunContext(store, 's2b')
    ref = store.put_artifact('s2b', 'records', {'records': RECORDS})
    counts = {}
    for scope in ('positive', 'neutral', 'negative', 'warning', 'negative_or_warning'):
        result = filter_records({'records_ref': ref, 'scope': scope}, ctx)
        assert result.status == 'ok'
        counts[scope] = len(store.get_artifact(result.data_ref)['records'])
    assert counts == {'positive': 2, 'neutral': 1, 'negative': 2,
                      'warning': 2, 'negative_or_warning': 3}


def test_filter_records_includes_sensitive_when_contract_says_so(tmp_path, monkeypatch):
    from core.tools import vocabulary
    from copy import deepcopy

    contract = deepcopy(vocabulary.filter_contract("anshun_monthly"))
    contract["sentiment"]["scopes"]["negative"] = {"contains": ["负"], "values": ["敏感"]}

    def fake_contract(package=None):
        return contract

    monkeypatch.setattr(vocabulary, "filter_contract", fake_contract)
    store = Store(tmp_path)
    rows = list(RECORDS) + [
        {"id": "r6", "sentiment": "敏感", "warning": "未预警"},
        {"id": "r7", "sentiment": "敏感", "warning": "是"},
    ]
    ref = store.put_artifact("t1", "records", {"records": list(rows)})
    ctx = SimpleNamespace(store=store, task_id="t1", package="anshun_monthly")
    result = filter_records({"records_ref": ref, "scope": "negative"}, ctx)
    selected = {row["id"] for row in store.get_artifact(result.data_ref)["records"]}
    assert selected == {"r1", "r2", "r6", "r7"}


def test_anshun_filter_does_not_include_sensitive_by_default(tmp_path):
    store = Store(tmp_path)
    rows = list(RECORDS) + [{"id": "r6", "sentiment": "敏感", "warning": "未预警"}]
    ref = store.put_artifact("t1", "records", {"records": list(rows)})
    ctx = SimpleNamespace(store=store, task_id="t1", package="anshun_monthly")
    result = filter_records({"records_ref": ref, "scope": "negative"}, ctx)
    selected = {row["id"] for row in store.get_artifact(result.data_ref)["records"]}
    assert selected == {"r1", "r2"}
    assert "r6" not in selected
