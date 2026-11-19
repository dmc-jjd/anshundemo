import asyncio
import pytest

from app.storage import Store
from app.schemas import TaskState, HumanDecision
from app.workflow import Dependencies, _analyse_report_events, _analysis_refs
from core.classify import Verdict


def fixture(tmp_path, dedup=False, classification=True):
    store=Store(tmp_path)
    rows=[{'id':key,'title':'学校事件'+key,'summary':'合成测试内容','source_ref':{},'category':''} for key in ('a','b','c')]
    ref=store.put_artifact('t','records',{'records':rows})
    metrics=store.put_artifact('t','metrics',{})
    themes=store.put_artifact('t','theme_clusters',{'groups':[{'candidate_theme':'词典旧结果','member_ids':['a','b','c']}]})
    refs={'filter_records:negative_or_warning':ref,'calculate_metrics':metrics,'cluster_event_themes':themes}
    if dedup:
        refs['group_events']=store.put_artifact('t','events',{'groups':[
            {'id':r['id'],'member_ids':[r['id']],'representative_id':r['id'],'title':r['title']} for r in rows],
            'source_records_ref':ref,'all_record_ids':['a','b','c'],'borderline_candidates':[]})
    store.put_task(TaskState(id='t',kind='report',phase='processing',result_refs=refs,
        metadata={'template_rules':{'features_source':'task_snapshot','features':{
            'classification':classification,'dedup':dedup,'top10':False,'first_warning':False,'locality':False}}}))
    return store


def mock_head(monkeypatch, confidence=.75):
    from core.classify import semantic
    calls=[]
    def predict(records):
        calls.append([r['id'] for r in records])
        return [Verdict(record_id=r['id'],category='教育管理',confidence=confidence if r['id']=='a' else .74,source='bge') for r in records]
    monkeypatch.setattr(semantic,'predict_bge',predict)
    return calls


def test_llm_batches_twenty_and_logs_only_validated_batches(tmp_path,monkeypatch):
    from core.classify import semantic
    store=fixture(tmp_path)
    records=[{'id':str(i),'title':'合成事件','summary':'测试'} for i in range(45)]
    monkeypatch.setattr(semantic,'predict_bge',lambda rows:[
        Verdict(record_id=r['id'],category='教育管理',confidence=.74,source='bge') for r in rows])
    calls=[];events=[]
    original=store.append_event
    def record(task_id,event):
        events.append(event)
        return original(task_id,event)
    monkeypatch.setattr(store,'append_event',record)
    async def adapter(role,payload):
        calls.append([r['id'] for r in payload['events']])
        if len(calls)==1:return {'items':[]}  # 格式重试不能算作批次完成。
        return {'items':[{'id':r['id'],'status':'classified','category':'教育管理','reason':'测试'} for r in payload['events']]}
    result=asyncio.run(semantic.classify_units(Dependencies(store,adapter),'t',
        [{'id':r['id'],'member_ids':[r['id']]} for r in records],records))
    assert [len(batch) for batch in calls]==[20,20,20,5]
    assert not result['pending_model']
    progress=[e for e in events if e['type']=='classification_batch_completed']
    assert [(e['total'],e['batch_index'],e['batch_total'],e['batch_size']) for e in progress]==[
        (45,1,3,20),(45,2,3,20),(45,3,3,5)]


def test_analysis_gate_does_not_require_dedup():
    refs=_analysis_refs({'dedup':False,'classification':True})
    assert 'group_events' not in refs
    assert 'filter_records:negative_or_warning' in refs


@pytest.mark.parametrize('dedup',[False,True])
def test_threshold_and_llm_uncertainty_with_both_dedup_modes(tmp_path,monkeypatch,dedup):
    store=fixture(tmp_path,dedup)
    head=mock_head(monkeypatch)
    calls=[]
    async def adapter(role,payload):
        assert role=='event_classifier'
        ids=[r['id'] for r in payload['events']];calls.append(ids)
        assert ids==['b','c']
        return {'items':[{'id':'b','status':'classified','category':'社会民生','reason':'合成语义判断'},
                         {'id':'c','status':'uncertain','category':None,'reason':'缺少事实'}]}
    asyncio.run(_analyse_report_events(Dependencies(store,adapter),'t'))
    state=store.get_task('t')
    ref=state.result_refs['event_analysis'] if dedup else state.result_refs['semantic_classification']
    result=store.get_artifact(ref)
    assert not result['pending_model']
    assert result['classification_counts']['bge']==1
    assert result['classification_counts']['llm']==1
    assert result['classification_counts']['human']==1
    assert head==[['a','b','c']] and calls==[['b','c']]
    if not dedup:
        assert 'group_events' not in state.result_refs and 'event_analysis' not in state.result_refs
        assert store.get_artifact(state.result_refs['cluster_event_themes'])['groups']==result['theme_groups']
    asyncio.run(_analyse_report_events(Dependencies(store,adapter),'t'))
    assert len(head)==1 and len(calls)==1


