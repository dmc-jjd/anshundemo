"""关掉模板开关（事件去重 / 自动分类）后的数据审核可确认路径（QA2 B1/B2 回归）。

三个不变量：
1. `Store.get_artifact(None/'')` 抛带语义的 ValueError，不再 `KeyError(None)`；
2. 关了去重（因此没有 group_events）的任务，`review-data` 返回**有效结构**而不是 legacy；
3. 这种任务能确认（写出空组 confirmed_* 产物）并冻结事实，不被 500 卡死在审核页。
"""
from __future__ import annotations

import pytest

from app.review_service import review_data
from app.schemas import HumanDecision, TaskState
from app.storage import Store
from app.workflow import Dependencies, _data_review_details, freeze_facts

ALL_OFF = {'dedup': False, 'classification': False, 'first_warning': False, 'top10': False}
ALL_ON = {'dedup': True, 'classification': True, 'first_warning': True, 'top10': True}


def _records(*ids):
    return [{'id': i, 'title': '测试记录 ' + i, 'summary': '摘要', 'source': '测试来源',
             'published': '2026-10-01', 'url': ''} for i in ids]


def _store_with_review(tmp_path, features):
    store = Store(tmp_path / 'data')
    metrics = store.put_artifact('t1', 'metrics', {'record_count': 3, 'sentiment': {'负面': 2}, 'platform': {'网站': 3}})
    negative = store.put_artifact('t1', 'records', {'records': _records('a')})
    warning = store.put_artifact('t1', 'records', {'records': _records('a')})
    union = store.put_artifact('t1', 'records', {'records': _records('a', 'b', 'c')})
    state = TaskState(id='t1', kind='report', phase='awaiting_review', input_refs=['file'], revision=1,
                      metadata={'report_month': '2026-10', 'event_threshold': .65,
                                'template_rules': {'features': features, 'features_source': 'task_snapshot'}},
                      result_refs={'import_records': negative, 'calculate_metrics': metrics,
                                   'filter_records:negative': negative, 'filter_records:warning': warning,
                                   'filter_records:negative_or_warning': union})
    state.review_items = [{'id': 'item-1', 'kind': 'data_review', 'question': '请确认本期数据',
                           'blocking': True, 'details': _data_review_details(state), 'status': 'open',
                           'allowed_actions': ['confirm', 'modify', 'defer']}]
    store.put_task(state)
    return store, state


def test_get_artifact_without_ref_is_readable_value_error(tmp_path):
    store = Store(tmp_path / 'data')
    for ref in (None, ''):
        with pytest.raises(ValueError) as info:
            store.get_artifact(ref)
        assert 'artifact_ref_missing' in str(info.value)


def test_review_data_without_events_is_not_legacy(tmp_path):
    store, _state = _store_with_review(tmp_path, ALL_OFF)
    view = review_data(store, 't1')
    assert view['legacy'] is False
    assert view['event_groups'] == [] and view['themes'] == [] and view['top10'] == []
    assert view['analysis_pending'] is False
    assert view['method']['disabled'] is True and view['method']['threshold'] == .65
    assert len(view['records']) == 3
    assert view['review_item']['id'] == 'item-1'


def test_old_task_without_groups_still_reads_as_legacy(tmp_path):
    store, _state = _store_with_review(tmp_path, {})
    assert review_data(store, 't1')['legacy'] is True


def test_switch_off_task_can_confirm_and_freeze(tmp_path):
    store, _state = _store_with_review(tmp_path, ALL_OFF)
    decided = store.apply_decision('t1', HumanDecision(item_id='item-1', expected_revision=1, action='confirm',
        payload={'groups': [], 'themes': [], 'merge_decisions': {}, 'briefs': {}},
        reason='关闭去重/分类后确认统计与来源记录'))
    assert store.get_artifact(decided.result_refs['confirmed_event_groups'])['groups'] == []
    assert store.get_artifact(decided.result_refs['confirmed_theme_groups'])['groups'] == []
    frozen = freeze_facts(Dependencies(store), 't1')
    assert frozen.phase == 'facts_frozen'
    facts = store.get_artifact(frozen.fact_ref)
    assert facts['confirmed_event_count'] == 0
    assert facts['metrics']['automatic_event_count'] == 0
    assert 'first_section_warning_event_count' not in facts['metrics']


def test_events_present_still_requires_groups(tmp_path):
    store, _state = _store_with_review(tmp_path, {**ALL_ON, 'top10': False})
    events = store.put_artifact('t1', 'event_analysis', {
        'groups': [{'id': 'g1', 'representative_id': 'a', 'member_ids': ['a', 'b', 'c']}],
        'all_record_ids': ['a', 'b', 'c'],
        'theme_groups': [{'candidate_theme': '综合舆情', 'member_ids': ['a', 'b', 'c']}]})
    clusters = store.put_artifact('t1', 'cluster_event_themes', {
        'groups': [{'candidate_theme': '综合舆情', 'member_ids': ['a', 'b', 'c']}],
        'all_record_ids': ['a', 'b', 'c']})
    state = store.get_task('t1')
    state.result_refs.update({'event_analysis': events, 'cluster_event_themes': clusters})
    state.review_items[0]['details'] = _data_review_details(state)
    store.put_task(state, state.revision)
    with pytest.raises(ValueError) as info:
        store.apply_decision('t1', HumanDecision(item_id='item-1', expected_revision=state.revision,
            action='confirm', payload={'groups': [], 'themes': []}, reason='空分组必须被拒'))
    assert 'review_groups_required' in str(info.value)