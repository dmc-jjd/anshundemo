"""Persisted task transitions and explicit business-tool orchestration."""
from __future__ import annotations
from .agent import get_prompt
import asyncio,hashlib,json,uuid
from dataclasses import dataclass
from core.agent_steps import graph_agents,prune_spec,resolve_enabled_agents
from core.graph.compiler import END_TARGET,compile_graph
from core.graph.review_loop import ReviewBudgets,build_review_loop
from core.ports import GraphNode,GraphSpec,ReviewerSpec
from typing_extensions import TypedDict
from .schemas import TaskState,ToolCall,ToolDecision,DraftVersion,FactSnapshot
from .tool_executor import RunContext,execute_tool
from .model_client import invoke_agent,ModelUnavailable,TaskPaused
from .fallback_policy import build_fallback_plan

class GraphState(TypedDict, total=False):
    task_id: str
    phase: str
    repair_succeeded: bool

@dataclass
class Dependencies:
    store: object
    model_adapter: object = None

def _enabled_agents(agents=None):
    """本次启用的角色集：显式传入优先，否则按客户包 manifest 的 `agents:` 解析。"""
    return resolve_enabled_agents() if agents is None else frozenset(agents)

def _record_agent_scope(store,task_id,graph,agents):
    """把「本次这张图由哪些角色驱动」写进任务事件（审计可见；不产物件、不进指纹）。"""
    store.append_event(task_id,{'type':'agent_scope','graph':graph,'agents':list(graph_agents(graph,agents))})

def _graph_node(deps,name,action,graph_name):
    async def node(value):
        task_id=value['task_id'];store=deps.store
        store.append_event(task_id,{'type':'graph_node','graph':graph_name,'node':name,'status':'started'})
        try:
            import inspect
            result=action(task_id)
            if inspect.isawaitable(result):result=await result
            phase=store.get_task(task_id).phase
            store.append_event(task_id,{'type':'graph_node','graph':graph_name,'node':name,'status':'finished','phase':phase})
            return {'phase':phase,**({'repair_succeeded':result} if isinstance(result,bool) else {})}
        except Exception as exc:
            store.append_event(task_id,{'type':'graph_node','graph':graph_name,'node':name,'status':'error','error_type':type(exc).__name__})
            raise
    return node


def _report_spec():
    return GraphSpec(id='report',entry='validate_input',nodes=(
        GraphNode('validate_input','gate'),GraphNode('data_processing','tool'),
        GraphNode('event_analysis','agent'),GraphNode('await_data_review','gate')))


def build_report_graph(dependencies:Dependencies,agents=None):
    agents=_enabled_agents(agents)
    def validate(task_id):
        if dependencies.store.get_task(task_id).kind!='report':raise ValueError('not_report_task')
    def entry(value):
        task=dependencies.store.get_task(value['task_id'])
        return 'process' if not task.fact_ref and not task.metadata.get('human_review_final') and task.phase in ('queued','processing','awaiting_review','analysis_pending') else 'stop'
    def after_processing(value):
        task=dependencies.store.get_task(value['task_id'])
        return 'analyse' if {'calculate_metrics','group_events','cluster_event_themes'}<=task.result_refs.keys() and not task.cancel_requested else 'finish'
    def after_analysis(value):return 'stop' if dependencies.store.get_task(value['task_id']).phase=='analysis_pending' else 'finish'
    actions={'validate_input':validate,'data_processing':lambda tid:_process_records(dependencies,tid),
             'event_analysis':lambda tid:_analyse_report_events(dependencies,tid),'await_data_review':lambda tid:_await_data_review(dependencies,tid)}
    # 出口即结束只能走 edges 注册表（GraphSpec.next 只认节点 id）；终审只有一个出口，故为常量路由。
    edges={'validate_input':(entry,{'process':'data_processing','stop':END_TARGET}),
           'data_processing':(after_processing,{'analyse':'event_analysis','finish':'await_data_review'}),
           'event_analysis':(after_analysis,{'stop':END_TARGET,'finish':'await_data_review'}),
           'await_data_review':(lambda value:'end',{'end':END_TARGET})}
    spec,edges=prune_spec(_report_spec(),edges,'report',agents)
    return compile_graph(spec,actions=actions,edges=edges,state_schema=GraphState,
                         node_wrapper=lambda name,action:_graph_node(dependencies,name,action,'report')).compile()