@pytest.mark.parametrize('failure',['transport','missing','invalid_category'])
def test_model_failures_do_not_become_human_cases(tmp_path,monkeypatch,failure):
    store=fixture(tmp_path)
    mock_head(monkeypatch,.749999)
    async def adapter(role,payload):
        if failure=='transport':raise RuntimeError('offline')
        if failure=='missing':return {'items':[]}
        return {'items':[{'id':r['id'],'status':'classified','category':'不存在的类别','reason':'invalid'} for r in payload['events']]}
    state=asyncio.run(_analyse_report_events(Dependencies(store,adapter),'t'))
    assert state.phase=='analysis_pending'
    result=store.get_artifact(state.result_refs['semantic_classification'])
    assert result['pending_model'] and not result['classification_issues']
    assert result['classification_counts']['human']==0
    assert result['classification_counts']['pending_model']==3


def test_closed_package_categories_cannot_accept_extra_bge_class(tmp_path,monkeypatch):
    from core.classify import semantic
    store=fixture(tmp_path)
    monkeypatch.setattr(semantic,'predict_bge',lambda records:[Verdict(record_id=r['id'],category='无效内容',confidence=.99,source='bge') for r in records])
    calls=[]
    async def adapter(role,payload):
        calls.extend(r['id'] for r in payload['events'])
        return {'items':[{'id':r['id'],'status':'uncertain','reason':'模板类别不适用'} for r in payload['events']]}
    asyncio.run(_analyse_report_events(Dependencies(store,adapter),'t'))
    assert calls==['a','b','c']


def test_classification_disabled_never_calls_models(tmp_path,monkeypatch):
    store=fixture(tmp_path,classification=False)
    from core.classify import semantic
    monkeypatch.setattr(semantic,'predict_bge',lambda records:pytest.fail('classification disabled'))
    async def adapter(*args):pytest.fail('classification disabled')
    asyncio.run(_analyse_report_events(Dependencies(store,adapter),'t'))
    assert 'semantic_classification' not in store.get_task('t').result_refs


def test_failed_batch_resumes_without_repeating_head_or_successful_llm(tmp_path,monkeypatch):
    store=fixture(tmp_path);head=mock_head(monkeypatch)
    async def unavailable(*args):raise RuntimeError('offline')
    asyncio.run(_analyse_report_events(Dependencies(store,unavailable),'t'))
    async def recovered(role,payload):
        return {'items':[{'id':r['id'],'status':'classified','category':'社会民生','reason':'恢复后判断'} for r in payload['events']]}
    asyncio.run(_analyse_report_events(Dependencies(store,recovered),'t'))
    result=store.get_artifact(store.get_task('t').result_refs['semantic_classification'])
    assert not result['pending_model'] and head==[['a','b','c']]


def test_word_match_still_goes_through_head_and_low_confidence_llm(tmp_path,monkeypatch):
    store=fixture(tmp_path);head=mock_head(monkeypatch,.74);calls=[]
    async def adapter(role,payload):
        calls.extend(r['id'] for r in payload['events'])
        return {'items':[{'id':r['id'],'status':'classified','category':'教育管理','reason':'语义确认'} for r in payload['events']]}
    asyncio.run(_analyse_report_events(Dependencies(store,adapter),'t'))
    assert head==[['a','b','c']] and calls==['a','b','c']


def test_human_override_survives_without_calling_models(tmp_path,monkeypatch):
    from core.classify import semantic
    store=fixture(tmp_path);state=store.get_task('t')
    records=store.get_artifact(state.result_refs['filter_records:negative_or_warning'])['records']
    monkeypatch.setattr(semantic,'predict_bge',lambda records:pytest.fail('human overrides must win'))
    async def adapter(*args):pytest.fail('human overrides must win')
    result=asyncio.run(semantic.classify_units(Dependencies(store,adapter),'t',
        [{'id':r['id'],'member_ids':[r['id']]} for r in records],records,
        {r['id']:'社会民生' for r in records}))
    assert result['classification_counts']['human_override']==3
    assert not result['pending_model']


def test_confirmation_cannot_override_machine_pending(tmp_path,monkeypatch):
    store=fixture(tmp_path);mock_head(monkeypatch)
    async def unavailable(*args):raise RuntimeError('offline')
    asyncio.run(_analyse_report_events(Dependencies(store,unavailable),'t'))
    state=store.get_task('t')
    state.review_items=[{'id':'review','kind':'data_review','status':'open','allowed_actions':['confirm'],
                        'details':{'cluster_ref':state.result_refs['cluster_event_themes']}}]
    store.put_task(state,state.revision);state=store.get_task('t')
    with pytest.raises(ValueError,match='model_analysis_pending'):
        store.apply_decision('t',HumanDecision(item_id='review',expected_revision=state.revision,
            action='confirm',reason='test',payload={'groups':[],
                'themes':[{'candidate_theme':'社会民生','member_ids':['a','b','c']}]}))


