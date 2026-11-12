from __future__ import annotations
import asyncio,time,uuid,multiprocessing
from dataclasses import dataclass
from .schemas import ToolCall,ToolResult
from .tool import get_tool_handler,get_tool_specs
from .config import PACKAGE_DIR
from core.manifest import load_manifest
from core.ports import (REJECT_BUDGET_EXCEEDED,REJECT_FROZEN_FACTS,REJECT_PHASE_NOT_ALLOWED,
                        REJECT_TOOL_NOT_ALLOWED,ToolPolicy)
from core.tools import hints

@dataclass
class RunContext:
    store: object
    task_id: str
    phase: str = 'processing'
    timeout: float = 60
    model_adapter: object = None
    policy: ToolPolicy | None = None

_POLICY=None
def _default_policy():
    """客户包的策略；若 manifest 声明了 `capabilities.require`，就把 allow 收窄成可达工具集。

    这是「去重/分类/研判不必每份报告都跑」的落点：客户包不声明 `events` 产物，
    那组工具就不进白名单，模型调它会被 `tool_not_allowed` 拒掉——流程由数据决定，
    不由执行器里的 if 决定。未声明 require 时行为与剪枝前完全一致。
    """
    global _POLICY
    if _POLICY is None:
        manifest=load_manifest(PACKAGE_DIR)
        policy=manifest.policy
        required=manifest.required_capabilities
        if required:
            from core.tools.registry import resolve_tools
            narrowed=resolve_tools(required)
            policy=ToolPolicy(allow=frozenset(set(policy.allow)&narrowed) if policy.allow else narrowed,
                              phases=policy.phases,budgets=policy.budgets)
        _POLICY=policy
    return _POLICY

def _ref_key(name,arguments):
    spec=hints.REF_KEY.get(name)
    return spec[1]+str(arguments.get(spec[0])) if spec else name

def _reject(context,call,reason):
    context.store.append_event(context.task_id,{'type':'tool_policy_rejected','tool':call.tool_name,'phase':context.phase,'reason':reason})
    return ToolResult(status='error',error_code=reason)

def _run_in_process(name,arguments,root,task_id,conn):
    from .storage import Store
    try:
        ctx=RunContext(Store(root),task_id)
        result=get_tool_handler(name)(arguments,ctx)
        conn.send(('ok',result.model_dump()))
    except Exception as e:
        conn.send(('error',{'error_code':type(e).__name__,'message':str(e)}))
    finally: conn.close()

def _bounded_run(name,arguments,root,task_id,timeout):
    parent,child=multiprocessing.Pipe(duplex=False)
    proc=multiprocessing.get_context('spawn').Process(target=_run_in_process,args=(name,arguments,root,task_id,child))
    proc.start(); child.close()
    ready=parent.poll(timeout)
    if not ready:
        proc.terminate(); proc.join(5)
        if proc.is_alive(): proc.kill(); proc.join()
        parent.close()
        return ToolResult(status='error',error_code='timeout',warnings=['worker terminated after timeout'])
    if ready:
        status,value=parent.recv(); parent.close()
        proc.join(5)
        return ToolResult.model_validate(value) if status=='ok' else ToolResult(status='error',error_code=value['error_code'],warnings=[value['message']])
    parent.close(); return ToolResult(status='error',error_code='worker_exit',warnings=[f'worker exit code {proc.exitcode}'])

