from __future__ import annotations
import asyncio,time,uuid,multiprocessing
from dataclasses import dataclass
from .schemas import ToolCall,ToolResult
from .tool import get_tool_handler,get_tool_specs
from .config import MAX_TOOL_CALLS

@dataclass
class RunContext:
    store: object
    task_id: str
    phase: str = 'processing'
    timeout: float = 60
    model_adapter: object = None

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
    if call.tool_name in ('search_historical_web','fetch_historical_page') and (context.phase!='writing' or not state.fact_ref):
        return ToolResult(status='error',error_code='historical_web_requires_frozen_writing_stage')
    if call.tool_name=='propose_vector_event_neighbors' and not call.arguments.get('keyword_candidates_ref'):
        return ToolResult(status='error',error_code='missing_keyword_candidates')
    schema=specs[call.tool_name].arguments_schema
    if any(key not in call.arguments for key in schema.get('required',[])): return ToolResult(status='error',error_code='missing_required_argument')
    for key,value in call.arguments.items():
        if key.endswith('_ref') and isinstance(value,str) and value not in state.result_refs.values() and not context.store.artifact_belongs_to_task(value,context.task_id):
            return ToolResult(status='error',error_code='unauthorized_input_ref')
    if call.tool_name in ('import_records','parse_report_document'):
        allowed={state.metadata.get('input_path'),*state.metadata.get('paths',[])}
        if allowed-{None} and call.arguments.get('path') not in allowed: return ToolResult(status='error',error_code='path_not_in_task_inputs')
    if call.tool_name=='filter_records' and call.arguments.get('scope') not in ('positive','neutral','negative','warning','negative_warning','negative_or_warning','media'):
        return ToolResult(status='error',error_code='unapproved_filter_scope')
    writer_readonly=call.tool_name in ('frozen_statistics','query_frozen_materials','plot_frozen_chart','search_historical_web','fetch_historical_page') and context.phase=='writing'
    if writer_readonly:
        if state.metadata.get('writer_tool_calls',0)>=80:return ToolResult(status='error',error_code='writer_tool_limit')
    elif state.tool_calls>=MAX_TOOL_CALLS: return ToolResult(status='error',error_code='hard_limit')
    if state.fact_ref and specs[call.tool_name].mutates_facts: return ToolResult(status='error',error_code='frozen_facts')
    signature=call.idempotency_key or f'{specs[call.tool_name].version}:{call.tool_name}:{call.arguments}:{call.input_refs}'
    if writer_readonly:signature+=f':{state.fact_ref}:{state.metadata.get("report_parameters_ref","")}'
    prior=state.metadata.get('tool_results',{}).get(signature)
    if prior:
        cached=ToolResult.model_validate(prior)
        if cached.data_ref:
            key=('filter_records:'+str(call.arguments.get('scope','negative')) if call.tool_name=='filter_records' else
                 'render_chart:'+str(call.arguments.get('chart_type')) if call.tool_name=='render_chart' else call.tool_name)
            state.result_refs[key]=cached.data_ref
            context.store.put_task(state,state.revision)
        return cached
    state.tool_calls+=1
    if writer_readonly:state.metadata['writer_tool_calls']=state.metadata.get('writer_tool_calls',0)+1
    context.store.put_task(state,state.revision)
    context.store.append_event(context.task_id,{'type':'tool_start','tool':call.tool_name,'reason':call.reason,'arguments':call.arguments,'call_id':call.call_id})
    try:
        timeout=120 if call.tool_name=='propose_vector_event_neighbors' else context.timeout
        result=await asyncio.to_thread(_bounded_run,call.tool_name,call.arguments,context.store.root,context.task_id,timeout)
    except Exception as e: result=ToolResult(status='error',error_code=type(e).__name__,warnings=[str(e)])
    result.elapsed_ms=int((time.monotonic()-start)*1000)
    state=context.store.get_task(context.task_id)
    state.metadata.setdefault('tool_results',{})[signature]=result.model_dump()
    if result.data_ref:
        if call.tool_name=='filter_records':
            scoped='filter_records:'+str(call.arguments.get('scope','negative'))
            state.result_refs[scoped]=result.data_ref
            if call.arguments.get('scope','negative')=='negative': state.result_refs['filter_records']=result.data_ref
        elif call.tool_name=='render_chart': state.result_refs['render_chart:'+str(call.arguments.get('chart_type'))]=result.data_ref
        else: state.result_refs[call.tool_name]=result.data_ref
    context.store.put_task(state,state.revision)
    context.store.append_event(context.task_id,{'type':'tool_result','tool':call.tool_name,**result.model_dump()})
    return result

