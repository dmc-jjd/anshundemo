import asyncio
import pytest
from app.event_analysis import analyse_events,negative_ranking,validate_consolidation,Consolidation,BriefBatch
from app.schemas import TaskState,HumanDecision
from app.storage import Store
from app.workflow import Dependencies

def row(id,title,warning='是',sentiment='负面'):
    return {'id':id,'title':title,'summary':title,'warning':warning,'sentiment':sentiment,'category':'','source_ref':{}}

def setup(tmp_path,records):
    store=Store(tmp_path);source=store.put_artifact('t','records',{'records':records})
    groups=[{'id':f'g{i}','title':r['title'],'representative_id':r['id'],'member_ids':[r['id']]} for i,r in enumerate(records)]
    local=store.put_artifact('t','events',{'groups':groups,'all_record_ids':[r['id'] for r in records],
        'source_records_ref':source,'borderline_candidates':[{'id':'pair','source_group':'g1','target_group':'g0','score':.5}]})
    store.put_task(TaskState(id='t',kind='report',phase='analyzing',result_refs={'group_events':local}))
    return store

def test_ranking_counts_only_negative_warned_members_after_deduplication():
    records=[row('a','甲'),row('b','乙'),row('c','乙'),row('d','正面','是','正面')]+[row(str(i),'甲','否') for i in range(20)]
    groups=[{'id':'a','member_ids':['a']+[str(i) for i in range(20)]},{'id':'b','member_ids':['b','c']},{'id':'d','member_ids':['d']}]
    ranked=negative_ranking(groups,records)
    assert [x['id'] for x in ranked]==['b','a']
    assert [x['negative_warning_count'] for x in ranked]==[2,1]
    assert 'd' not in [rid for x in ranked for rid in x['negative_ids']]

def test_top10_cannot_override_human_distinct_event_decision():
    response=Consolidation(groups=[{'group_ids':['a','b']}])
    with pytest.raises(ValueError,match='human_distinct'):
        validate_consolidation(response,['a','b'],[('a','b')])

def test_brief_length_boundary_matches_model_and_table_schema():
    from pydantic import ValidationError
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError as SchemaError
    from app.structured_template import top10_table_schema
    for length in (15,35):
        BriefBatch.model_validate({'items':[{'id':'a','status':'complete','summary':'字'*length,'source_refs':['r']}]})
        Draft202012Validator(top10_table_schema()).validate([['1','字'*length,'2']])
    for length in (14,36):
        with pytest.raises(ValidationError):BriefBatch.model_validate({'items':[{'id':'a','status':'complete','summary':'字'*length,'source_refs':['r']}]})
        with pytest.raises(SchemaError):Draft202012Validator(top10_table_schema()).validate([['1','字'*length,'2']])
    BriefBatch.model_validate({'items':[{'id':'a','status':'uncertain','reason':'来源缺少事件内容'}]})

def test_only_explicit_model_uncertainty_goes_to_human(tmp_path):
    store=setup(tmp_path,[row('a','模糊内容甲'),row('b','模糊内容乙')])
    async def model(role,payload):
        if role=='event_judge' and 'events' in payload:return {'groups':[{'group_ids':[p['id']]} for p in payload['events']],'uncertain_pairs':[]}
        if role=='event_judge':return {'items':[{'id':p['id'],'decision':'uncertain','reason':'无法确定发生地点是否相同'} for p in payload['pairs']]}
        if role=='event_classifier':return {'items':[{'id':p['id'],'status':'uncertain','reason':'缺少事件主体','category':None} for p in payload['events']]}
        return {'items':[{'id':p['id'],'status':'complete','summary':'来源反映有关情况，具体事件主体尚不明确。','source_refs':[p['evidence'][0]['ref']]} for p in payload['events']]}
    result=asyncio.run(analyse_events(Dependencies(store,model),'t'))
    assert not result['pending_model']
    assert len(result['merge_ambiguities'])==1
    assert len(result['classification_issues'])==2
    assert all(x['reason']=='缺少事件主体' for x in result['classification_issues'])
    assert len(result['top10'])==2 and all(x['status']=='complete' for x in result['top10'])
    state=store.get_task('t');ref=state.result_refs['event_analysis']
    cluster=store.put_artifact('t','theme_groups',{'groups':result['theme_groups']})
    local=store.get_artifact(state.result_refs['group_events'])
    state.result_refs['filter_records:negative_or_warning']=local['source_records_ref']
    state.phase='awaiting_review';state.review_items=[{'id':'review','kind':'data_review','status':'open','blocking':True,
        'details':{'event_ref':ref,'cluster_ref':cluster,'analysis_ref':ref}}];store.put_task(state,state.revision)
    payload={'groups':result['groups'],'themes':[{'candidate_theme':'其他','member_ids':['a','b']}]}
    with pytest.raises(ValueError,match='merge_ambiguity_unresolved'):
        store.apply_decision('t',HumanDecision(item_id='review',expected_revision=state.revision,action='confirm',payload=payload,reason='review test'))
    payload['merge_decisions']={'pair':'different'}
    accepted=store.apply_decision('t',HumanDecision(item_id='review',expected_revision=state.revision,action='confirm',payload=payload,reason='explicit human review test'))
    assert accepted.review_items[0]['status']=='resolved'
    assert len(accepted.metadata['reviewed_top10'])==2