def _writing_spec(review_only=False):
    return GraphSpec(id='writing',entry='validate_input',nodes=(
        GraphNode('validate_input','gate',next=('local_validation' if review_only else 'write_draft',)),
        GraphNode('write_draft','agent',next=('local_validation',)),
        GraphNode('local_validation','tool',next=('style_detection',)),
        GraphNode('style_detection','tool',next=('format_review',)),
        GraphNode('format_review','agent'),GraphNode('content_review','agent'),GraphNode('revise_draft','loop'),
        GraphNode('content_local_validation','tool',next=('content_style_detection',)),
        GraphNode('content_style_detection','tool',next=('content_review',)),
        GraphNode('final_format_review','agent',next=('await_final_review',)),
        GraphNode('await_final_review','gate')))


def build_writing_graph(dependencies:Dependencies,review_only=False,agents=None):
    from .reviewers import begin_run,local_review,style_review,run_reviewer,review_route,format_route,revise_draft,finish_review,repairable
    agents=_enabled_agents(agents)
    store=dependencies.store
    def validate(task_id):
        task=store.get_task(task_id)
        if task.kind!='report' or not task.fact_ref:raise ValueError('data_review_required')
        if review_only and not task.draft_ref:raise ValueError('draft_missing')
        begin_run(store,task_id,review_only)
    def phase_node(name,action):
        def run(task_id):
            task=store.get_task(task_id);task.phase=name;store.put_task(task,task.revision)
            return action(task_id)
        return run
    nodes=[('validate_input',validate),('write_draft',phase_node('writing',lambda tid:_write_draft(dependencies,tid))),
        ('local_validation',lambda tid:local_review(store,tid)),('style_detection',phase_node('style_detection',lambda tid:style_review(store,tid))),
        ('format_review',lambda tid:run_reviewer(dependencies,tid,'format_reviewer')),
        ('content_review',lambda tid:run_reviewer(dependencies,tid,'content_reviewer')),
        ('revise_draft',phase_node('revising',lambda tid:revise_draft(dependencies,tid))),
        ('content_local_validation',lambda tid:local_review(store,tid)),('content_style_detection',phase_node('style_detection',lambda tid:style_review(store,tid))),
        ('final_format_review',lambda tid:run_reviewer(dependencies,tid,'format_reviewer',phase='final_format_review')),
        ('await_final_review',lambda tid:finish_review(store,tid))]
    # 审校循环的 12 个出口名由 ReviewerSpec.kind 派生（出口名的唯一来源）；预算显式 5——
    # ReviewerSpec.max_rounds 默认 2 且全仓零消费，接线即改行为。
    plan=build_review_loop(reviewers=(ReviewerSpec('format','format_reviewer'),ReviewerSpec('content','content_reviewer')),
        actions={'review:format_reviewer':'format_review','review:content_reviewer':'content_review',
                 'revalidate:format_reviewer':'local_validation','revalidate:content_reviewer':'content_local_validation',
                 'revision':'revise_draft','final_review':'final_format_review','await_final':'await_final_review'},
        budgets=ReviewBudgets(max_rounds=5))
    # 线性流水线：writer成稿 → 格式审核(循环退修) → 内容审核(循环退修) → 最终格式审核 → 人工研判。
    # 初始成稿后一律先走格式审核；格式审核完毕后才会进入内容审核。
    # 格式审核：仍有可退修意见 → 退修改写；通过/达上限 → 内容审核；取消 → 终审。
    # 内容审核：仍有可退修意见 → 退修改写；通过/达上限 → 最后一次格式审核；取消 → 终审。
    def after_revision(value):
        # 退修成功：格式退修回到格式校验链路，内容退修回到内容校验链路（各自独立，不穿插）。
        if value.get('repair_succeeded'):
            stage=store.get_task(value['task_id']).metadata['writing_review_run'].get('repair_stage','format_reviewer')
            return 'content_revalidate' if stage=='content_reviewer' else 'format_revalidate'
        task=store.get_task(value['task_id'])
        if task.cancel_requested:return 'finish'
        run=task.metadata['writing_review_run'];stage=run.get('repair_stage','content_reviewer')
        if stage=='content_reviewer':
            # 内容退修失败/被拒：轮次内重审内容，否则交给最终格式审核。
            if run.get('stage_rounds',{}).get(stage,0)<5 and repairable(store,task,stage):
                run['retry_reviewer']=stage;store.put_task(task,task.revision);return 'content'
            return 'final_format'
        if not repairable(store,task,stage):
            # Writer 拒绝格式退修或无退修点：保留格式意见，转发到内容审核一次。
            return 'content' if format_route(store,task.id)=='content' else 'finish'
        if run.get('stage_repair_attempts',{}).get(stage,0)<5:return 'retry'
        return 'content' if format_route(store,task.id)=='content' else 'finish'
    # 内容退修后的独立重校验链路 → 回到内容审核；与格式审核的重校验链路完全分离。
    routers={'format_review':lambda value:format_route(store,value['task_id']),
             'content_review':lambda value:review_route(store,value['task_id']),'revise_draft':after_revision}
    edges={origin:(routers[origin],dict(branches)) for origin,branches in plan.conditional_edges}
    edges['await_final_review']=(lambda value:'end',{'end':END_TARGET})
    spec,edges=prune_spec(_writing_spec(review_only),edges,'writing',agents)
    return compile_graph(spec,actions=dict(nodes),edges=edges,state_schema=GraphState,
                         node_wrapper=lambda name,action:_graph_node(dependencies,name,action,'writing')).compile()

