"""第二轮归并重编号 → `borderline_candidates` 组号失效的回归（P0）。

缺陷：`group_by_representative` 产出的候选对引用的是**第一轮**组号；`merge_group_round`
会把组吞并/重编号，之后 `core/event_analysis.py` 按旧组号 `root()` 取组即 KeyError，
真实数据（28789 行，576 条候选里 358 条失效）必然卡在 `analyzing`。

这里钉住六件事：`id_map` 内容正确、`group_by_representative` 行为未变、重映射后无未知
组号、两端并成一组时候选被丢弃、`pair.id` 连续无洞、研判入口遇到未知组号只跳过不崩。
"""

import asyncio
import json
import logging

import pytest

import app.event_grouping as shell
from app.schemas import TaskState
from app.storage import Store
from app.workflow import Dependencies
from app.event_analysis import analyse_events
from core.tools import dedup, vocabulary
from core.tools.events import group_events
from core.tool_executor import RunContext

# 夜市烧烤两只：第一轮相似度落在 [0.39, 0.65) 记候选，第二轮 0.5 阈值下并进 event-1。
# 学生食堂两只：同样是候选，但第二轮聚合相似度不过 0.5，保留。
FIXTURE = [
    ('a1', '夜市烧烤油烟扰民投诉'),
    ('b1', '烧烤摊油烟扰民投诉不断'),
    ('c1', '学生食堂过期食材'),
    ('d1', '学校食堂发现过期食材'),
    ('e1', '城市公园绿化养护'),
]


def record(rid, title, summary=''):
    return {'id': rid, 'title': title, 'summary': summary}


def rows():
    return [record(rid, title) for rid, title in FIXTURE]


def round1():
    return dedup.group_by_representative(rows(), 0.65)


def test_id_map_is_returned_only_when_asked_and_maps_first_round_ids_to_anchors():
    result = round1()
    behind = dedup.merge_group_round(result['groups'], rows(), threshold=0.5)
    assert len(behind) == 2, '默认两元组：既有调用方的解包不能被打断'

    merged, method, id_map = dedup.merge_group_round(result['groups'], rows(), threshold=0.5, with_id_map=True)
    assert [item['id'] for item in merged] == ['event-1', 'event-3', 'event-4', 'event-5']
    assert id_map == {'event-1': 'event-1', 'event-2': 'event-1', 'event-3': 'event-3',
                      'event-4': 'event-4', 'event-5': 'event-5'}
    assert set(id_map) == {group['id'] for group in result['groups']}, '第一轮每个组都要有映射'
    assert set(id_map.values()) <= {item['id'] for item in merged}
    assert method['merge_rounds'] == 2 and method['merge_threshold'] == 0.5


def test_group_by_representative_itself_is_unchanged():
    result = round1()
    assert set(result) == {'groups', 'member_scores', 'all_record_ids', 'borderline_candidates', 'method'}
    assert [group['id'] for group in result['groups']] == ['event-1', 'event-2', 'event-3', 'event-4', 'event-5']
    assert [group['member_ids'] for group in result['groups']] == [['a1'], ['b1'], ['c1'], ['d1'], ['e1']]
    assert [group['representative_id'] for group in result['groups']] == ['a1', 'b1', 'c1', 'd1', 'e1']
    assert [(pair['id'], pair['source_group'], pair['target_group']) for pair in result['borderline_candidates']] == [
        ('pair-1', 'event-2', 'event-1'), ('pair-2', 'event-4', 'event-3')]
    assert all(0.39 <= pair['score'] < 0.65 for pair in result['borderline_candidates'])


def test_remap_rewrites_group_ids_and_keeps_the_pair():
    id_map = {'event-9': 'event-3'}
    remapped = dedup.remap_borderline_candidates(
        [{'id': 'pair-1', 'source_group': 'event-9', 'target_group': 'event-5', 'score': 0.5}], id_map)
    assert remapped == [{'id': 'pair-1', 'source_group': 'event-3', 'target_group': 'event-5', 'score': 0.5}]


def test_candidate_whose_two_ends_merge_into_one_group_is_dropped():
    result = round1()
    _, _, id_map = dedup.merge_group_round(result['groups'], rows(), threshold=0.5, with_id_map=True)
    remapped = dedup.remap_borderline_candidates(result['borderline_candidates'], id_map)
    assert len(result['borderline_candidates']) == 2
    assert len(remapped) == 1 and remapped[0]['id'] == 'pair-1'
    assert (remapped[0]['source_group'], remapped[0]['target_group']) == ('event-4', 'event-3')
    assert remapped[0]['score'] == pytest.approx(result['borderline_candidates'][1]['score'])


