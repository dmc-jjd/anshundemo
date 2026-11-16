"""模板级 TOP10 开关在 core 的两个终点：研判阶段不产梗概、数据审核不校验梗概。

前一版只做到「报告层整段不生成」：`analyse_events` 仍在空算 TOP10 去重与梗概，
`storage.apply_decision` 仍要求每条排名事件都有 15—35 字梗概。这里把这两处钉住：

* 关掉时**不调模型**（`event_judge:events` / `event_summarizer` 一次都没有），产物里
  `top10` 为空表，checkpoint 不再建 `top10_consolidations`；
* 关掉时数据审核确认**不再因「没有梗概」报错**，`reviewed_top10` 落空表；
* 开着时行为与改造前一致（梗概照出、少了梗概仍报 `top10_summary_required`）。
"""
from __future__ import annotations

import asyncio

import pytest

from app.event_analysis import analyse_events
from app.schemas import HumanDecision, TaskState
from app.storage import Store
from app.workflow import Dependencies

ALL_ON = {'dedup': True, 'classification': True, 'first_warning': True, 'top10': True}
TOP10_OFF = {**ALL_ON, 'top10': False}


def row(identifier, title, warning='是', sentiment='负面'):
    return {'id': identifier, 'title': title, 'summary': title, 'warning': warning,
            'sentiment': sentiment, 'category': '', 'source_ref': {}}


def setup(tmp_path, records, features):
    store = Store(tmp_path)
    source = store.put_artifact('t', 'records', {'records': records})
    groups = [{'id': f'g{index}', 'title': item['title'], 'representative_id': item['id'],
               'member_ids': [item['id']]} for index, item in enumerate(records)]
    local = store.put_artifact('t', 'events', {
        'groups': groups, 'all_record_ids': [item['id'] for item in records],
        'source_records_ref': source,
        'borderline_candidates': [{'id': 'pair', 'source_group': 'g1', 'target_group': 'g0', 'score': .5}]})
    metadata = {'template_rules': {'event_threshold': .65, 'features': features}} if features else {}
    store.put_task(TaskState(id='t', kind='report', phase='analyzing',
                             result_refs={'group_events': local}, metadata=metadata))
    return store


def adapter(calls):
    async def model(role, payload):
        calls.append((role, 'events' if 'events' in payload else 'pairs' if 'pairs' in payload else ''))
        if role == 'event_judge' and 'events' in payload:
            return {'groups': [{'group_ids': [item['id']]} for item in payload['events']],
                    'uncertain_pairs': []}
        if role == 'event_judge':
            return {'items': [{'id': item['id'], 'decision': 'different', 'reason': 'test'}
                              for item in payload['pairs']]}
        if role == 'event_classifier':
            return {'items': [{'id': item['id'], 'category': '其他', 'status': 'classified',
                               'reason': 'test'} for item in payload['events']]}
        if role == 'event_summarizer':
            return {'items': [{'id': item['id'], 'status': 'complete',
                               'summary': '来源记录反映有关问题，具体情况以原文为准。',
                               'source_refs': [item['evidence'][0]['ref']]}
                              for item in payload['events']]}
        raise ValueError('unexpected_role:' + role)
    return model


def records():
    return [row('a', '甲地发生一起值得关注的事件'), row('b', '乙地发生另一起值得关注的事件')]


def analyse(tmp_path, features, calls):
    store = setup(tmp_path, records(), features)
    result = asyncio.run(analyse_events(Dependencies(store, adapter(calls)), 't'))
    return store, result


def freeze_and_confirm(store, result, briefs):
    state = store.get_task('t')
    ref = state.result_refs['event_analysis']
    cluster = store.put_artifact('t', 'theme_groups', {'groups': result['theme_groups']})
    local = store.get_artifact(state.result_refs['group_events'])
    state.result_refs['filter_records:negative_or_warning'] = local['source_records_ref']
    state.phase = 'awaiting_review'
    state.review_items = [{'id': 'review', 'kind': 'data_review', 'status': 'open', 'blocking': True,
                           'details': {'event_ref': ref, 'cluster_ref': cluster, 'analysis_ref': ref}}]
    store.put_task(state, state.revision)
    payload = {'groups': result['groups'],
               'themes': [{'candidate_theme': '其他', 'member_ids': [item['id'] for item in records()]}],
               'merge_decisions': {case['id']: 'different' for case in result['merge_ambiguities']},
               'briefs': briefs}
    return store.apply_decision('t', HumanDecision(item_id='review', expected_revision=state.revision,
                                                  action='confirm', payload=payload, reason='test'))


def test_top10_off_skips_top10_model_calls_and_briefs(tmp_path):
    calls = []
    store, result = analyse(tmp_path, TOP10_OFF, calls)
    assert result['top10'] == []
    assert not result['pending_model'] and not result['failures']
    assert not [item for item in calls if item[0] == 'event_summarizer']
    assert not [item for item in calls if item == ('event_judge', 'events')]
    assert result['counts']['human_summary_cases'] == 0
    state = store.get_task('t')
    checkpoint = store.get_artifact(state.result_refs['event_analysis_checkpoint'])
    assert 'top10_consolidations' not in checkpoint
    # 去重/分类阶段照旧跑：关的只是 TOP10，不是整条研判链
    assert [item for item in calls if item[0] == 'event_classifier']


def test_top10_off_confirm_data_skips_summary_validation(tmp_path):
    calls = []
    store, result = analyse(tmp_path, TOP10_OFF, calls)
    accepted = freeze_and_confirm(store, result,
                                  {'stale-fingerprint': {'status': 'complete', 'summary': '', 'source_refs': []}})
    assert accepted.metadata['reviewed_top10'] == []
    assert accepted.review_items[0]['status'] == 'resolved'


def test_top10_on_produces_briefs_and_still_validates_them(tmp_path):
    calls = []
    store, result = analyse(tmp_path, ALL_ON, calls)
    assert len(result['top10']) == 2 and all(item['status'] == 'complete' for item in result['top10'])
    assert [item for item in calls if item[0] == 'event_summarizer']
    assert ('event_judge', 'events') in calls
    bad = {result['top10'][0]['fingerprint']: {'status': 'complete', 'summary': '', 'source_refs': []}}
    with pytest.raises(ValueError, match='top10_summary_required'):
        freeze_and_confirm(store, result, bad)