async def run_writing_graph(dependencies:Dependencies,task_id:str,review_only=False,agents=None):
    enabled=_enabled_agents(agents)
    _record_agent_scope(dependencies.store,task_id,'writing',enabled)
    graph=build_writing_graph(dependencies,review_only) if agents is None else build_writing_graph(dependencies,review_only,enabled)
    try:await graph.ainvoke({'task_id':task_id},config={'recursion_limit':100})
    except TaskPaused:pass
    return dependencies.store.get_task(task_id)

async def make_preview_with_charts(deps:Dependencies,task_id:str):
    return await run_writing_graph(deps,task_id)


def _template_spec():
    return GraphSpec(id='template',entry='validate_input',nodes=(
        GraphNode('validate_input','gate',next=('local_compare_and_analysis',)),
        GraphNode('local_compare_and_analysis','tool')))


def build_template_graph(dependencies:Dependencies,agents=None):
    agents=_enabled_agents(agents)
    def validate_input(state):
        task=dependencies.store.get_task(state['task_id'])
        if task.kind!='template': raise ValueError('not_template_task')
        return {'phase':'validated'}
    async def compare(state):
        result=await run_template(dependencies,state['task_id'])
        return {'phase':result.phase}
    spec,edges=prune_spec(_template_spec(),{'local_compare_and_analysis':(lambda state:'end',{'end':END_TARGET})},
                          'template',agents)
    return compile_graph(spec,actions={'validate_input':validate_input,'local_compare_and_analysis':compare},
                         edges=edges,state_schema=GraphState).compile()

async def run_report_graph(dependencies:Dependencies,task_id:str,agents=None):
    enabled=_enabled_agents(agents)
    _record_agent_scope(dependencies.store,task_id,'report',enabled)
    graph=build_report_graph(dependencies) if agents is None else build_report_graph(dependencies,enabled)
    try:return await graph.ainvoke({'task_id':task_id})
    except TaskPaused:return dependencies.store.get_task(task_id)

async def run_template_graph(dependencies:Dependencies,task_id:str,agents=None):
    enabled=_enabled_agents(agents)
    _record_agent_scope(dependencies.store,task_id,'template',enabled)
    graph=build_template_graph(dependencies) if agents is None else build_template_graph(dependencies,enabled)
    try:return await graph.ainvoke({'task_id':task_id})
    except TaskPaused:return dependencies.store.get_task(task_id)

def _item(kind,question,blocking=True,details=None):
    actions=['confirm','modify','merge','split','independent','exclude','defer'] if kind=='event_groups' else ['confirm','modify','defer']
    return {'id':uuid.uuid4().hex,'kind':kind,'question':question,'blocking':blocking,'details':details or {},'status':'open','allowed_actions':actions}

