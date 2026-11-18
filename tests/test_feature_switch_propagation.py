"""两层开关的生效结果必须贯通到底：宿主落盘 → core 读到 → 渲染层剪枝（B7-1 / B7-2）。

三个断点各一条用例，缺一条就又是「工具层关了、core 照跑」的假开关：

1. **B7-1**：建报告任务时 `template_rules.features` 必须落「模板级 AND 客户包级」的生效值，
   core 的 `template_feature_switches` 只读这份值；落盘后任务级快照不可变（客户包配置再改
   不影响已建任务），只有没有快照标记的老任务才回落到「现算 AND」。
2. **B7-2**：导出渲染前按生效开关剪枝——模板是开关还开着时确认的，关掉的段落必须在这里掉；
   全开时与不传 `features` 逐字节相同（幂等）。
3. **WARNING**：数据审核算出的 `reviewed_top10` 与冻结出的 `facts.top10` 不一致时，
   事件流里必须有一条 `feature_mismatch`，不许静默（也不强行对齐数值）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

import app.workflow as workflow
from app.export import export_docx
from app.schemas import TaskState
from app.storage import Store
from core.structured_template import template_feature_switches
from test_template_section_switches import ALL_ON as TEMPLATE_ALL_ON, CANDIDATE, TOP10_OFF as TEMPLATE_TOP10_OFF, _docx_text

ALL_ON = {**TEMPLATE_ALL_ON, 'locality': True}
TOP10_OFF = {**ALL_ON, 'top10': False}


def _package(monkeypatch, **overrides):
    """把客户包级读口换成指定开关（等价于换一个客户包 manifest）。"""
    value = {**ALL_ON, **overrides}
    monkeypatch.setattr(workflow, '_package_feature_switches', lambda: dict(value))
    return value


def _store_with_task(tmp_path, template_rules):
    store = Store(tmp_path / 'store')
    store.put_task(TaskState(id='t', kind='report', phase='queued',
                             template_ref='template_version-x',
                             metadata={'template_rules': template_rules}))
    return store


def test_creation_snapshot_carries_package_off_and_core_reads_it(tmp_path, monkeypatch):
    """① 包级关 + 模板级开：落盘的是 AND 结果，core 读到的也是关。"""
    _package(monkeypatch, top10=False)
    snapshot = workflow.task_feature_snapshot({'event_threshold': .65, 'features': ALL_ON})

    assert snapshot['features'] == TOP10_OFF, '任务里落盘的必须是生效值，不是模板级原值'
    assert snapshot['features_source'] == workflow.FEATURES_SNAPSHOT
    assert snapshot['event_threshold'] == .65, '其余口径键原样带过去'

    store = _store_with_task(tmp_path, snapshot)
    state = store.get_task('t')
    assert template_feature_switches(state, store) == TEMPLATE_TOP10_OFF, 'core 模板开关面仍是四项处理开关'
    assert workflow.effective_features(store, state) == TOP10_OFF


def test_task_snapshot_is_immutable_after_package_config_changes(tmp_path, monkeypatch):
    """快照不可变：落盘之后改客户包配置，已建任务的口径不动。"""
    _package(monkeypatch)
    snapshot = workflow.task_feature_snapshot({'features': ALL_ON})
    store = _store_with_task(tmp_path, snapshot)
    assert workflow.effective_features(store, store.get_task('t'))['top10'] is True

    _package(monkeypatch, top10=False)
    assert workflow.effective_features(store, store.get_task('t'))['top10'] is True


def test_old_task_without_snapshot_still_ands_package(tmp_path, monkeypatch):
    """老任务（没有快照标记）保持原语义：模板级 AND 客户包级现算。"""
    _package(monkeypatch, top10=False)
    store = _store_with_task(tmp_path, {'features': ALL_ON})
    assert workflow.effective_features(store, store.get_task('t'))['top10'] is False
    # core 读到的仍是模板级原值——这正是 `freeze_facts` 要记 `feature_mismatch` 的那种局面。
    assert template_feature_switches(store.get_task('t'), store)['top10'] is True


def _confirmed_template(store):
    from fixture_factories import switch_template
    candidate = switch_template(store.root)
    return store.put_artifact('t', 'template_version', candidate)


def test_export_prunes_by_effective_features_and_stays_byte_identical_when_all_on(tmp_path):
    """② 渲染前按生效开关剪枝；全开幂等（与不传 features 逐字节相同）。"""
    store = Store(tmp_path / 'store')
    ref = _confirmed_template(store)
    draft = {'structured_template_ref': ref, 'fact_ref': 'facts-x',
             'evidence_refs': [], 'slot_values': {}, 'chart_refs': {}}

    raw = export_docx(dict(draft), {}, None, 'draft', [], local_store=store)
    pruned = export_docx(dict(draft), {}, None, 'draft', [], local_store=store, features=TOP10_OFF)
    all_on = export_docx(dict(draft), {}, None, 'draft', [], local_store=store, features=ALL_ON)

    assert _docx_text(raw).count('TOP10') == 1
    assert _docx_text(pruned).count('TOP10') == 0, '关掉的段落在渲染前必须剪掉'
    assert all_on == raw, '全开时输出必须与不传 features 逐字节相同'


def _freeze_fixture(tmp_path):
    store = Store(tmp_path / 'store')
    records = [{'id': 'r1', 'title': '甲地发生一起值得关注的事件', 'summary': '摘要',
                'sentiment': '负面', 'warning': '是'}]
    refs = {'calculate_metrics': store.put_artifact('t', 'metrics', {'record_count': 1})}
    for key in ('filter_records:negative', 'filter_records:warning',
                'filter_records:negative_or_warning'):
        refs[key] = store.put_artifact('t', 'records', {'records': records})
    refs['confirmed_event_groups'] = store.put_artifact(
        't', 'confirmed_event_groups', {'groups': [{'id': 'g1', 'member_ids': ['r1'],
                                                    'representative_id': 'r1'}]})
    refs['confirmed_theme_groups'] = store.put_artifact(
        't', 'confirmed_theme_groups',
        {'groups': [{'member_ids': ['r1'], 'candidate_theme': '其他'}]})
    brief = {'id': 'g1', 'fingerprint': 'fp', 'summary': '来源记录反映有关问题，具体情况以原文为准。',
             'source_refs': ['r1']}
    store.put_task(TaskState(id='t', kind='report', phase='awaiting_review',
                             template_ref='template_version-x', result_refs=refs,
                             metadata={'template_rules': {'features': ALL_ON,
                                                         'first_warning_scope': 'negative_or_warning'},
                                       'reviewed_top10': [brief]},
                             review_items=[]))
    return store


def test_top10_mismatch_is_recorded_and_not_silently_dropped(tmp_path, monkeypatch):
    """③ reviewed_top10=1 与 facts.top10=0 不一致 → 一条 feature_mismatch，数值不强行对齐。"""
    _package(monkeypatch, top10=False)
    store = _freeze_fixture(tmp_path)

    frozen = workflow.freeze_facts(workflow.Dependencies(store, None), 't')
    facts = store.get_artifact(frozen.fact_ref)
    assert facts['top10'] == []
    assert len(store.get_task('t').metadata['reviewed_top10']) == 1, '不强行对齐审核结果'

    events = [{key: value for key, value in event.items() if key not in ('seq', 'at')}
              for event in store.events('t')]
    assert {'type': 'feature_mismatch', 'key': 'top10', 'reviewed': 1, 'facts': 0} in events
