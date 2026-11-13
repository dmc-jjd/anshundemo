"""第二轮「组级聚合向量」合并的验收（V1）。

第一轮只与单条原文代表比，同一真实事件的不同措辞过不了阈值；第二轮改成「组内全部
成员 token 的并集」再对组集合重算 IDF。这里钉住四件事：能合该合的、不合并该分的、
不链式漂移、开关回退逐字节等价。
"""

import json

import app.event_grouping as shell
import core.tools.dedup as dedup
from app.storage import Store
from app.tool import group_events
from app.tool_executor import RunContext
from core.tools import vocabulary

CORE = '苹果 香蕉 葡萄 西瓜'
BRIDGE = '苹果 香蕉 葡萄 西瓜 汽车 火车 飞机 轮船'
OTHER = '汽车 火车 飞机 轮船'


def record(rid, title, summary=''):
    return {'id': rid, 'title': title, 'summary': summary}


def group(gid, member_ids, title='t'):
    return {'id': gid, 'title': title, 'representative_id': member_ids[0], 'member_ids': list(member_ids)}


def round1(records, threshold=0.65):
    return dedup.group_by_representative(records, threshold)


def test_similar_group_aggregates_merge_and_record_pair_provenance():
    records = [record('a1', '贵州法院魔术办案空气证据造假'), record('b1', '贵州法院编造空气证据魔术办案')]
    groups = [group('event-1', ['a1']), group('event-2', ['b1'])]
    merged, method = dedup.merge_group_round(groups, records, threshold=0.4)

    assert len(merged) == 1
    assert merged[0]['id'] == 'event-1'
    assert merged[0]['member_ids'] == ['a1', 'b1']
    assert merged[0]['member_count'] == 2
    assert merged[0]['merged_from'] == ['event-1', 'event-2']
    assert list(merged[0]['merge_scores']) == ['event-2']
    assert merged[0]['merge_scores']['event-2'] >= 0.4
    assert method['merge_type'] == 'group-aggregate TF-IDF cosine against immutable anchor'
    assert method['merge_rounds'] == 2 and method['merge_threshold'] == 0.4


def test_unrelated_groups_stay_apart_without_merge_fields():
    records = [record('a1', '贵州法院魔术办案空气证据造假'), record('b1', '学校食堂食品安全检查发现过期食材')]
    groups = [group('event-1', ['a1']), group('event-2', ['b1'])]
    merged, _ = dedup.merge_group_round(groups, records, threshold=0.4)

    assert [g['id'] for g in merged] == ['event-1', 'event-2']
    for item in merged:
        assert 'merged_from' not in item and 'merge_scores' not in item
        assert item['member_count'] == 1


def test_anchor_is_immutable_so_merge_never_chains():
    """A≈B、B≈C、但 A≉C：B 并进 A 之后，锚仍是 A，C 不得因 B 的传递被吸进来。"""
    records = [record('a1', CORE), record('b1', BRIDGE), record('c1', OTHER)]
    groups = [group('event-1', ['a1']), group('event-2', ['b1']), group('event-3', ['c1'])]
    merged, _ = dedup.merge_group_round(groups, records, threshold=0.5)

    assert [g['id'] for g in merged] == ['event-1', 'event-3']
    assert merged[0]['member_ids'] == ['a1', 'b1'] and merged[0]['merged_from'] == ['event-1', 'event-2']
    assert merged[1]['member_ids'] == ['c1'] and 'merged_from' not in merged[1]