def _args_for(name,state):
    r=state.result_refs
    if name=='import_records': return {'path':state.metadata['input_path'],'sheet_index':state.metadata.get('sheet_index',3)}
    if name=='calculate_metrics': return {'records_ref':r['import_records'],'negative_ref':r.get('filter_records')}
    if name=='filter_records': return {'records_ref':r['import_records'],'scope':'negative'}
    if name=='filter_positive_scope': return {'records_ref':r['import_records'],'scope':'positive'}
    if name=='filter_neutral_scope': return {'records_ref':r['import_records'],'scope':'neutral'}
    if name=='filter_warning_scope': return {'records_ref':r['import_records'],'scope':'warning'}
    if name=='filter_union_scope': return {'records_ref':r['import_records'],'scope':'negative_or_warning'}
    if name=='filter_negative_warning_scope': return {'records_ref':r['import_records'],'scope':'negative_warning'}
    if name=='propose_keyword_event_candidates':
        scope=state.metadata.get('event_scope')
        key={'all':'import_records','negative':'filter_records:negative','warning':'filter_records:warning','negative_warning':'filter_records:negative_warning','negative_or_warning':'filter_records:negative_or_warning'}.get(scope)
        if not key: raise KeyError('event scope not confirmed')
        return {'records_ref':r[key],'scope_label':scope}
    if name in ('resolve_locality','classify_records','cluster_event_themes','select_materials'):
        return {'records_ref':r['filter_records:negative_or_warning']}
    if name=='group_events': return {'records_ref':r['filter_records:negative_or_warning'],'threshold':state.metadata.get('event_threshold',.65)}
    if name=='propose_vector_event_neighbors': return {'keyword_candidates_ref':r['propose_keyword_event_candidates']}
    if name=='discover_topics': return {'records_ref':r['filter_records:negative_or_warning'],'cluster_ref':r.get('cluster_event_themes')}
    raise KeyError(name)

