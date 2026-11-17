"""三轮模板语义研判行为测试（2026-11 用户拍板规则）。

覆盖验收：
- r1 后不停止（另见 test_template_single_shot.py）；
- r2 完美早停（结构 0、重要 0、建议<3）→ final_round=2，human_review_items 在场；
- r2 不完美（重要项 / 建议≥3 / 第一轮意见回执未全处理）→ 必跑 r3；
- r3 模板覆盖候选、意见全部 advisory、确认接口不强制逐条处理；
- r3 仍报重要项 → template_round_quality_incident 事件；
- severity 非法值降级「建议」，不 500；
- 已确认模板预览不再有「LLM审核」/ mountAdvice。
"""
from __future__ import annotations

import asyncio
import copy
from pathlib import Path

from fastapi.testclient import TestClient

from app.schemas import TaskState
from app.storage import Store
from app.workflow import Dependencies, run_template
from test_structured_template import semantic_analyst
from test_template_single_shot import four_block_reports

REPO = Path(__file__).resolve().parents[1]
RULES = {'event_threshold': .65, 'first_warning_scope': 'warning',
         'ranking': 'negative_warning_member_count', 'features':
         {'dedup': True, 'classification': True, 'first_warning': True, 'top10': True}}


def template_task(tmp_path, name='t'):
    docs = four_block_reports(tmp_path)
    store = Store(tmp_path / 'store')
    store.put_task(TaskState(id=name, kind='template', phase='queued',
                             metadata={'paths': [d['path'] for d in docs]}))
    return store


def item(severity, message, checklist='数字/占比/日期类字段格式与原文是否一致'):
    return {'severity': severity, 'checklist': checklist,
            'field_id': '', 'message': message, 'evidence': '报告0首段。'}


def scripted(scripts):
    """按调用次序返回脚本化响应；每个 spec 可带 items / receipts / marker / bad_severity。"""
    calls = []

    async def analyst(role, payload):
        spec = scripts[min(len(calls), len(scripts) - 1)]
        calls.append(payload)
        result = await semantic_analyst(role, payload)
        round_no = payload['semantic_round']['round']
        result['review_items'] = copy.deepcopy(spec.get('items', []))
        if round_no == 2:
            if 'receipts' in spec:
                result['prior_opinion_resolved'] = spec['receipts']
            else:
                prior = payload['semantic_round']['prior_round']['review_items']
                result['prior_opinion_resolved'] = [
                    {'opinion_index': i, 'resolved': True, 'note': '已处理'}
                    for i in range(len(prior))]
        if spec.get('marker'):
            result['summary'] = spec['marker']
        return result

    return analyst, calls


def candidate(store, state):
    return store.get_artifact(state.metadata['structured_template_ref'])


def confirm_rules(state):
    return {'expected_revision': state.revision,
            'candidate_ref': state.metadata['structured_template_ref'],
            'reason': '已查看终审参考意见并确认', 'rules': RULES}


def test_r2_perfect_with_two_suggestions_stops_and_carries_advisory_items(tmp_path):
    """验收 2：r2 结构无误+重要0+建议2 → 不发起 r3；最终候选=当前模板，human_review_items 在场。"""
    store = template_task(tmp_path)
    analyst, calls = scripted([
        {'items': []},
        {'items': [item('建议', '可优化一'), item('建议', '可优化二')]}])
    state = asyncio.run(run_template(Dependencies(store, analyst), 't'))
    assert state.phase == 'awaiting_template_confirmation', state.metadata.get('template_error')
    assert [c['semantic_round']['round'] for c in calls] == [1, 2]
    batch = next(iter(state.metadata['template_batches'].values()))
    assert batch['final_round'] == 2
    cand = candidate(store, state)
    assert cand['semantic_final_round'] == 2
    assert [i['message'] for i in cand['human_review_items']] == ['可优化一', '可优化二']
    events = store.events('t')
    assert not any(e['type'] == 'template_round_quality_incident' for e in events)
    passed = [e for e in events if e['type'] == 'template_round_passed']
    assert passed[-1]['perfect'] is True and passed[-1]['suggestions'] == 2


def test_three_suggestions_force_round_three(tmp_path):
    """验收 4：r2 结构无误+重要0+建议 3 条 → 进 r3；建议 2 条停（上一条已覆盖）。"""
    store = template_task(tmp_path)
    analyst, calls = scripted([
        {'items': []},
        {'items': [item('建议', f'建议{i}') for i in range(3)]},
        {'items': [], 'marker': 'V3-终审'}])
    state = asyncio.run(run_template(Dependencies(store, analyst), 't'))
    assert state.phase == 'awaiting_template_confirmation', state.metadata.get('template_error')
    assert [c['semantic_round']['round'] for c in calls] == [1, 2, 3]
    batch = next(iter(state.metadata['template_batches'].values()))
    assert batch['final_round'] == 3
    assert candidate(store, state)['review_summary'] == 'V3-终审'
    # r3 输入必须带前两轮模板与意见。
    r3 = calls[2]['semantic_round']
    assert r3['prior_round']['template']['blocks'] and len(r3['history']) == 2
    r2_event = [e for e in store.events('t') if e['type'] == 'template_round_passed' and e['round'] == 2][0]
    assert r2_event['perfect'] is False


