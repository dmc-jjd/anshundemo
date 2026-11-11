"""WP-S2-B：records / locality / metrics 三域搬到 core.tools 后，守住"薄壳 re-export"与筛选语义。"""

from __future__ import annotations

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
