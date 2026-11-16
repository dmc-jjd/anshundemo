"""全量单次研判：整份模板一次调用、截断即报错、不落半成品候选。

三块分批取消后有三条硬契约：
1. 每个基准块都在**同一次**模型调用里（不再有“第 N/M 批”）；
2. 响应被截断（finish_reason=length / JSON 不完整）→ 抛 template_response_truncated，
   不进入 repair 轮，也不写 structured_template_candidate；
3. 进度事件是“已覆盖块数 / 总块数”，completed 不会超过 total。
"""
from __future__ import annotations

import asyncio
import io
import json

import pytest

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


def test_one_call_sends_every_block_with_the_full_packet(tmp_path):
    store, _ = template_task(tmp_path)
    calls = []

    async def analyst(role, payload):
        calls.append(payload)
        return await semantic_analyst(role, payload)

    state = asyncio.run(run_template(Dependencies(store, analyst), 't'))
    assert state.phase == 'awaiting_template_confirmation', state.metadata.get('template_error')

    # 整份模板只有 1 次模型调用，且 target_blocks 是全部基准块。
    assert len(calls) == 1
    payload = calls[0]
    assert payload['target_blocks'] == [0, 1, 2, 3]
    assert [b['index'] for b in payload['source_reports'][0]['blocks']] == [0, 1, 2, 3]
    # 完整上下文：三份报告全文、本地比对、本地假设、可用绑定都在同一次请求里。
    assert len(payload['source_reports']) == 3
    assert payload['local_comparison']['alignments'] and payload['available_bindings']
    assert payload['local_hypothesis']['blocks']
    assert '一次性返回整份模板的全部块' in payload['instruction']
    assert '本次一次性输出全部 target_blocks' in payload['task_scope']['instruction']

    # 每次全部通过：只有一个 batch 键，没有按批台账；进度事件覆盖 0→全部，不越界。
    assert set(state.metadata['template_batches']) == {'all'}
    events = store.events('t')
    assert len([e for e in events if e['type'] == 'model_call']) == 1
    progress = [e for e in events if e['type'] == 'template_model_progress']
    assert [p['stage'] for p in progress] == ['started', 'finished']
    assert all(p['completed'] <= p['total'] == 4 for p in progress)
    assert progress[-1]['completed'] == 4 and progress[-1]['mode'] == 'single_shot'
    assert [e for e in events if e['type'] == 'template_round_started'][0]['batch'] == 'all'


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
    assert len(calls) == 1 and calls[0]['target_blocks'] == [0, 1, 2, 3]
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
    cut = '{"summary":"半份模板","blocks":[{"index":0,"kind":"paragraph","purpose":"甲","parts":[{"text":"舆'

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

    assert len(requests) == 1                        # 截断不重试、也不进入 repair 轮
    assert state.phase == 'template_review_failed'
    error = state.metadata['template_error']
    assert error['type'] == 'TemplateResponseTruncated'
    assert 'template_response_truncated' in error['message']
    assert 'finish_reason=length' in error['message']
    assert '整份重试' in error['message'] and '不能续跑' in error['message']

    events = store.events('t')
    assert any(e['type'] == 'template_response_truncated' and e['finish_reason'] == 'length'
               for e in events)
    assert not any(e['type'] == 'structured_template_candidate' for e in events)
    assert 'structured_template_ref' not in state.metadata
    assert 'template_validation_ref' not in state.metadata
    assert not list(store.files.glob('structured_template_candidate-*.json'))
    # 截断的响应既不成为 checkpoint，也不冒充“可审阅的半成品”。
    assert state.metadata['template_review_checkpoints'] == {}
    assert next(iter(state.metadata['template_batches'].values()))['status'] == 'truncated'
