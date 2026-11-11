from fastapi.testclient import TestClient
from app.storage import Store
from app.schemas import TaskState
from app.workflow import Dependencies


def fixture(tmp_path,monkeypatch):
    import app.main as main
    store=Store(tmp_path/'store')
    records=[{'id':rid,'title':rid,'summary':rid,'sentiment':'负面','warning':'是','source_ref':{}} for rid in ('a','b','c')]
    source=store.put_artifact('draft','records',{'records':records})
    groups=[{'id':rid,'representative_id':rid,'title':rid,'member_ids':[rid]} for rid in ('a','b','c')]
    themes=[{'candidate_theme':'待人工分类','member_ids':['a','b','c']}]
    cases=[{'id':'ab','source_id':'a','target_id':'b','source_evidence':[],'target_evidence':[],'reason':'unknown'},
           {'id':'ac','source_id':'a','target_id':'c','source_evidence':[],'target_evidence':[],'reason':'unknown'}]
    analysis=store.put_artifact('draft','analysis',{'groups':groups,'theme_groups':themes,'merge_ambiguities':cases,'all_record_ids':['a','b','c'],'top10':[]})
    local=store.put_artifact('draft','local',{'groups':groups,'all_record_ids':['a','b','c'],'method':{'threshold':.65},'source_records_ref':source})
    clusters=store.put_artifact('draft','clusters',{'groups':themes})
    metrics=store.put_artifact('draft','metrics',{'record_count':3})
    state=TaskState(id='draft',kind='report',phase='awaiting_review',result_refs={'event_analysis':analysis,'group_events':local,'filter_records:negative_or_warning':source,'cluster_event_themes':clusters,'calculate_metrics':metrics})
    store.put_task(state);monkeypatch.setattr(main,'store',store);monkeypatch.setattr(main,'deps',Dependencies(store))
    return store,main,groups,analysis


def test_legacy_update_preserves_partial_relationships_before_rejecting(tmp_path,monkeypatch):
    store,main,groups,analysis=fixture(tmp_path,monkeypatch)
    groups[0]['member_ids']=['a','b'];groups.pop(1)
    with TestClient(main.app) as client:
        result=client.post('/api/tasks/draft/event-settings',json={'expected_revision':0,'groups':groups,'merge_decisions':{'ab':'same'}})
        assert result.status_code==409 and '已保存 1 项人工判断' in result.json()['detail']
    saved=store.get_review_draft('draft',analysis)
    assert saved['data']['merge_decisions']=={'ab':'same'} and len(saved['data']['groups'])==2
    assert store.get_task('draft').revision==0 and store.get_task('draft').fact_ref is None


def test_partial_draft_restores_decisions_categories_and_briefs_without_unlocking(tmp_path,monkeypatch):
    store,main,groups,analysis=fixture(tmp_path,monkeypatch)
    payload={'groups':groups,'themes':[{'candidate_theme':'交通管理','member_ids':['a']},{'candidate_theme':'待人工分类','member_ids':['b','c']}],
        'merge_decisions':{'ab':'different'},'briefs':{'sample':{'status':'complete','summary':'人工补充梗概','source_refs':['a']}},'groups_dirty':False}
    with TestClient(main.app) as client:
        saved=client.put('/api/tasks/draft/review-draft',json={'expected_revision':0,'analysis_ref':analysis,'expected_version':0,'data':payload})
        assert saved.status_code==200 and saved.json()['pending_relationships']==['ac']
        view=client.get('/api/tasks/draft/review-data').json()
        assert view['review_draft']==payload and view['draft_version']==1
        assert client.put('/api/tasks/draft/review-draft',json={'expected_revision':0,'analysis_ref':analysis,'expected_version':0,'data':payload}).status_code==409
        assert store.get_task('draft').fact_ref is None


def test_relationship_conflict_is_saved_and_explicitly_identified(tmp_path,monkeypatch):
    store,main,groups,analysis=fixture(tmp_path,monkeypatch)
    groups[0]['member_ids']=['a','b'];groups.pop(1)
    with TestClient(main.app) as client:
        result=client.put('/api/tasks/draft/review-draft',json={'expected_revision':0,'analysis_ref':analysis,'data':{'groups':groups,'merge_decisions':{'ab':'different'}}})
        assert result.status_code==200 and result.json()['conflicting_relationships']==['ab']


