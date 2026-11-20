import pytest
from app.template_agent_review import status_for, record_dispositions, normalize_review_targets, rebase_addressed_dispositions

def test_legacy_category_review_points_to_dynamic_field():
    definition={'fields':[{'id':'numbered_items_1','category_coverage_scope':'negative_warning_events','block':19}],
                'human_review_items':[{'field_id':'b28_item','message':'类别条目超过10项'}]}
    result=normalize_review_targets(definition)
    assert result['human_review_items'][0]['field_id']=='numbered_items_1'
    assert result['human_review_items'][0]['target_block']==19

def test_addressed_opinion_survives_user_candidate_edit():
    definition=fixture();metadata={};item=status_for(definition,[],metadata)['opinions']['items'][0]
    record_dispositions(definition,[],metadata,[{'kind':'opinion','id':item['id'],'status':'addressed','note':'已处理','evidence':'字段 a'}])
    definition['fields'].append({'id':'user_added','owner':'writer'})
    rebase_addressed_dispositions(definition,metadata)
    assert status_for(definition,[],metadata)['opinions']['addressed']==1

def fixture():
    return {'fields':[{'id':'a'}],'blocks':[],'rules':{},'human_review_items':[{'message':'检查分类数量','field_id':'a'}]}

def test_only_evidenced_current_dispositions_count_as_addressed():
    definition=fixture();questions=[{'id':'business-1','question':'保留章节？','status':'open'}]
    metadata={};status=status_for(definition,questions,metadata)
    item=status['opinions']['items'][0]
    assert status['opinions']['addressed']==0
    record_dispositions(definition,questions,metadata,[{'kind':'opinion','id':item['id'],'status':'addressed','note':'已调整并重读验证','evidence':'候选字段 a 的规则与保存后值一致'}])
    assert status_for(definition,questions,metadata)['opinions']['addressed']==1
    definition['fields'][0]['rule']='再次修改'
    result=status_for(definition,questions,metadata)
    assert result['opinions']['addressed']==0
    assert result['opinions']['items'][0]['status']=='stale'
    assert questions[0]['status']=='open'

def test_invalid_or_unsupported_resolution_does_not_mutate_metadata():
    definition=fixture();metadata={};item=status_for(definition,[],metadata)['opinions']['items'][0]
    with pytest.raises(ValueError):
        record_dispositions(definition,[],metadata,[{'kind':'opinion','id':item['id'],'status':'addressed','note':'已修','evidence':''}])
    assert metadata=={}
    with pytest.raises(ValueError):
        record_dispositions(definition,[],metadata,[{'kind':'business','id':'missing','status':'addressed','note':'已修','evidence':'物证'}])
    assert metadata=={}

def test_review_notes_api_preserves_confirmation_and_checks_revision(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main
    from test_template_name_and_field_edit import _store,_create_task
    store,_=_store(tmp_path,monkeypatch)
    with TestClient(main.app) as client:
        task_id,state=_create_task(client,store)
        state=store.get_task(task_id)
        candidate=store.get_artifact(state.metadata['structured_template_ref'])
        candidate['human_review_items']=[{'message':'核对字段','field_id':candidate['fields'][0]['id']}]
        state.metadata['structured_template_ref']=store.put_artifact(task_id,'structured_template_candidate',candidate)
        store.put_task(state,state.revision)
        url=f'/api/templates/{task_id}'
        data=client.get(url+'/definition').json()
        entry={'kind':'opinion','id':data['agent_review_status']['opinions']['items'][0]['id'],'status':'addressed','note':'字段已核查','evidence':'合成回归验证字段描述保留'}
        payload={'expected_revision':data['revision'],'entries':[entry]}
        response=client.put(url+'/agent-review',json=payload)
        assert response.status_code==200,response.text
        assert response.json()['agent_review_status']['opinions']['addressed']==1
        assert not store.get_task(task_id).metadata.get('confirmed_template_ref')
        assert client.put(url+'/agent-review',json=payload).status_code==409
        state=store.get_task(task_id);state.metadata['confirmed_template_ref']=state.metadata['structured_template_ref'];store.put_task(state,state.revision)
        payload['expected_revision']=store.get_task(task_id).revision
        assert client.put(url+'/agent-review',json=payload).status_code==409