async def _process_records(deps:Dependencies,task_id:str):
    task=deps.store.get_task(task_id)
    if task.metadata.get('human_review_final') and task.result_refs.get('event_analysis'):return task
    store=deps.store; state=store.get_task(task_id)
    if state.fact_ref or state.phase not in ('queued','processing','awaiting_review','analysis_pending'): return state
    state.phase='processing'; store.put_task(state,state.revision)
    store.append_event(task_id,{'type':'phase','phase':'processing'})
    ctx=RunContext(store,task_id,model_adapter=deps.model_adapter)
    if state.metadata.get('mode')=='dynamic' and not state.metadata.get('reprocess_events'):
        no_progress=0
        while True:
            state=store.get_task(task_id)
            if state.planning_calls>=12 or no_progress>=3: break
            state.planning_calls+=1; store.put_task(state,state.revision)
            try:
                import json
                from core import paths
                manifest=json.loads((paths.template_dir()/'report.template.json').read_text(encoding='utf-8'))
                slot_goals=[{'id':x['id'],'semantic':x['semantic'],'scope':x['scope'],'statistical_unit':x['statistical_unit'],'calculation':x['calculation'],'source_fields':x['source_fields_or_calculation'],'review_required':x['review_required']} for x in manifest['placeholders']]
                if state.template_ref and state.template_ref!='anshun-monthly-colored':
                    from .structured_template import load_confirmed_template
                    definition=load_confirmed_template(store,state.template_ref)
                    slot_goals=[{'id':f['id'],'semantic':f['semantic'],'owner':f['owner'],'value_schema':f['value_schema'],'binding':f.get('binding')} for f in definition['fields']]
                    manifest={**manifest,'template_id':definition['id']}
                from .tool import get_tool_specs
                decision=await invoke_agent('data_processor',{'template_id':manifest['template_id'],'slot_goals':slot_goals,'confirmed_scope_requirements':manifest['scope_requirements'],'input':{'path':state.metadata.get('input_path'),'sheet_index':state.metadata.get('sheet_index',3)},'template_rules':state.metadata.get('template_rules',{}),'results':state.result_refs,'tools':[x.model_dump() for x in get_tool_specs() if x.name not in ('propose_keyword_event_candidates','propose_vector_event_neighbors')],'instruction':get_prompt('data_processor.next_tool')},ToolDecision,ctx)
            except Exception as e:
                store.append_event(task_id,{'type':'planning_error','error':type(e).__name__}); break
            if decision.action=='finish_processing':
                needed={'import_records','calculate_metrics','filter_records:positive','filter_records:neutral','filter_records:negative','filter_records:warning','filter_records:negative_or_warning','group_events','cluster_event_themes'}
                if needed<=state.result_refs.keys(): break
                no_progress+=1; store.append_event(task_id,{'type':'coverage_rejected','missing':list(needed-state.result_refs.keys())}); continue
            if decision.action=='request_human':
                store.append_event(task_id,{'type':'planner_handoff','reason':decision.reason}); break
            if decision.tool_name not in ('import_records','calculate_metrics','filter_records','resolve_locality','classify_records','cluster_event_themes','discover_topics','select_materials','read_evidence','group_events'):
                no_progress+=1; continue
            before=len(state.result_refs)
            call=ToolCall(call_id=uuid.uuid4().hex,tool_name=decision.tool_name,arguments=decision.arguments,reason=decision.reason)
            await execute_tool(call,ctx)
            no_progress=0 if len(store.get_task(task_id).result_refs)>before else no_progress+1
    state=store.get_task(task_id)
    needed={'import_records','calculate_metrics','filter_records:positive','filter_records:neutral','filter_records:negative','filter_records:warning','filter_records:negative_or_warning','group_events','cluster_event_themes'}
    if not needed<=state.result_refs.keys():
        reason='model_unavailable_or_no_progress' if state.metadata.get('mode')=='dynamic' else 'model_not_configured'
        state.fallback=build_fallback_plan(state,reason)
        if state.metadata.get('event_scope')=='negative_warning' and 'filter_records:negative_warning' not in state.result_refs:
            state.fallback['steps'].insert(state.fallback['steps'].index('group_events'),'filter_negative_warning_scope')
        store.put_task(state,state.revision)
        store.append_event(task_id,{'type':'fallback_started',**state.fallback})
        for name in list(state.fallback['steps']):
            state=store.get_task(task_id)
            if state.cancel_requested: break
            try: args=_args_for(name,state)
            except KeyError as e:
                store.append_event(task_id,{'type':'fallback_step_skipped','tool':name,'reason':f'missing prerequisite {e}'})
                continue
            tool_name='filter_records' if name in ('filter_positive_scope','filter_neutral_scope','filter_warning_scope','filter_negative_warning_scope','filter_union_scope') else name
            result=await execute_tool(ToolCall(call_id=uuid.uuid4().hex,tool_name=tool_name,arguments=args,reason='公开保底步骤 '+name),ctx)
            store.append_event(task_id,{'type':'fallback_step_result','tool':name,'status':result.status,'error_code':result.error_code})
    return store.get_task(task_id)

async def _analyse_report_events(deps:Dependencies,task_id:str):
    store=deps.store
    state=store.get_task(task_id)
    if {'calculate_metrics','group_events','cluster_event_themes'}<=state.result_refs.keys() and not state.cancel_requested:
        from .event_analysis import analyse_events
        state.phase='analyzing';store.put_task(state,state.revision)
        analysis=await analyse_events(deps,task_id)
        state=store.get_task(task_id)
        if analysis['pending_model']:
            state.phase='analysis_pending';store.put_task(state,state.revision)
            store.append_event(task_id,{'type':'phase','phase':'analysis_pending'})
            return state
    return store.get_task(task_id)

def _await_data_review(deps:Dependencies,task_id:str):
    store=deps.store;state=store.get_task(task_id)
    if state.cancel_requested: state.phase='cancelled'
    elif 'import_records' not in state.result_refs: state.phase='failed'
    else:
        obsolete={'model_question','event_groups','first_section_warning_rule','theme_clusters','template_review','ranking_rule','warning_scope'}
        for item in state.review_items:
            if item['kind'] in obsolete and item.get('status')!='resolved':
                item.update(status='superseded',blocking=False,superseded_reason='已采用模板规则、自动事件归并和整体数据审核')
        required={'calculate_metrics','group_events','cluster_event_themes'}
        if not required<=state.result_refs.keys():
            state.phase='failed'
            state.metadata['failure_message']='数据处理未完成，请查看运行动态并重试。'
        elif not any(x['kind']=='data_review' and x['status']=='open' for x in state.review_items):
            state.review_items.append(_item('data_review','请查看本期统计、自动归并事件与分类结果，修改后确认本期数据。',True,{'metrics_ref':state.result_refs['calculate_metrics'],'event_ref':state.result_refs['event_analysis'],'cluster_ref':state.result_refs['cluster_event_themes'],'analysis_ref':state.result_refs['event_analysis']}))
        else:
            for item in state.review_items:
                if item['kind']=='data_review' and item['status']=='open':
                    item['details']={'metrics_ref':state.result_refs['calculate_metrics'],'event_ref':state.result_refs['event_analysis'],
                                     'cluster_ref':state.result_refs['cluster_event_themes'],'analysis_ref':state.result_refs['event_analysis']}
        if state.phase!='failed':state.phase='awaiting_review'
    store.put_task(state,state.revision); store.append_event(task_id,{'type':'phase','phase':state.phase})
    return state