def test_r2_important_triggers_r3_which_overwrites_candidate(tmp_path):
    """验收 3：r2 有 1 条重要 → r3；r3 模板覆盖候选。"""
    store = template_task(tmp_path)
    analyst, calls = scripted([
        {'items': []},
        {'items': [item('重要', 'r2 重要问题')], 'marker': 'V2'},
        {'items': [item('建议', '终审小建议')], 'marker': 'V3'}])
    state = asyncio.run(run_template(Dependencies(store, analyst), 't'))
    assert state.phase == 'awaiting_template_confirmation', state.metadata.get('template_error')
    assert [c['semantic_round']['round'] for c in calls] == [1, 2, 3]
    cand = candidate(store, state)
    assert cand['review_summary'] == 'V3'
    # 候选只保留最后一轮（r3）意见。
    assert [i['message'] for i in cand['human_review_items']] == ['终审小建议']


def test_unresolved_first_round_receipts_force_round_three(tmp_path):
    """验收 5：r2 prior_opinion_resolved 全 false（声称没改）→ 即使结构过也不完美 → r3。"""
    store = template_task(tmp_path)
    r1_items = [item('重要', 'r1 提的问题')]
    analyst, calls = scripted([
        {'items': r1_items},
        {'items': [], 'receipts': [{'opinion_index': 0, 'resolved': False, 'note': '漏改'}]},
        {'items': []}])
    state = asyncio.run(run_template(Dependencies(store, analyst), 't'))
    assert state.phase == 'awaiting_template_confirmation', state.metadata.get('template_error')
    assert [c['semantic_round']['round'] for c in calls] == [1, 2, 3]
    r2 = calls[1]
    # r2 输入里逐条带上了第一轮意见。
    assert [i['message'] for i in r2['semantic_round']['prior_round']['review_items']] == ['r1 提的问题']
    r2_entry = next(iter(state.metadata['template_batches'].values()))['rounds']
    judge = next(e for e in r2_entry if e['number'] == 2 and e.get('verdict'))
    assert judge['verdict']['perfect'] is False and judge['verdict']['prior_unresolved'] is True
    # 回执缺失同样不允许完美（重放一次：r2 干脆不返回该字段）。
    root_b = tmp_path / 'b'; root_b.mkdir()
    store2 = template_task(root_b, name='t2')
    analyst2, calls2 = scripted([
        {'items': r1_items},
        {'items': [], 'receipts': None},
        {'items': []}])
    state2 = asyncio.run(run_template(Dependencies(store2, analyst2), 't2'))
    assert [c['semantic_round']['round'] for c in calls2] == [1, 2, 3]


def test_r3_important_items_raise_quality_incident_but_confirmation_still_200(tmp_path, monkeypatch):
    """验收 6+7：r3 报 4 条重要 → 质量事故事件；但意见全 advisory，确认接口 200 不强制处理。"""
    import app.main as main
    store = template_task(tmp_path)
    analyst, _ = scripted([
        {'items': []},
        {'items': [item('重要', 'r2 重要问题')]},
        {'items': [item('重要', f'终审重要问题{i}') for i in range(4)]}])
    state = asyncio.run(run_template(Dependencies(store, analyst), 't'))
    assert state.phase == 'awaiting_template_confirmation'
    incidents = [e for e in store.events('t') if e['type'] == 'template_round_quality_incident']
    assert len(incidents) == 1 and incidents[0]['round'] == 3 and incidents[0]['important'] == 4
    cand = candidate(store, state)
    assert len(cand['human_review_items']) == 4
    monkeypatch.setattr(main, 'store', store)
    with TestClient(main.app) as client:
        response = client.post('/api/templates/t/confirm', json=confirm_rules(state))
    assert response.status_code == 200, response.text
    confirmed = store.get_task('t')
    assert confirmed.phase == 'template_confirmed' and confirmed.metadata['confirmed_template_ref']


def test_illegal_severity_is_downgraded_to_suggestion_without_500(tmp_path):
    """schema 扩展容错：severity 非法值按「建议」处理并记录归一化事件。"""
    store = template_task(tmp_path)
    weird = {'severity': '紧急', 'checklist': '', 'field_id': '',
             'message': '自创级别', 'evidence': '报告0首段。'}
    analyst, calls = scripted([{'items': []}, {'items': [weird]}])
    state = asyncio.run(run_template(Dependencies(store, analyst), 't'))
    assert state.phase == 'awaiting_template_confirmation', state.metadata.get('template_error')
    assert [c['semantic_round']['round'] for c in calls] == [1, 2]  # 1 条降级建议 <3 → 完美早停
    normalized = [e for e in store.events('t') if e['type'] == 'template_round_item_normalized']
    assert normalized and normalized[0]['count'] == 1
    assert candidate(store, state)['human_review_items'][0]['severity'] == '建议'


def test_confirmed_template_preview_has_no_llm_advice_button():
    """验收 9：前端不再有 mountAdvice / LLM审核；终审意见面板用 human_review_items。"""
    js = (REPO / 'app' / 'static' / 'template-draft.js').read_text(encoding='utf-8')
    assert 'mountAdvice' not in js and 'runAdvice' not in js
    assert 'LLM审核' not in js and '/advice' not in js
    assert 'human_review_items' in js and 'mountHumanReview' in js
    assert '这些是模型的参考意见，可忽略' in js
    assert 'locateHumanReviewField' in js and 'td-advice-locate' in js
