"""三轮模板语义研判的第一轮/硬失败契约（2026-11 行为改造后）。

轮次语义（用户拍板）：r1 必跑不判完美；r2 必跑做判定（结构 0、重要 0、建议<3、
第一轮意见全量回执处理）；r3 仅在 r2 不完美时终审。模型调用最少 2 次、最多 3 次。

本文件钉死三条硬契约：
1. 每个基准块都在**同一次**模型调用里（不再有“第 N/M 批”），且 r1 之后绝不停止——必发 r2；
2. 响应被截断（finish_reason=length / JSON 不完整）→ 抛 template_response_truncated，
   不进入同语义轮的后续重试，也不写 structured_template_candidate；
3. 进度事件轮次口径是「第 N/3 轮」，旧的三块分批台账不被拼成新候选。
"""
from __future__ import annotations

import asyncio
import io
import json

from app.schemas import TaskState
from app.storage import Store
from app.workflow import Dependencies, run_template
from test_structured_template import docx, semantic_analyst


def four_block_reports(tmp_path):
    return [docx(tmp_path / f'{i}.docx',
                  f'报告{i}首段。</w:t></w:r></w:p><w:p><w:r><w:t>二段。</w:t></w:r></w:p>'
                  f'<w:p><w:r><w:t>三段。</w:t></w:r></w:p><w:p><w:r><w:t>四段。') for i in range(3)]


def template_task(tmp_path, name='t'):
    docs = four_block_reports(tmp_path)
    store = Store(tmp_path / 'store')
    store.put_task(TaskState(id=name, kind='template', phase='queued',
                             metadata={'paths': [d['path'] for d in docs]}))
    return store, docs


def test_r1_never_short_circuits_r2_runs_with_full_packet(tmp_path):
    """验收 1：桩模拟 r1「完美」（结构无误、零意见），仍必须发起 r2。"""
    store, _ = template_task(tmp_path)
    calls = []

    async def analyst(role, payload):
        calls.append(payload)
        return await semantic_analyst(role, payload)

    state = asyncio.run(run_template(Dependencies(store, analyst), 't'))
    assert state.phase == 'awaiting_template_confirmation', state.metadata.get('template_error')

    # 三轮研判最少 2 次模型调用：r1 不做完美判定，r2 判定完美后收尾，绝不发起 r3。
    assert len(calls) == 2
    assert [c['semantic_round']['round'] for c in calls] == [1, 2]
    r1, r2 = calls
    assert r1['target_blocks'] == [0, 1, 2, 3]
    assert [b['index'] for b in r1['source_reports'][0]['blocks']] == [0, 1, 2, 3]
    # 完整上下文：三份报告全文、本地比对、本地假设、可用绑定都在同一次请求里。
    assert len(r1['source_reports']) == 3
    assert r1['local_comparison']['alignments'] and r1['available_bindings']
    assert r1['local_hypothesis']['blocks']
    # r2 必带 r1 的模板稿与第一轮意见。
    assert r2['semantic_round']['prior_round']['template']['blocks']
    assert r2['semantic_round']['prior_round']['review_items'] == []

    # 只有一个 batch 键；事件流：两轮 started、两轮 passed（r2 完美终态）。
    assert set(state.metadata['template_batches']) == {'all'}
    batch = next(iter(state.metadata['template_batches'].values()))
    assert batch['engine'] == 'three_round_v1' and batch['terminal'] == 'candidate_ready'
    assert batch['final_round'] == 2
    events = store.events('t')
    assert [e['round'] for e in events if e['type'] == 'template_round_started'] == [1, 2]
    passed = [e for e in events if e['type'] == 'template_round_passed']
    assert [(e['round'], e.get('perfect')) for e in passed] == [(1, None), (2, True)]
    assert not any(e['type'] == 'template_round_quality_incident' for e in events)
    progress = [e for e in events if e['type'] == 'template_model_progress']
    assert progress[0]['completed'] == 0 and progress[0]['total'] == 4
    assert all(p['completed'] <= p['total'] for p in progress)
    assert progress[-1]['stage'] == 'finished' and progress[-1]['mode'] == 'three_round'
    assert progress[-1]['completed'] == 4
    assert [e for e in events if e['type'] == 'template_round_started'][0]['batch'] == 'all'
    # 第二轮完美即早停：没有第三轮输入工件。
    assert not any(c['semantic_round']['round'] == 3 for c in calls)
    # 终审意见随候选工件落盘（第二轮完美时即第二轮意见，此处为空数组）。
    candidate = store.get_artifact(state.metadata['structured_template_ref'])
    assert candidate['human_review_items'] == [] and candidate['semantic_final_round'] == 2