def test_merge_rounds_one_is_a_byte_identical_fallback(tmp_path, monkeypatch):
    rows = [{'id': str(i), 'title': title, 'summary': summary} for i, (title, summary) in enumerate([
        ('贵州法院魔术办案空气证据造假', '同一事件的转载一'),
        ('贵州法院魔术办案空气证据造假', '同一事件的转载二'),
        ('贵州法院编造空气证据魔术办案', '同一事件换了措辞'),
        ('学校食堂食品安全检查', '另一件事'),
    ])]
    store = Store(tmp_path / 'data')
    ctx = RunContext(store, 's2m')
    ref = store.put_artifact('s2m', 'records', {'records': rows})

    monkeypatch.setattr(vocabulary, 'dedup_merge_rounds', lambda: 1)
    off = store.get_artifact(group_events({'records_ref': ref}, ctx).data_ref)
    assert json.dumps(off['groups'], ensure_ascii=False, sort_keys=True) == json.dumps(
        round1(rows)['groups'], ensure_ascii=False, sort_keys=True)
    assert 'merge_rounds' not in off['method'] and 'merge_type' not in off['method']

    monkeypatch.setattr(vocabulary, 'dedup_merge_rounds', lambda: 2)
    monkeypatch.setattr(vocabulary, 'dedup_merge_threshold', lambda: 0.4)
    on = store.get_artifact(group_events({'records_ref': ref}, ctx).data_ref)
    assert on['method']['merge_rounds'] == 2 and on['method']['merge_threshold'] == 0.4
    assert on['method']['merge_type'] == 'group-aggregate TF-IDF cosine against immutable anchor'


def test_same_input_twice_is_byte_identical():
    records = [record('a1', '贵州法院魔术办案空气证据造假'), record('b1', '贵州法院编造空气证据魔术办案'),
               record('c1', '学校食堂食品安全检查'), record('d1', '贵州法院魔术办案空气证据集体造假')]
    groups = [group('event-1', ['a1']), group('event-2', ['b1']), group('event-3', ['c1']), group('event-4', ['d1'])]
    first = dedup.merge_group_round(groups, records, threshold=0.4)
    second = dedup.merge_group_round(groups, records, threshold=0.4)
    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(second, ensure_ascii=False, sort_keys=True)


def test_members_are_conserved_and_never_duplicated():
    here = [record('a1', CORE), record('a2', CORE), record('b1', BRIDGE), record('b2', BRIDGE),
            record('c1', OTHER), record('z1', '学校食堂食品安全检查发现过期食材')]
    groups = [group('event-1', ['a1', 'a2']), group('event-2', ['b1', 'b2']),
              group('event-3', ['c1']), group('event-4', ['z1'])]
    merged, _ = dedup.merge_group_round(groups, here, threshold=0.5)

    flattened = [rid for g in merged for rid in g['member_ids']]
    assert len(flattened) == len(set(flattened)) == 6
    assert set(flattened) == {r['id'] for r in here}
    assert sum(g['member_count'] for g in merged) == 6
    assert all(g['member_count'] == len(g['member_ids']) for g in merged)


def test_every_recorded_merge_score_reaches_the_threshold():
    records = [record(f'r{i}', title) for i, title in enumerate([
        '贵州法院魔术办案空气证据造假', '贵州法院编造空气证据魔术办案',
        '贵州法院帮助编造空气证据实施魔术办案', '贵州法院魔术办案空气证据集体造假',
        '学校食堂食品安全检查发现过期食材', '本地桥面施工恢复通行',
    ])]
    groups = [group(f'event-{i + 1}', [f'r{i}']) for i in range(6)]
    for threshold in (0.35, 0.5, 0.65):
        merged, _ = dedup.merge_group_round(groups, records, threshold=threshold)
        for item in merged:
            for gid, score in (item.get('merge_scores') or {}).items():
                assert score >= threshold, (threshold, gid, score)
                assert gid in item['merged_from'] and gid != item['id']


def test_empty_and_single_group_inputs_do_not_raise():
    merged, method = dedup.merge_group_round([], [], threshold=0.5)
    assert merged == []
    assert method['merge_rounds'] == 2 and method['merge_threshold'] == 0.5 and method['merge_comparisons'] == 0
    merged, _ = dedup.merge_group_round([group('event-1', ['a1'])], [record('a1', CORE)], threshold=0.5)
    assert merged == [{'id': 'event-1', 'title': 't', 'representative_id': 'a1', 'member_ids': ['a1'], 'member_count': 1}]


def test_missing_contract_keys_default_to_a_single_round(monkeypatch):
    monkeypatch.setattr(vocabulary, '_contract', lambda: {})
    assert vocabulary.dedup_merge_rounds() == 1
    assert vocabulary.dedup_merge_threshold() == 0.5


def test_shell_exports_the_same_merger_object():
    assert shell.group_by_representative is dedup.group_by_representative