async def run_report(deps:Dependencies,task_id:str):
    await run_report_graph(deps,task_id)
    return deps.store.get_task(task_id)


async def run_template(deps:Dependencies,task_id:str):
    from .structured_template import build_structured_template
    from .template_review import make_input,compile_review,digest,POLICY_VERSION
    from .state import TemplateCandidateState
    from .template_execution import review_batches,ManualTemplateReviewRequired
    store=deps.store;state=store.get_task(task_id)
    if state.metadata.get('confirmed_template_ref') or state.phase=='template_manual_review':return state
    ctx=RunContext(store,task_id,model_adapter=deps.model_adapter)
    def save(phase):
        state.phase=phase;store.put_task(state,state.revision)
        store.append_event(task_id,{'type':'phase','phase':phase})
    state.review_items=[]
    state.metadata.pop('structured_template_ref',None)
    state.metadata.pop('template_validation_ref',None)
    state.metadata.pop('template_error',None)
    try:
        save('template_parsing')
        documents=[];refs=[]
        for path in state.metadata['paths']:
            # Reuse unchanged local parses, while detecting edited source documents.
            cached=state.metadata.get('parsed_report_refs',{}).get(path)
            document=store.get_artifact(cached) if cached else None
            if document is None or document['sha256']!=hashlib.sha256(__import__('pathlib').Path(path).read_bytes()).hexdigest():
                file_hash=hashlib.sha256(__import__('pathlib').Path(path).read_bytes()).hexdigest()
                res=await execute_tool(ToolCall(call_id=uuid.uuid4().hex,tool_name='parse_report_document',arguments={'path':path},idempotency_key='parse:'+path+':'+file_hash,reason='本地提取历史报告'),ctx)
                if not res.data_ref:raise ValueError('unreadable_report:'+path)
                cached=res.data_ref;document=store.get_artifact(cached)
            refs.append(cached);documents.append(document)
        # execute_tool updates task bookkeeping; reload before saving our metadata.
        state=store.get_task(task_id)
        state.review_items=[]
        state.metadata.pop('structured_template_ref',None)
        state.metadata.pop('template_validation_ref',None)
        state.metadata['parsed_report_refs']=dict(zip(state.metadata['paths'],refs))
        comparison_res=await execute_tool(ToolCall(call_id=uuid.uuid4().hex,tool_name='compare_report_structures',arguments={'document_refs':refs},reason='本地多报告结构对齐'),ctx)
        if not comparison_res.data_ref:raise ValueError('comparison_failed')
        latest=store.get_task(task_id);state.tool_calls=latest.tool_calls
        state.result_refs=latest.result_refs;state.revision=latest.revision
        state.metadata['tool_results']=latest.metadata.get('tool_results',{})
        state.metadata['comparison_ref']=comparison_res.data_ref
        local=build_structured_template(documents,comparison_res.data_ref)
        state.metadata['local_template_ref']=store.put_artifact(task_id,'local_template_candidate',local)
        packet=make_input(documents,store.get_artifact(comparison_res.data_ref),local)
        input_hash=digest(packet)
        state.metadata['template_input_ref']=store.put_artifact(task_id,'template_model_input',packet)
        save('template_local_ready')
        checkpoints=state.metadata.get('template_review_checkpoints',{}) if state.metadata.get('template_input_hash')==input_hash else {}
        if state.metadata.get('template_input_hash')!=input_hash:state.metadata['template_batches']={}
        state.metadata.update(template_input_hash=input_hash,template_review_checkpoints=checkpoints)
        save('template_model_reviewing')
        combined,review_refs=await review_batches(store,state,ctx,packet,comparison_res.data_ref)
        candidate=compile_review(combined,packet,comparison_res.data_ref)
        candidate_ref=store.put_artifact(task_id,'structured_template_candidate',candidate)
        validated=TemplateCandidateState(policy_version=POLICY_VERSION,input_ref=state.metadata['template_input_ref'],
            input_hash=input_hash,review_refs=review_refs,candidate_ref=candidate_ref,candidate_hash=digest(candidate),validation='passed')
        state.metadata['template_validation_ref']=store.put_artifact(task_id,'template_validation',validated.model_dump())
        state.metadata['structured_template_ref']=candidate_ref
        state.metadata['model_analysis']={'summary':combined['summary'],'source_files':state.metadata['paths']}
        for question in candidate['review_items']:
            state.review_items.append(_item('template_business_question',question['question'],True,question))
        state.review_items.append(_item('template_candidate','请查看模型研判后的完整模板并整体确认。'))
        store.append_event(task_id,{'type':'structured_template_candidate','artifact':candidate_ref,'source_count':len(documents),'fields':len(candidate['fields']),'semantic_review':True})
        save('awaiting_template_confirmation')
    except Exception as exc:
        # A failed request is never reclassified as a human semantic decision.
        latest=store.get_task(task_id);state.revision=latest.revision
        state.tool_calls=latest.tool_calls;state.result_refs=latest.result_refs
        state.metadata.pop('structured_template_ref',None);state.metadata.pop('template_validation_ref',None)
        state.metadata['template_error']={'type':type(exc).__name__,'message':str(exc)[:600]}
        if isinstance(exc,ManualTemplateReviewRequired):
            state.review_items=[_item('template_exception','模型三轮纠正仍未通过，请在异常研判页查看原文、候选和全部问题。')]
            state.metadata['template_error']={'type':'manual_review_required','message':'模型已达到三轮上限，等待人工修正并重新校验。'}
            save('template_manual_review')
        else:save('template_review_failed')
    return state