def test_legacy_batch_bookkeeping_is_not_reassembled_into_a_candidate(tmp_path):
    store, _ = template_task(tmp_path)
    state = store.get_task('t')
    state.metadata['template_batches'] = {'1,2,3': {'targets': [0, 1, 2], 'rounds': [], 'status': 'passed'}}
    state.metadata['template_review_checkpoints'] = {'1,2,3': 'template_model_response-deadbeefdeadbeefdead'}
    store.put_task(state, state.revision)
    calls = []

    async def analyst(role, payload):
        calls.append(payload)
        return await semantic_analyst(role, payload)

    result = asyncio.run(run_template(Dependencies(store, analyst), 't'))
    assert result.phase == 'awaiting_template_confirmation', result.metadata.get('template_error')
    # 旧台账整份重来：r1+r2 两次调用，batch 只剩 all。
    assert len(calls) == 2 and calls[0]['target_blocks'] == [0, 1, 2, 3]
    assert set(result.metadata['template_batches']) == {'all'}


def test_truncated_response_raises_loudly_and_leaves_no_candidate(tmp_path, monkeypatch):
    import core.model_client as m

    class Reply:
        def __init__(self, obj):
            self.obj = obj

        def __enter__(self):
            return io.StringIO(json.dumps(self.obj))

        def __exit__(self, *args):
            pass

    requests = []
    cut = '{"summary":"半份模板","blocks":[{"index":0,"kind":"paragraph","purpose":"甲","parts":[{"field":"x"}]'

    def request(req, timeout=None):
        requests.append(json.loads(req.data))
        return Reply({'choices': [{'message': {'content': cut}, 'finish_reason': 'length'}],
                      'usage': {'prompt_tokens': 10, 'completion_tokens': 5}})

    monkeypatch.setattr(m, 'MODEL_URL', 'https://example.invalid')
    monkeypatch.setattr(m, 'MODEL_NAME', 'test-model')
    monkeypatch.setattr(m, 'MODEL_KEY', 'test-key')
    monkeypatch.setattr(m.urllib.request, 'urlopen', request)

    store, _ = template_task(tmp_path)
    state = asyncio.run(run_template(Dependencies(store), 't'))

    assert len(requests) == 1                        # 截断不重试、也不进入 r2
    assert state.phase == 'template_review_failed'
    error = state.metadata['template_error']
    assert error['type'] == 'TemplateResponseTruncated'
    assert 'template_response_truncated' in error['message']
    assert 'finish_reason=length' in error['message']
    assert '整份重试' in error['message'] and '不能续跑' in error['message']

    events = store.events('t')
    assert any(e['type'] == 'template_response_truncated' and e['finish_reason'] == 'length'
               and e['round'] == 1 for e in events)
    assert not any(e['type'] == 'structured_template_candidate' for e in events)
    assert 'structured_template_ref' not in state.metadata
    assert 'template_validation_ref' not in state.metadata
    assert not list(store.files.glob('structured_template_candidate-*.json'))
    # 截断的响应既不成为 checkpoint，也不冒充“可审阅的半成品”。
    assert state.metadata['template_review_checkpoints'] == {}
    assert next(iter(state.metadata['template_batches'].values()))['status'] == 'truncated'