def test_pair_ids_stay_contiguous_after_remap():
    result = round1()
    _, _, id_map = dedup.merge_group_round(result['groups'], rows(), threshold=0.5, with_id_map=True)
    remapped = dedup.remap_borderline_candidates(result['borderline_candidates'], id_map)
    assert [pair['id'] for pair in remapped] == [f'pair-{index}' for index in range(1, len(remapped) + 1)]
    assert len(remapped) < len(result['borderline_candidates']), '有空洞才需要重编号'


def test_group_events_artifact_never_references_a_missing_group(tmp_path, monkeypatch):
    store = Store(tmp_path / 'data')
    ctx = RunContext(store, 'remap')
    ref = store.put_artifact('remap', 'records', {'records': rows()})
    monkeypatch.setattr(vocabulary, 'dedup_merge_rounds', lambda: 2)
    monkeypatch.setattr(vocabulary, 'dedup_merge_threshold', lambda: 0.5)
    artifact = store.get_artifact(group_events({'records_ref': ref, 'threshold': 0.65}, ctx).data_ref)

    group_ids = {group['id'] for group in artifact['groups']}
    referenced = {pair['source_group'] for pair in artifact['borderline_candidates']} | {
        pair['target_group'] for pair in artifact['borderline_candidates']}
    assert referenced - group_ids == set(), '重映射后不许再出现未知组号'
    assert len(artifact['borderline_candidates']) == 1
    assert artifact['borderline_candidates'][0]['source_group'] in group_ids
    assert artifact['method']['merge_rounds'] == 2


def test_group_events_with_a_single_round_leaves_candidates_untouched(tmp_path, monkeypatch):
    store = Store(tmp_path / 'data')
    ctx = RunContext(store, 'remap1')
    ref = store.put_artifact('remap1', 'records', {'records': rows()})
    monkeypatch.setattr(vocabulary, 'dedup_merge_rounds', lambda: 1)
    artifact = store.get_artifact(group_events({'records_ref': ref, 'threshold': 0.65}, ctx).data_ref)
    assert json.dumps(artifact['borderline_candidates'], ensure_ascii=False, sort_keys=True) == json.dumps(
        round1()['borderline_candidates'], ensure_ascii=False, sort_keys=True)
    assert 'merge_rounds' not in artifact['method']


def test_analysis_skips_unknown_group_reference_instead_of_raising(tmp_path, caplog):
    records = [{'id': 'a', 'title': '未知内容甲', 'summary': '未知内容甲', 'warning': '是', 'sentiment': '负面',
                'category': '', 'source_ref': {}},
               {'id': 'b', 'title': '未知内容乙', 'summary': '未知内容乙', 'warning': '是', 'sentiment': '负面',
                'category': '', 'source_ref': {}}]
    store = Store(tmp_path)
    source = store.put_artifact('t', 'records', {'records': records})
    groups = [{'id': 'g0', 'title': '未知内容甲', 'representative_id': 'a', 'member_ids': ['a']},
              {'id': 'g1', 'title': '未知内容乙', 'representative_id': 'b', 'member_ids': ['b']}]
    local = store.put_artifact('t', 'events', {
        'groups': groups, 'all_record_ids': ['a', 'b'], 'source_records_ref': source,
        'borderline_candidates': [{'id': 'pair', 'source_group': 'ghost', 'target_group': 'g0', 'score': .5},
                                  {'id': 'pair-2', 'source_group': 'g1', 'target_group': 'g0', 'score': .5}]})
    store.put_task(TaskState(id='t', kind='report', phase='analyzing', result_refs={'group_events': local}))

    async def model(role, payload):
        if role == 'event_judge' and 'events' in payload:
            return {'groups': [{'group_ids': [p['id']]} for p in payload['events']], 'uncertain_pairs': []}
        if role == 'event_judge':
            return {'items': [{'id': p['id'], 'decision': 'different', 'reason': '不同事件'} for p in payload['pairs']]}
        if role == 'event_classifier':
            return {'items': [{'id': p['id'], 'status': 'classified', 'category': '其他', 'reason': '内容完整'}
                              for p in payload['events']]}
        return {'items': [{'id': p['id'], 'status': 'complete', 'summary': '来源反映两件不同事件的具体情况。',
                           'source_refs': [p['evidence'][0]['ref']]} for p in payload['events']]}

    with caplog.at_level(logging.WARNING, logger='core.event_analysis'):
        result = asyncio.run(analyse_events(Dependencies(store, model), 't'))

    assert result['failures'] == []
    assert not result['pending_model']
    assert any('ghost' in message for message in caplog.messages), '未知组号必须留一条 warning'
    assert len(result['groups']) == 2, '未知组号只跳过那一对，其余组照常研判'


def test_shell_exports_the_patched_merger():
    assert shell.group_by_representative is dedup.group_by_representative