def freeze_facts(deps:Dependencies,task_id:str):
    store=deps.store; state=store.get_task(task_id)
    if state.phase!='awaiting_review':raise ValueError('invalid_data_review_stage')
    if any(x['blocking'] and x['status']!='resolved' for x in state.review_items): raise ValueError('unresolved_blockers')
    if state.fact_ref: raise ValueError('facts_already_frozen')
    if not {'filter_records:negative_or_warning','confirmed_event_groups','confirmed_theme_groups'}<=state.result_refs.keys(): raise ValueError('data_review_required')
    metrics=store.get_artifact(state.result_refs['calculate_metrics'])
    metrics['negative_record_count']=len(store.get_artifact(state.result_refs['filter_records:negative'])['records'])
    metrics['warning_record_count']=len(store.get_artifact(state.result_refs['filter_records:warning'])['records'])
    metrics['negative_or_warning_record_count']=len(store.get_artifact(state.result_refs['filter_records:negative_or_warning'])['records'])
    groups=store.get_artifact(state.result_refs['confirmed_event_groups'])['groups']
    warning_ids={r['id'] for r in store.get_artifact(state.result_refs['filter_records:warning'])['records']}
    metrics['automatic_event_count']=len(groups)
    metrics['first_section_warning_event_count']=(sum(bool(set(g['member_ids'])&warning_ids) for g in groups)
        if state.metadata.get('template_rules',{}).get('first_warning_scope')=='warning' else len(groups))
    snapshot=FactSnapshot(id=uuid.uuid4().hex,template_ref=state.template_ref or '',input_refs=state.input_refs,result_refs=state.result_refs,report_month=state.metadata.get('report_month'),metrics=metrics,confirmed_event_count=len(groups),top10=state.metadata.get('reviewed_top10',[]),decisions=[x['decision'] for x in state.review_items if x.get('decision')])
    payload=snapshot.model_dump(exclude={'content_hash'}); snapshot.content_hash=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    state.fact_ref=store.put_artifact(task_id,'facts',snapshot.model_dump()); state.phase='facts_frozen'
    store.put_task(state,state.revision); store.append_event(task_id,{'type':'facts_frozen','fact_ref':state.fact_ref})
    return state