async def execute_tool(call:ToolCall,context:RunContext)->ToolResult:
    start=time.monotonic(); state=context.store.get_task(context.task_id)
    specs={x.name:x for x in get_tool_specs()}
    if call.tool_name not in specs: return ToolResult(status='error',error_code='unknown_tool')
    policy=context.policy or _default_policy()
    if call.tool_name not in set(policy.allow)|set(policy.phases.get(context.phase,frozenset())):
        declared=set(policy.allow)|{x for tools in policy.phases.values() for x in tools}
        return _reject(context,call,REJECT_PHASE_NOT_ALLOWED if call.tool_name in declared else REJECT_TOOL_NOT_ALLOWED)
    schema=specs[call.tool_name].arguments_schema
    if any(key not in call.arguments for key in schema.get('required',[])):
        return ToolResult(status='error',error_code=hints.REQUIRED_ERROR_CODE.get(call.tool_name,'missing_required_argument'))
    for key,value in call.arguments.items():
        if key.endswith('_ref') and isinstance(value,str) and value not in state.result_refs.values() and not context.store.artifact_belongs_to_task(value,context.task_id):
            return ToolResult(status='error',error_code='unauthorized_input_ref')
    if 'path' in call.arguments:
        allowed={state.metadata.get('input_path'),*state.metadata.get('paths',[])}
        if allowed-{None} and call.arguments.get('path') not in allowed: return ToolResult(status='error',error_code='path_not_in_task_inputs')
    for tool,scopes in hints.SCOPE_ENUM.items():
        if call.tool_name==tool and call.arguments.get('scope') not in scopes:
            return ToolResult(status='error',error_code=hints.SCOPE_ERROR_CODE.get(tool,'unapproved_filter_scope'))
    writer_readonly=call.tool_name in policy.phases.get(context.phase,())
    budget=policy.budget(context.phase)
    if writer_readonly:
        if state.metadata.get('writer_tool_calls',0)>=budget:return _reject(context,call,REJECT_BUDGET_EXCEEDED)
    elif state.tool_calls>=budget: return _reject(context,call,REJECT_BUDGET_EXCEEDED)
    guard=hints.REQUIRES_FROZEN_FACTS.get(call.tool_name)
    if guard and not state.fact_ref: return ToolResult(status='error',error_code=guard)
    if state.fact_ref and specs[call.tool_name].mutates_facts: return ToolResult(status='error',error_code=REJECT_FROZEN_FACTS)
    signature=call.idempotency_key or f'{specs[call.tool_name].version}:{call.tool_name}:{call.arguments}:{call.input_refs}'
    if writer_readonly:signature+=f':{state.fact_ref}:{state.metadata.get("report_parameters_ref","")}'
    prior=state.metadata.get('tool_results',{}).get(signature)
    if prior:
        cached=ToolResult.model_validate(prior)
        if cached.data_ref:
            state.result_refs[_ref_key(call.tool_name,call.arguments)]=cached.data_ref
            context.store.put_task(state,state.revision)
        return cached
    state.tool_calls+=1
    if writer_readonly:state.metadata['writer_tool_calls']=state.metadata.get('writer_tool_calls',0)+1
    context.store.put_task(state,state.revision)
    context.store.append_event(context.task_id,{'type':'tool_start','tool':call.tool_name,'reason':call.reason,'arguments':call.arguments,'call_id':call.call_id})
    try:
        timeout=hints.TIMEOUT_S.get(call.tool_name,context.timeout)
        result=await asyncio.to_thread(_bounded_run,call.tool_name,call.arguments,context.store.root,context.task_id,timeout)
    except Exception as e: result=ToolResult(status='error',error_code=type(e).__name__,warnings=[str(e)])
    result.elapsed_ms=int((time.monotonic()-start)*1000)
    state=context.store.get_task(context.task_id)
    state.metadata.setdefault('tool_results',{})[signature]=result.model_dump()
    if result.data_ref:
        if call.tool_name in hints.REF_KEY: state.result_refs[_ref_key(call.tool_name,call.arguments)]=result.data_ref
        else: state.result_refs[call.tool_name]=result.data_ref
        alias=hints.REF_ALIAS.get(call.tool_name)
        if alias and str(call.arguments.get(alias[0],alias[1]))==alias[1]: state.result_refs[alias[2]]=result.data_ref
    context.store.put_task(state,state.revision)
    context.store.append_event(context.task_id,{'type':'tool_result','tool':call.tool_name,**result.model_dump()})
    return result

