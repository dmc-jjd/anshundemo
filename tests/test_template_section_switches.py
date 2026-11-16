"""模板级「第一部分重点预警 / TOP10 榜单」开关：关掉后**整段不生成**（不是留空）。

四层各有断言落点，缺一层就会出现「改了配置没生效」的假开关：

1. `rules.features` 扩成四项，未声明/脏值一律当 True（老模板零变化）；
2. 关掉的口径键（`first_warning_scope` / `ranking` + TOP10 派生键）不再写进已确认版本；
3. 模板侧：关掉 top10 不跑 TOP10 规则，并把该字段/整段从模板里去掉，删哪些块与字符
   区间记进 `omitted_sections`、渲染期照单删掉——版式保持原始文件，不再生成派生副本；
4. 下游：TOP10 的候选材料工具退出给模型的清单，保底步骤不进计划，
   `processing_features` 事件带四项，facts 不产出被关掉的口径。
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pytest

import app.main as main
import app.workflow as workflow
from app.api_views.template import (normalize_features, omitted_field_ids, omit_disabled_sections,
                                    rules_for_features)
from app.storage import Store
from app.structured_template import render_structured_docx
from test_template_processing_features import _run_report

ROOT = Path(__file__).resolve().parent.parent
CANDIDATE = 'structured_template_candidate-31a1a13f17026d1f0b73'
ALL_ON = {'dedup': True, 'classification': True, 'first_warning': True, 'top10': True}
TOP10_OFF = {**ALL_ON, 'top10': False}
WARNING_OFF = {**ALL_ON, 'first_warning': False}
BOTH_OFF = {**ALL_ON, 'first_warning': False, 'top10': False}
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
TOP10_TOOLS = {'select_materials'}


def _docx_text(payload):
    from lxml import etree as ET
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
    return '\n'.join(''.join(node.text or '' for node in paragraph.iter(W + 't'))
                     for paragraph in root.iter(W + 'p'))


@pytest.fixture(scope='module')
def demo_candidate():
    """真实候选模板（含 `b34_top10_rows` 与「负面单一重点预警」字段）。缺失时跳过。"""
    from core.config import DATA
    store = Store(DATA)
    try:
        return store.get_artifact(CANDIDATE)
    except (KeyError, FileNotFoundError):
        pytest.skip('demo 候选模板不在数据目录里')


def test_features_default_to_true_and_carry_four_switches():
    assert normalize_features({'event_threshold': .65}) == ALL_ON
    # 界面只提交口径（不带 features）时，已存开关不能被抹回默认
    assert normalize_features({'event_threshold': .65}, {'features': BOTH_OFF}) == BOTH_OFF
    # 脏值一律当开：不静默关掉客户流程
    assert normalize_features({'features': {'top10': 'yes', 'first_warning': None}})['top10'] is True


def test_disabled_scopes_are_not_written_into_rules():
    rules = rules_for_features({'event_threshold': .65, 'first_warning_scope': '', 'ranking': '',
                                'features': BOTH_OFF})
    assert 'first_warning_scope' not in rules and 'ranking' not in rules
    assert not {'top10_scope', 'top10_unit', 'top10_display', 'summary_min_chars'} & set(rules)
    assert rules['features'] == BOTH_OFF
    # 开关全开时口径照旧（逐键不变）
    full = rules_for_features({'event_threshold': .65, 'first_warning_scope': 'warning',
                               'ranking': 'negative_warning_member_count', 'features': ALL_ON})
    assert full['first_warning_scope'] == 'warning' and full['ranking'] == 'negative_warning_member_count'


def test_default_template_keeps_top10_field_and_section(demo_candidate):
    template = omit_disabled_sections(demo_candidate, ALL_ON)
    assert template is demo_candidate                     # 全开＝原样返回，零行为变化
    assert 'b34_top10_rows' in {field['id'] for field in template['fields']}
    text = _docx_text(render_structured_docx(template, {}, set()))
    assert 'TOP10' in text and '重点预警' in text


def test_top10_off_drops_field_and_whole_section(demo_candidate):
    template = omit_disabled_sections(demo_candidate, TOP10_OFF)
    ids = {field['id'] for field in template['fields']}
    assert 'b34_top10_rows' not in ids
    assert 'b34_top10_rows' in template['omitted_sections']['fields']
    assert template['omitted_sections']['blocks']                  # TOP10 表 + 表题注整块去掉
    text = _docx_text(render_structured_docx(template, {}, set()))
    assert 'TOP10' not in text
    assert '重点预警' in text                                       # 只关 TOP10，重点预警段还在


def test_first_warning_off_drops_scope_field_only(demo_candidate):
    template = omit_disabled_sections(demo_candidate, WARNING_OFF)
    ids = {field['id'] for field in template['fields']}
    assert 'b17_key_warning' not in ids
    assert 'b34_top10_rows' in ids
    text = _docx_text(render_structured_docx(template, {}, set()))
    assert '重点预警' not in text
    assert 'TOP10' in text
    # 同段其余统计字段一个字都没动（只删「引导语 + 字段 + 括注」）
    assert {'b17_total_info', 'b17_positive', 'b17_negative'} <= ids


def test_both_off_report_text_has_neither_section(demo_candidate):
    template = omit_disabled_sections(demo_candidate, BOTH_OFF)
    text = _docx_text(render_structured_docx(template, {}, set()))
    assert re.findall('TOP10', text) == []
    assert '重点预警' not in text
    assert 'b34_top10_rows' not in {field['id'] for field in template['fields']}
    # 版式不做副本：删段记录进模板，渲染期直接删，`layout_source` 仍指回原始版式
    assert not Path(template['layout_source']).name.startswith('derived-layout-')
    assert template['omitted_sections']['source_layout']['sha256'] == \
        template['source_reports'][0]['sha256']


def test_omitted_fields_match_demo_ids(demo_candidate):
    assert omitted_field_ids(demo_candidate, TOP10_OFF) == {'b34_top10_rows', 'b30_top_issue_categories'}
    assert omitted_field_ids(demo_candidate, WARNING_OFF) == {'b17_key_warning'}
    assert omitted_field_ids(demo_candidate, ALL_ON) == set()


def test_top10_off_prunes_tool_and_skips_step(tmp_path, monkeypatch):
    seen, calls = [], []
    state, events = _run_report(tmp_path, monkeypatch, TOP10_OFF, seen, calls)
    assert seen, '规划器没有被调用'
    assert not TOP10_TOOLS & set(seen[0])
    assert not TOP10_TOOLS & set(state['metadata']['available_tools'])
    assert not TOP10_TOOLS & set(calls)
    fallback = [event for event in events if event['type'] == 'fallback_started']
    assert fallback and not TOP10_TOOLS & set(fallback[0]['steps'])
    feature_events = [event for event in events if event['type'] == 'processing_features']
    assert feature_events and feature_events[0]['top10'] is False
    assert feature_events[0]['first_warning'] is True


def test_default_template_keeps_top10_tool(tmp_path, monkeypatch):
    seen, calls = [], []
    state, events = _run_report(tmp_path, monkeypatch, ALL_ON, seen, calls)
    assert seen, '规划器没有被调用'
    assert TOP10_TOOLS <= set(seen[0])
    assert TOP10_TOOLS <= set(state['metadata']['available_tools'])
    feature_events = [event for event in events if event['type'] == 'processing_features']
    assert feature_events and feature_events[0]['top10'] is True
