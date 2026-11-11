from __future__ import annotations
import asyncio

from app.schemas import TaskState,ToolCall
from app.storage import Store
from app.tool_executor import RunContext,execute_tool
from core.ports import ToolPolicy


def _store(tmp_path):
    store=Store(tmp_path/'data')
    store.put_task(TaskState(id='p',kind='report',phase='processing'))
    return store


def test_tool_not_allowed_is_rejected_and_logged(tmp_path):
    store=_store(tmp_path)
    ctx=RunContext(store,'p',policy=ToolPolicy(allow=frozenset({'calculate_metrics'})))
    result=asyncio.run(execute_tool(ToolCall(call_id='x',tool_name='import_records',arguments={'path':'a.xlsx'}),ctx))
    assert result.error_code=='tool_not_allowed'
    rejected=[e for e in store.events('p') if e['type']=='tool_policy_rejected']
    assert rejected[-1]['tool']=='import_records' and rejected[-1]['phase']=='processing'
    assert rejected[-1]['reason']=='tool_not_allowed'


def test_writer_tool_outside_its_phase_is_rejected(tmp_path):
    store=_store(tmp_path)
    result=asyncio.run(execute_tool(ToolCall(call_id='x',tool_name='plot_frozen_chart'),RunContext(store,'p')))
    assert result.error_code=='tool_phase_not_allowed'
    assert [e['reason'] for e in store.events('p') if e['type']=='tool_policy_rejected']==['tool_phase_not_allowed']


def test_budget_exhaustion_reports_budget_error(tmp_path):
    store=_store(tmp_path)
    ref=store.put_artifact('p','records',{'records':[]})
    ctx=RunContext(store,'p',policy=ToolPolicy(allow=frozenset({'calculate_metrics'}),budgets={'default':0}))
    result=asyncio.run(execute_tool(ToolCall(call_id='x',tool_name='calculate_metrics',arguments={'records_ref':ref}),ctx))
    assert result.error_code=='tool_budget_exceeded'
    assert store.get_task('p').tool_calls==0


def test_frozen_facts_still_blocks_mutating_tools(tmp_path):
    store=_store(tmp_path)
    ref=store.put_artifact('p','records',{'records':[]})
    state=store.get_task('p'); state.fact_ref='facts-1'; store.put_task(state,state.revision)
    result=asyncio.run(execute_tool(ToolCall(call_id='x',tool_name='calculate_metrics',arguments={'records_ref':ref}),RunContext(store,'p')))
    assert result.error_code=='frozen_facts'


def _writing_store(tmp_path):
    store=Store(tmp_path/'data')
    store.put_task(TaskState(id='w',kind='report',phase='writing'))
    return store


def test_web_tool_requires_frozen_facts_in_writing_phase(tmp_path):
    """搬迁前就存在的行为：web 工具必须已有冻结事实才能用。

    阶段白名单只回答"这个阶段允不允许"，回答不了"有没有事实可查"。
    WP-S2-E 按规格删掉原特判后这半条曾丢失（= 行为放宽），此处以声明式提示表保住。
    """
    from core.ports import ToolPolicy

    store=_writing_store(tmp_path)
    policy=ToolPolicy(allow=frozenset(),phases={'writing':frozenset({'search_historical_web'})})
    ctx=RunContext(store,'w',phase='writing',policy=policy)
    result=asyncio.run(execute_tool(ToolCall(call_id='x',tool_name='search_historical_web',
                                             arguments={'query':'q'}),ctx))
    assert result.error_code=='historical_web_requires_frozen_writing_stage'