def test_model_failure_is_machine_pending_and_checkpoint_can_resume(tmp_path):
    store=setup(tmp_path,[row('a','未知事情甲'),row('b','未知事情乙')])
    async def broken(role,payload):raise RuntimeError('provider unavailable')
    failed=asyncio.run(analyse_events(Dependencies(store,broken),'t'))
    assert failed['pending_model'] and not failed['merge_ambiguities'] and not failed['classification_issues']
    calls=[]
    async def recovered(role,payload):
        calls.append(role)
        if role=='event_judge' and 'events' in payload:return {'groups':[{'group_ids':[p['id']]} for p in payload['events']],'uncertain_pairs':[]}
        if role=='event_judge':return {'items':[{'id':p['id'],'decision':'same','reason':'同一主体同一事件'} for p in payload['pairs']]}
        if role=='event_classifier':return {'items':[{'id':p['id'],'status':'classified','category':'其他','reason':'来源叙述完整'} for p in payload['events']]}
        return {'items':[{'id':p['id'],'status':'complete','summary':'来源反映同一主体发生有关情况。','source_refs':[p['evidence'][0]['ref']]} for p in payload['events']]}
    ready=asyncio.run(analyse_events(Dependencies(store,recovered),'t'))
    assert not ready['pending_model'] and len(ready['groups'])==1
    assert ready['groups'][0]['representative_id']=='a'
    assert ready['groups'][0]['member_ids']==['a','b']
    assert ready['top10'][0]['negative_warning_count']==2
    calls.clear();asyncio.run(analyse_events(Dependencies(store,recovered),'t'))
    assert calls==[]

def test_missing_model_items_are_schema_failure_not_human_cases(tmp_path):
    store=setup(tmp_path,[row('a','未知内容甲'),row('b','未知内容乙')])
    async def incomplete(role,payload):return {'items':[]}
    result=asyncio.run(analyse_events(Dependencies(store,incomplete),'t'))
    assert result['pending_model']
    assert not result['classification_issues'] and not result['merge_ambiguities']
    assert any(f['error']=='ValueError' for f in result['failures'])

def test_top10_model_check_consolidates_repeated_events_before_ranking(tmp_path):
    store=setup(tmp_path,[row('a','一名皮划艇选手落水'),row('b','景区通报落水选手已救起')])
    async def model(role,payload):
        if role=='event_judge' and 'events' in payload:
            ids=[p['id'] for p in payload['events']]
            return {'groups':[{'group_ids':ids}],'uncertain_pairs':[]}
        if role=='event_judge':return {'items':[{'id':p['id'],'decision':'different','reason':'synthetic first-pass miss'} for p in payload['pairs']]}
        if role=='event_classifier':return {'items':[{'id':p['id'],'status':'classified','category':'文化旅游','reason':'景区事件'} for p in payload['events']]}
        return {'items':[{'id':p['id'],'status':'complete','summary':'一名皮划艇选手落水，景区通报已将其救起。','source_refs':[p['evidence'][0]['ref']]} for p in payload['events']]}
    result=asyncio.run(analyse_events(Dependencies(store,model),'t'))
    assert not result['pending_model']
    assert len(result['groups'])==1 and len(result['top10'])==1
    assert result['top10'][0]['negative_warning_count']==2

def test_top10_invalid_coverage_is_repaired_and_resume_keeps_merge_state(tmp_path):
    store=setup(tmp_path,[row('a','未知情况甲'),row('b','未知情况乙')]);calls=[];attempts=0
    async def model(role,payload):
        nonlocal attempts
        calls.append(role)
        if role=='event_judge' and 'events' in payload:
            attempts+=1;ids=[x['id'] for x in payload['events']]
            if attempts==1:return {'groups':[{'group_ids':[ids[0]]}],'uncertain_pairs':[]}
            assert 'validation_error' in payload and ids[1] in payload['validation_error']
            return {'groups':[{'group_ids':[id]} for id in ids],'uncertain_pairs':[]}
        if role=='event_judge':return {'items':[{'id':x['id'],'decision':'different','reason':'different facts'} for x in payload['pairs']]}
        if role=='event_classifier':return {'items':[{'id':x['id'],'status':'classified','category':'其他','reason':'classified from content'} for x in payload['events']]}
        return {'items':[{'id':x['id'],'status':'complete','summary':'来源反映有关情况，具体事实以原文为准。','source_refs':[x['evidence'][0]['ref']]} for x in payload['events']]}
    result=asyncio.run(analyse_events(Dependencies(store,model),'t'))
    assert not result['pending_model'] and attempts==2
    state=store.get_task('t');checkpoint=store.get_artifact(state.result_refs['event_analysis_checkpoint'])
    assert len(checkpoint['top10_review_attempts'])==2 and checkpoint['merge_snapshot']['remaining']==[]
    calls.clear();resumed=asyncio.run(analyse_events(Dependencies(store,model),'t'))
    assert not calls and [g['member_ids'] for g in resumed['groups']]==[g['member_ids'] for g in result['groups']]