def test_real_report_graph_classifies_without_generating_dedup_groups(tmp_path,monkeypatch):
    from core.classify import semantic
    from test_template_processing_features import _run_report
    calls=[]
    def head(records):
        calls.extend(r['id'] for r in records)
        return [Verdict(record_id=r['id'],category='教育管理',confidence=.9,source='bge') for r in records]
    monkeypatch.setattr(semantic,'predict_bge',head)
    state,events=_run_report(tmp_path,monkeypatch,{'dedup':False,'classification':True,'top10':False,'first_warning':False})
    assert state['phase']=='awaiting_review'
    assert 'semantic_classification' in state['result_refs']
    assert 'group_events' not in state['result_refs'] and 'event_analysis' not in state['result_refs']
    assert len(calls)==3
    assert any(e['type']=='semantic_classification_summary' and e['counts']['bge']==3 for e in events)


@pytest.mark.parametrize('confidence',[float('nan'),float('inf'),-1,1.01])
def test_invalid_bge_probabilities_cannot_bypass_llm(tmp_path,monkeypatch,confidence):
    store=fixture(tmp_path);mock_head(monkeypatch,confidence);calls=[]
    async def adapter(role,payload):
        calls.extend(r['id'] for r in payload['events'])
        return {'items':[{'id':r['id'],'status':'classified','category':'教育管理','reason':'有效语义'} for r in payload['events']]}
    asyncio.run(_analyse_report_events(Dependencies(store,adapter),'t'))
    assert calls==['a','b','c']


def test_bge_unavailable_falls_back_to_llm_and_is_audited(tmp_path,monkeypatch):
    from core.classify import semantic
    store=fixture(tmp_path)
    monkeypatch.setattr(semantic,'predict_bge',lambda records:[Verdict(r['id'],reason='bge_unavailable',borderline=True) for r in records])
    async def adapter(role,payload):
        return {'items':[{'id':r['id'],'status':'classified','category':'教育管理','reason':'模型语义判断'} for r in payload['events']]}
    asyncio.run(_analyse_report_events(Dependencies(store,adapter),'t'))
    state=store.get_task('t');result=store.get_artifact(state.result_refs['semantic_classification'])
    assert result['classification_counts']['llm']==3 and not result['pending_model']
    assert all(r['bge']['reason']=='bge_unavailable' for r in result['items'])


def test_edited_input_invalidates_only_changed_unit(tmp_path,monkeypatch):
    from core.classify import semantic
    store=fixture(tmp_path);head=mock_head(monkeypatch)
    async def adapter(role,payload):
        return {'items':[{'id':r['id'],'status':'classified','category':'教育管理','reason':'语义判断'} for r in payload['events']]}
    asyncio.run(_analyse_report_events(Dependencies(store,adapter),'t'))
    state=store.get_task('t');rows=store.get_artifact(state.result_refs['filter_records:negative_or_warning'])['records']
    rows[1]['summary']='变更后的事实'
    state.result_refs['filter_records:negative_or_warning']=store.put_artifact('t','records',{'records':rows})
    store.put_task(state,state.revision)
    asyncio.run(_analyse_report_events(Dependencies(store,adapter),'t'))
    assert head==[['a','b','c'],['b']]


def test_paused_task_never_enters_head_or_llm(tmp_path,monkeypatch):
    from core.model_client import TaskPaused
    store=fixture(tmp_path);head=mock_head(monkeypatch)
    state=store.get_task('t');state.cancel_requested=True;store.put_task(state,state.revision)
    async def adapter(*args):pytest.fail('paused task')
    asyncio.run(_analyse_report_events(Dependencies(store,adapter),'t'))
    assert not head


def test_previous_review_cannot_confirm_while_head_is_running(tmp_path,monkeypatch):
    from core.classify import semantic
    from app.review_service import review_data
    store=fixture(tmp_path);state=store.get_task('t')
    state.review_items=[{'id':'review','kind':'data_review','status':'open','allowed_actions':['confirm'],
                        'details':{'cluster_ref':state.result_refs['cluster_event_themes']}}]
    store.put_task(state,state.revision)
    observations=[]
    def head(records):
        running=store.get_task('t')
        observations.append(review_data(store,'t')['analysis_pending'])
        try:
            store.apply_decision('t',HumanDecision(item_id='review',expected_revision=running.revision,
                action='confirm',reason='stale browser',payload={'groups':[],
                    'themes':[{'candidate_theme':'教育管理','member_ids':['a','b','c']}]}))
        except ValueError as exc:observations.append(str(exc))
        else:observations.append('accepted')
        return [Verdict(record_id=r['id'],category='教育管理',confidence=.9,source='bge') for r in records]
    monkeypatch.setattr(semantic,'predict_bge',head)
    async def adapter(*args):pytest.fail('head should resolve all records')
    asyncio.run(_analyse_report_events(Dependencies(store,adapter),'t'))
    assert observations==[True,'model_analysis_pending']
