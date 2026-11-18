import asyncio
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

import core.tool_executor as executor
from core.ports import ToolPolicy
from core.schemas import TaskState, ToolCall, ToolResult
from core.storage import Store


def context(tmp_path):
    store = Store(tmp_path)
    store.put_task(TaskState(id='r', kind='report', phase='queued', package='anshun_monthly'))
    policy = ToolPolicy(allow=frozenset({'calculate_metrics'}), budgets={'default': 3})
    return executor.RunContext(store, 'r', policy=policy)


def call(arguments):
    return ToolCall(call_id='check', tool_name='calculate_metrics', arguments=arguments)


def test_error_retries_then_success_cache_restores_reference_and_budget(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    ref = ctx.store.put_artifact('r', 'records', {'records': []})
    runs = []
    def worker(*args):
        runs.append(args)
        # Simulate an error after a content-addressed side effect: retry must not multiply files.
        output = ctx.store.put_artifact('r', 'metrics', {'record_count': 0})
        return ToolResult(status='error', error_code='transient') if len(runs) == 1 else ToolResult(status='ok', data_ref=output)
    monkeypatch.setattr(executor, '_bounded_run', worker)
    request = call({'records_ref': ref})
    first = asyncio.run(executor.execute_tool(request, ctx))
    second = asyncio.run(executor.execute_tool(request, ctx))
    assert first.error_code == 'transient' and second.status == 'ok'
    state = ctx.store.get_task('r')
    state.result_refs.clear()
    ctx.store.put_task(state, state.revision)
    third = asyncio.run(executor.execute_tool(request, ctx))
    assert third.data_ref == second.data_ref and len(runs) == 2
    state = ctx.store.get_task('r')
    assert state.tool_calls == 2 and state.result_refs['calculate_metrics'] == second.data_ref
    events = ctx.store.events('r')
    assert [e['status'] for e in events if e['type'] == 'tool_result'] == ['error', 'ok']
    assert len(list(ctx.store.files.glob('metrics-*.json'))) == 1
    state.tool_calls = 3
    ctx.store.put_task(state, state.revision)
    assert asyncio.run(executor.execute_tool(request, ctx)).error_code == 'tool_budget_exceeded'
    assert len(runs) == 2


@pytest.mark.parametrize('denominator,status,ratio', [('absent', 'ok', 'absent'), (None, 'ok', 'absent'), (0, 'needs_review', None), (2, 'ok', 0.5)])
def test_metrics_schema_and_execution_agree(tmp_path, monkeypatch, denominator, status, ratio):
    from core.tools.metrics import calculate_metrics
    ctx = context(tmp_path)
    ref = ctx.store.put_artifact('r', 'records', {'records': [{'sentiment': '负面', 'platform': '网站'}]})
    args = {'records_ref': ref}
    if denominator != 'absent':
        args['denominator'] = denominator
    schema = next(s.arguments_schema for s in executor._tool_specs() if s.name == 'calculate_metrics')
    Draft202012Validator(schema).validate(args)
    runs = []
    def worker(name, arguments, *unused):
        runs.append(arguments)
        return calculate_metrics(arguments, ctx)
    monkeypatch.setattr(executor, '_bounded_run', worker)
    assert asyncio.run(executor.execute_tool(call({}), ctx)).error_code == 'missing_required_argument'
    other = ctx.store.put_artifact('other', 'records', {'records': [], 'distinct': True})
    assert asyncio.run(executor.execute_tool(call({'records_ref': other}), ctx)).error_code == 'unauthorized_input_ref'
    result = asyncio.run(executor.execute_tool(call(args), ctx))
    assert result.status == status and len(runs) == 1
    payload = ctx.store.get_artifact(result.data_ref)
    if ratio == 'absent':
        assert 'ratio' not in payload
    else:
        assert payload['ratio'] == ratio
    state = ctx.store.get_task('r')
    state.fact_ref = 'frozen'
    ctx.store.put_task(state, state.revision)
    assert asyncio.run(executor.execute_tool(call(args), ctx)).error_code == 'frozen_facts'


@pytest.mark.parametrize('mode,code', [('eof', 'worker_exit'), ('timeout', 'timeout'), ('lingering', None), ('start_error', 'OSError')])
def test_worker_always_closes_pipes_and_reaps_process(tmp_path, monkeypatch, mode, code):
    class Pipe:
        closed = False
        def close(self): self.closed = True
        def poll(self, timeout): return mode != 'timeout'
        def recv(self):
            if mode == 'eof': raise EOFError
            return 'ok', ToolResult(status='ok').model_dump()
    class Process:
        exitcode = 2
        alive = mode in ('timeout', 'lingering')
        terminated = False
        closed = False
        def start(self):
            if mode == 'start_error': raise OSError('cannot start')
        def join(self, *args): pass
        def is_alive(self): return self.alive
        def terminate(self): self.terminated = True; self.alive = False
        def kill(self): self.alive = False
        def close(self): self.closed = True
    parent, child, proc = Pipe(), Pipe(), Process()
    monkeypatch.setattr(executor.multiprocessing, 'Pipe', lambda **kw: (parent, child))
    monkeypatch.setattr(executor.multiprocessing, 'get_context', lambda *args: SimpleNamespace(Process=lambda **kw: proc))
    if mode == 'start_error':
        with pytest.raises(OSError, match='cannot start'):
            executor._bounded_run('fake', {}, tmp_path, 'r', .01)
    else:
        result = executor._bounded_run('fake', {}, tmp_path, 'r', .01)
        assert result.error_code == code
    assert parent.closed and child.closed and proc.closed
    assert not proc.alive