def make_draft(deps:Dependencies,task_id:str):
    store=deps.store; state=store.get_task(task_id)
    if not state.fact_ref: raise ValueError('facts_not_frozen')
    metrics=store.get_artifact(state.result_refs['calculate_metrics'])
    draft=DraftVersion(id=uuid.uuid4().hex,fact_ref=state.fact_ref,template_ref=state.template_ref or '',sections=[{'heading':'本月舆情概况','text':f"本次导入记录 {metrics['record_count']} 条。统计口径及事件归并以人工确认结果为准。",'locked':True},{'heading':'处理说明','text':'本稿使用已取得的 8 月标色 Word 作为版式来源。未确认槽位保留占位符。','locked':True}],recommendations=[])
    raw=draft.model_dump(exclude={'content_hash'}); draft.content_hash=hashlib.sha256(json.dumps(raw,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    state.draft_ref=store.put_artifact(task_id,'draft',draft.model_dump()); state.phase='awaiting_final_review'; store.put_task(state,state.revision)
    store.append_event(task_id,{'type':'draft_created','draft_ref':state.draft_ref,'draft_hash':draft.content_hash})
    return state

def make_preview(deps:Dependencies,task_id:str,slot_values:dict|None=None):
    store=deps.store; state=store.get_task(task_id)
    if state.kind!='report' or not state.fact_ref: raise ValueError('data_review_required')
    payload={'template_ref':state.template_ref,'input_refs':state.input_refs,'result_refs':state.result_refs,'report_month':state.metadata.get('report_month'),'status':'provisional_unconfirmed','version':0}
    provisional_ref=state.fact_ref
    metrics=store.get_artifact(state.result_refs['calculate_metrics'])
    draft=DraftVersion(id=uuid.uuid4().hex,fact_ref=provisional_ref,template_ref=state.template_ref or '',sections=[{'heading':'本月舆情概况','text':f"导入记录 {metrics['record_count']} 条；本期数据已审核锁定，文字与图表仍按当前完成情况展示。",'locked':True}],slot_values=slot_values or {},recommendations=[])
    raw=draft.model_dump(exclude={'content_hash'}); draft.content_hash=hashlib.sha256(json.dumps(raw,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    state.draft_ref=store.put_artifact(task_id,'preview_draft',draft.model_dump())
    missing=state.metadata.get('missing_fields')
    state.metadata['preview_only']=True if missing is None else bool(missing)
    store.put_task(state,state.revision); store.append_event(task_id,{'type':'preview_draft_created','draft_ref':state.draft_ref,'provisional_ref':provisional_ref})
    return state

async def _write_draft(deps:Dependencies,task_id:str):
    store=deps.store; state=store.get_task(task_id)
    if not state.fact_ref: raise ValueError('data_review_required')
    if state.template_ref and state.template_ref!='anshun-monthly-colored':
        from .structured_writer import write_structured_preview
        return await write_structured_preview(deps,task_id)
    ctx=RunContext(store,task_id)
    chart_inputs={'sentiment':{},'daily':{},'platform':{},'theme':{'cluster_ref':state.result_refs.get('confirmed_theme_groups')},'locality':{'locality_ref':state.result_refs.get('resolve_locality')}}
    for chart_type,extra in chart_inputs.items():
        state=store.get_task(task_id)
        prior=state.result_refs.get('render_chart:'+chart_type)
        if prior and store.get_artifact(prior).get('style_version')==2: continue
        call=ToolCall(call_id=uuid.uuid4().hex,tool_name='render_chart',arguments={'chart_type':chart_type,'metrics_ref':state.result_refs['calculate_metrics'],'style_version':2,**extra},reason='未确认草稿图表预览')
        await execute_tool(call,ctx)
    from .slot_writer import write_first_section_slots
    slot_values,slot_issues=await write_first_section_slots(deps,task_id,store.get_task(task_id).result_refs)
    store.append_event(task_id,{'type':'slot_writer_preview','filled':list(slot_values),'issues':slot_issues})
    state=store.get_task(task_id)
    state.metadata['writer_issues']=slot_issues
    state.metadata['missing_fields']=[x['slot_id'] for x in slot_issues]
    store.put_task(state,state.revision)
    return make_preview(deps,task_id,slot_values)
