"""WP-S2-D：events / documents 两域搬到 core.tools 后，守住 re-export、阈值来源与文档解析行为。"""

from __future__ import annotations

import pytest

import app.tool as tool
from app.ooxml import UnreadableDocument
from app.storage import Store
from app.tool import group_events, parse_report_document_tool
from app.tool_executor import RunContext
from core.tools import documents, events

DOMAIN_MODULES = {
    'propose_keyword_event_candidates': 'core.tools.events',
    'propose_vector_event_neighbors': 'core.tools.events',
    'group_events': 'core.tools.events',
    'cluster_event_themes': 'core.tools.events',
    'discover_topics': 'core.tools.events',
    'parse_report_document_tool': 'core.tools.documents',
    'compare_report_structures': 'core.tools.documents',
}


def test_events_and_documents_handlers_live_in_core_modules():
    """7 个名字经 app.tool 拿到时，函数定义在哪个域模块——薄壳不能变成二次实现。"""
    assert {name: getattr(tool, name).__module__ for name in DOMAIN_MODULES} == DOMAIN_MODULES
    assert set(events.HANDLERS) == {'propose_keyword_event_candidates',
                                    'propose_vector_event_neighbors', 'group_events',
                                    'cluster_event_themes', 'discover_topics'}
    assert set(documents.HANDLERS) == {'parse_report_document_tool', 'compare_report_structures'}


def test_group_events_default_threshold_comes_from_package_data(tmp_path):
    """不传 threshold 时取模板里的 0.65（不是 core 里的字面量）。"""
    store = Store(tmp_path / 'data')
    ctx = RunContext(store, 's2d')
    ref = store.put_artifact('s2d', 'records', {'records': [
        {'id': 'r1', 'title': '同一事件标题', 'summary': '同一事件摘要'},
        {'id': 'r2', 'title': '另一事件标题', 'summary': '另一事件摘要'},
    ]})
    result = group_events({'records_ref': ref}, ctx)
    assert store.get_artifact(result.data_ref)['method']['threshold'] == 0.65


def test_parse_report_document_tool_still_rejects_unreadable_docx(tmp_path):
    """损坏 docx 仍抛 UnreadableDocument，错误类型不因搬家改变。"""
    path = tmp_path / 'broken.docx'
    path.write_bytes(b'not an OOXML zip')
    ctx = RunContext(Store(tmp_path / 'data'), 's2d')
    with pytest.raises(UnreadableDocument):
        parse_report_document_tool({'path': str(path)}, ctx)
