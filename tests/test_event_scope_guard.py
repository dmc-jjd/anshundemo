import asyncio
import pytest
from app.storage import Store
from app.schemas import TaskState,ToolCall,ToolResult
from app.workflow import Dependencies
from core.ports import ToolPolicy
from core.tool_executor import RunContext,execute_tool


def scoped(tmp_path):
    store=Store(tmp_path)
    records=[{'id':'n','title':'负面事件','summary':'测试','sentiment':'负面','warning':'否'},
             {'id':'p','title':'正面报道','summary':'测试','sentiment':'正面','warning':'否'}]
    full=store.put_artifact('t','records',{'records':records})
    wanted=store.put_artifact('t','records',{'records':records[:1],'scope':'negative_or_warning','parent_ref':full})
    store.put_task(TaskState(id='t',kind='report',phase='processing',result_refs={
        'import_records':full,'filter_records:negative_or_warning':wanted},
        metadata={'event_scope':'negative_or_warning','event_scope_confirmed':True}))
    return store,records,full,wanted


@pytest.mark.parametrize('tool',['group_events','classify_records','cluster_event_themes','discover_topics'])
def test_wrong_population_is_rejected_before_worker_or_cache(tmp_path,monkeypatch,tool):
    import core.tool_executor as executor
    store,_,full,wanted=scoped(tmp_path)
    monkeypatch.setattr(executor,'_bounded_run',lambda *args:pytest.fail('wrong scope reached worker'))
    ctx=RunContext(store,'t',policy=ToolPolicy(allow=frozenset({tool})))
    result=asyncio.run(execute_tool(ToolCall(call_id='bad',tool_name=tool,arguments={'records_ref':full}),ctx))
    assert result.error_code=='event_scope_mismatch'
    assert store.get_task('t').tool_calls==0


def test_grouping_wrong_scope_never_reaches_relation_or_classification_models(tmp_path,monkeypatch):
    from core.event_analysis import analyse_events
    store,records,full,_=scoped(tmp_path);state=store.get_task('t')
    state.result_refs['group_events']=store.put_artifact('t','automatic_event_groups',{
        'source_records_ref':full,'all_record_ids':[r['id'] for r in records],
        'groups':[{'id':r['id'],'representative_id':r['id'],'member_ids':[r['id']]} for r in records]})
    store.put_task(state,state.revision)
    async def model(*args):pytest.fail('out-of-scope input must never reach models')
    with pytest.raises(ValueError,match='event_scope'):
        asyncio.run(analyse_events(Dependencies(store,model),'t'))


def test_semantic_classification_cannot_bypass_scope_guard(tmp_path,monkeypatch):
    from core.classify import semantic
    store,records,_,_=scoped(tmp_path)
    monkeypatch.setattr(semantic,'predict_bge',lambda *args:pytest.fail('out-of-scope BGE call'))
    with pytest.raises(ValueError,match='event_scope'):
        asyncio.run(semantic.classify_units(Dependencies(store),'t',
            [{'id':r['id'],'member_ids':[r['id']]} for r in records],records))


def test_correct_population_reaches_worker(tmp_path,monkeypatch):
    import core.tool_executor as executor
    store,_,_,wanted=scoped(tmp_path);calls=[]
    def worker(name,args,*unused):
        calls.append(args['records_ref'])
        return ToolResult(status='ok',data_ref=store.put_artifact('t','groups',{'groups':[]}))
    monkeypatch.setattr(executor,'_bounded_run',worker)
    ctx=RunContext(store,'t',policy=ToolPolicy(allow=frozenset({'group_events'})))
    result=asyncio.run(execute_tool(ToolCall(call_id='ok',tool_name='group_events',arguments={'records_ref':wanted}),ctx))
    assert result.status=='ok' and calls==[wanted]


def test_wrong_scope_cached_success_cannot_bypass_guard(tmp_path,monkeypatch):
    store,_,full,_=scoped(tmp_path);state=store.get_task('t')
    state.metadata['tool_results']={'cached':{'status':'ok','data_ref':full}}
    store.put_task(state,state.revision)
    ctx=RunContext(store,'t',policy=ToolPolicy(allow=frozenset({'group_events'})))
    call=ToolCall(call_id='cached',tool_name='group_events',idempotency_key='cached',arguments={'records_ref':full})
    assert asyncio.run(execute_tool(call,ctx)).error_code=='event_scope_mismatch'


def test_correctly_named_but_wrong_filter_artifact_is_rejected(tmp_path):
    from core.event_scope import population
    store,_,full,_=scoped(tmp_path);state=store.get_task('t')
    state.result_refs['filter_records:negative_or_warning']=full
    store.put_task(state,state.revision)
    with pytest.raises(ValueError,match='event_scope_mismatch'):population(store,state)


def test_workflow_stale_groups_stop_before_models_and_review(tmp_path):
    from app.workflow import _analyse_report_events
    store,records,full,wanted=scoped(tmp_path);state=store.get_task('t')
    state.result_refs.update(calculate_metrics=store.put_artifact('t','metrics',{}),
                            cluster_event_themes=store.put_artifact('t','themes',{'groups':[]}))
    state.result_refs['group_events']=store.put_artifact('t','events',{'source_records_ref':full,'groups':[],
        'all_record_ids':[r['id'] for r in records]})
    state.metadata['template_rules']={'features_source':'task_snapshot','features':{'dedup':True,'classification':True,'top10':False,'first_warning':False,'locality':False}}
    store.put_task(state,state.revision)
    result=asyncio.run(_analyse_report_events(Dependencies(store),'t'))
    assert result.phase=='analysis_pending' and result.metadata['analysis_pending']
    assert result.metadata['event_scope_error'].startswith('event_scope_mismatch')


@pytest.mark.parametrize('ready',[False,True])
def test_dynamic_planner_cannot_classify_before_scope_is_ready(tmp_path,monkeypatch,ready):
    import app.workflow as workflow
    import app.report_planning as planning
    from core.schemas import ToolDecision
    store,_,full,wanted=scoped(tmp_path);state=store.get_task('t')
    if not ready:state.result_refs.pop('filter_records:negative_or_warning')
    state.metadata.update(mode='dynamic',input_path='test.xlsx')
    store.put_task(state,state.revision)
    features={'dedup':True,'classification':True,'top10':False,'first_warning':False,'locality':False}
    monkeypatch.setattr(workflow,'_template_features',lambda *a:features)
    monkeypatch.setattr(planning,'planning_template',lambda *a:{})
    async def decide(*a):
        return ToolDecision(action='call_tool',tool_name='classify_records',arguments={'records_ref':full})
    monkeypatch.setattr(workflow,'invoke_agent',decide)
    calls=[]
    async def execute(call,ctx):
        current=store.get_task('t')
        if call.tool_name=='filter_records':
            current.result_refs['filter_records:'+call.arguments['scope']]=wanted
        elif call.tool_name=='classify_records':
            assert 'filter_records:negative_or_warning' in current.result_refs
            assert call.arguments['records_ref']==wanted
        current.result_refs[call.tool_name]=wanted
        store.put_task(current,current.revision);calls.append(call.tool_name)
        return ToolResult(status='ok',data_ref=wanted)
    monkeypatch.setattr(workflow,'execute_tool',execute)
    asyncio.run(workflow._process_records(Dependencies(store),'t'))
    assert 'classify_records' in calls
    if not ready:assert calls.index('filter_records')<calls.index('classify_records')