def test_human_final_groups_apply_locally_and_never_run_models_again(tmp_path,monkeypatch):
    store,main,groups,analysis=fixture(tmp_path,monkeypatch)
    state=store.get_task('draft')
    import hashlib,json
    fp=lambda ids:hashlib.sha256(json.dumps(sorted(ids)).encode()).hexdigest()
    state.result_refs['event_analysis_checkpoint']=store.put_artifact('draft','checkpoint',{'classes':{'a':{'id':'a','status':'classified','category':'其他','reason':'cached'},'c':{'id':'c','status':'classified','category':'文化旅游','reason':'cached'}},
        'classification_members':{'a':fp(['a']),'c':fp(['c'])},'briefs':{}})
    store.put_task(state,state.revision)
    groups[0]['member_ids']=['a','b'];groups.pop(1)
    themes=[{'candidate_theme':'交通管理','member_ids':['a','b']},{'candidate_theme':'待人工分类','member_ids':['c']}]
    calls=[]
    async def do_not_run(deps,task_id):calls.append(task_id);raise AssertionError('human final decisions must not return to model processing')
    monkeypatch.setattr(main,'run_report_graph',do_not_run)
    with TestClient(main.app) as client:
        result=client.post('/api/tasks/draft/event-settings',json={'expected_revision':state.revision,'groups':groups,'themes':themes,'merge_decisions':{'ab':'same','ac':'different'}})
        assert result.status_code==200
    updated=store.get_task('draft');local=store.get_artifact(updated.result_refs['group_events'])
    result=store.get_artifact(updated.result_refs['event_analysis'])
    assert updated.phase=='awaiting_review' and updated.metadata['human_review_final']
    assert next(t['member_ids'] for t in result['theme_groups'] if t['candidate_theme']=='交通管理')==['a','b']
    assert len(local['human_relationship_decisions'])==2
    assert result['human_merge_decisions']=={'ab':'same','ac':'different'}
    assert calls==[]
    with TestClient(main.app) as client:
        assert client.post('/api/tasks/draft/resume').json()['phase']=='awaiting_review'
    assert calls==[]


def test_human_merge_with_category_conflict_goes_to_human_not_model(tmp_path,monkeypatch):
    from app.data_review import apply_human_review
    store,main,groups,analysis=fixture(tmp_path,monkeypatch)
    groups[0]['member_ids']=['a','b'];groups.pop(1)
    result=apply_human_review(store,store.get_task('draft'),{'groups':groups,'themes':[{'candidate_theme':'交通管理','member_ids':['a']},{'candidate_theme':'市场监管','member_ids':['b']},{'candidate_theme':'待人工分类','member_ids':['c']}],
        'merge_decisions':{'ab':'same','ac':'different'},'briefs':{}})
    assert len(result['classification_issues'])==2
    assert '冲突' in result['classification_issues'][0]['reason']
    assert not result['pending_model']


def test_unchanged_summaries_preserved_changed_event_requires_human_summary(tmp_path,monkeypatch):
    from app.data_review import apply_human_review
    from app.event_analysis import negative_ranking
    store,main,groups,analysis=fixture(tmp_path,monkeypatch)
    state=store.get_task('draft');original=store.get_artifact(analysis)
    records=store.get_artifact(state.result_refs['filter_records:negative_or_warning'])['records']
    original['top10']=[{**r,'rank':i+1,'status':'complete','summary':'来源反映有关服务问题，要求相关单位核实处理。','source_refs':r['negative_ids']} for i,r in enumerate(negative_ranking(groups,records))]
    baseline=store.put_artifact('draft','baseline',original)
    groups[0]['member_ids']=['a','b'];groups.pop(1)
    result=apply_human_review(store,state,{'groups':groups,'themes':[{'candidate_theme':'其他','member_ids':['a','b','c']}],'merge_decisions':{'ab':'same','ac':'different'},'briefs':{}},baseline)
    assert result['top10'][0]['negative_warning_count']==2 and result['top10'][0]['status']=='uncertain'
    assert result['top10'][1]['status']=='complete' and result['top10'][1]['negative_ids']==['c']
