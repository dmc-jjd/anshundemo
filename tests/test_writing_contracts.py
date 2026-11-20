import pytest

from core.writing_contracts import validate_contract, expand_fields, group_context, repair_allowed


def contract():
    return {'groups':[{'id':'case','label':'案例链','members':{'case':'case','analysis':'analysis','advice':'advice'},
                       'instruction':'三段使用同一个案例','query':{'focus':'all','limit':10}}]}


def fields():
    return {name:{'id':name,'owner':'writer'} for name in ['case','analysis','advice','other']}


def test_group_expands_joint_request_and_carries_previously_written_case():
    c=validate_contract(contract(),fields())
    assert expand_fields(['analysis'],c,fields())==['case','analysis','advice']
    values={'case':{'value':'已选定案例','source_refs':['record-1']}}
    context=group_context(['analysis'],c,values)
    assert context[0]['existing_values']==values
    assert context[0]['members']['case']=='case'


def test_invalid_or_overlapping_groups_are_rejected():
    c=contract();c['groups'][0]['members']['missing']='background'
    with pytest.raises(ValueError):validate_contract(c,fields())
    c=contract();c['groups'].append({**c['groups'][0],'id':'duplicate'})
    with pytest.raises(ValueError):validate_contract(c,fields())


def test_group_context_does_not_disclose_human_private_text():
    import json
    c=validate_contract(contract(),fields())
    context=group_context(['analysis'],c,{'case':{'value':'人工私密原文','source_refs':['human_edit']}})
    assert '人工私密原文' not in json.dumps(context,ensure_ascii=False)
    assert context[0]['existing_values']['case']['human_confirmed'] is True


def test_logic_repair_can_replace_machine_dates_but_not_style_or_data():
    c=validate_contract(contract(),fields())
    assert repair_allowed('analysis',[{'kind':'logic'}],c,{'owner':'writer'},['source-1'])
    assert not repair_allowed('analysis',[{'kind':'style'}],c,{'owner':'writer'},['source-1'])
    assert not repair_allowed('analysis',[{'kind':'logic'}],c,{'owner':'data'},['source-1'])
    assert not repair_allowed('analysis',[{'kind':'logic'}],c,{'owner':'writer'},[])


def test_group_schedule_keeps_case_analysis_advice_in_one_request():
    from core.writing_contracts import writing_blocks
    t={'fields':list(fields().values()),'blocks':[
        {'index':i,'parts':[{'text':name+':'},{'field':name}]} for i,name in enumerate(fields())]}
    blocks=writing_blocks(t,validate_contract(contract(),fields()))
    assert len(blocks)==2
    assert [p['field'] for p in blocks[0]['parts'] if p.get('field')]==['case','analysis','advice']


def test_relation_rules_survive_processing_rule_normalization():
    from app.api_views.template import rules_for_features
    rules={'features':{'dedup':True,'classification':True,'first_warning':False,'top10':False},'writing_groups':contract()['groups']}
    saved=rules_for_features(rules)['writing_groups']
    assert saved[0]['members']==rules['writing_groups'][0]['members']
    assert saved[0]['instruction']==rules['writing_groups'][0]['instruction']


def test_writer_sends_related_fields_together_with_original_layout(tmp_path,monkeypatch):
    import asyncio
    from test_frozen_writer import fixture
    from app.structured_writer import write_structured_preview
    from app.workflow import Dependencies
    store,template=fixture(tmp_path);state=store.get_task('r')
    state.metadata['writing_contract']={'groups':[{'id':'case','label':'关联正文','members':{'w1':'case','w2':'analysis'},'instruction':'同一案例','query':{'focus':'all','limit':10}}]}
    store.put_task(state,state.revision)
    monkeypatch.setattr('app.chart_spec.definitions',lambda template:[])
    calls=[]
    async def writer(catalog,payload,schema,ctx,**kwargs):
        calls.append(payload)
        assert set(payload['remaining_fields'])=={'w1','w2'}
        assert [f['id'] for f in payload['fields']]==['w1','w2']
        assert payload['writing_groups'][0]['members']=={'w1':'case','w2':'analysis'}
        assert {p['field'] for p in payload['template_parts'] if p.get('field')}=={'w1','w2'}
        return {'values':{key:{'value':'合成正文','source_refs':[state.fact_ref]} for key in payload['remaining_fields']}}
    monkeypatch.setattr('app.structured_writer.invoke_numbered_writer',writer)
    result=asyncio.run(write_structured_preview(Dependencies(store),'r',agents={'writer'}))
    assert len(calls)==1
    assert {'w1','w2'}<=store.get_artifact(result.draft_ref)['slot_values'].keys()


def test_contract_resolves_exact_template_and_returns_independent_snapshots(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from core.writing_contracts import resolve
    import yaml
    raw={'schema_version':1,'profiles':[{'template_refs':['confirmed-1'],'contract':contract()}]}
    (tmp_path/'writing_contracts.yaml').write_text(yaml.safe_dump(raw),encoding='utf-8')
    monkeypatch.setattr('core.packages.registry.load',lambda package:SimpleNamespace(directory=tmp_path))
    template={'fields':list(fields().values())}
    first=resolve(template,'client','confirmed-1')
    assert len(first['groups'])==1
    assert resolve(template,'client','confirmed-2')['groups']==[]
    raw['profiles'][0]['contract']['groups'][0]['instruction']='另一个要求'
    (tmp_path/'writing_contracts.yaml').write_text(yaml.safe_dump(raw),encoding='utf-8')
    second=resolve(template,'client','confirmed-1')
    assert first['groups'][0]['instruction']=='三段使用同一个案例'
    assert first['sha256']!=second['sha256']


def test_duplicate_event_titles_and_out_of_scope_media_examples_are_rejected():
    from core.writing_contracts import validate_group_answers
    ctx=[{'event_list_fields':['examples'],'allowed_event_titles':{'事件标题甲':'event-1','另一标题':'event-1'},'allowed_examples':{'media':['日报']}}]
    with pytest.raises(ValueError,match='重复举例'):
        validate_group_answers(ctx,{'examples':{'value':'事件标题甲”“另一标题'}})
    with pytest.raises(ValueError,match='机构列表'):
        validate_group_answers(ctx,{'media':{'value':'微博'}})


def test_group_request_preserves_strict_material_scope_on_empty_query(tmp_path,monkeypatch):
    import asyncio
    from test_frozen_writer import fixture
    from app.structured_writer import write_structured_preview
    from app.workflow import Dependencies
    store,_=fixture(tmp_path);state=store.get_task('r')
    state.metadata['writing_contract']={'groups':[{'id':'joint','label':'严格范围','members':{'w1':'topic','w2':'background'},'instruction':'同一主题','query':{'focus':'all','keyword':'不存在地域','sentiments':['正面'],'limit':10}}]}
    store.put_task(state,state.revision)
    monkeypatch.setattr('app.chart_spec.definitions',lambda template:[])
    calls=[]
    async def writer(*args,**kwargs):
        calls.append(args)
        pytest.fail('empty strict material scope must not call the writer')
    monkeypatch.setattr('app.structured_writer.invoke_numbered_writer',writer)
    result=asyncio.run(write_structured_preview(Dependencies(store),'r',agents={'writer'}))
    assert not calls
    assert any(i['error']=='writing_group_material_missing' for i in result.metadata['writer_issues'])


def test_adaptation_digest_includes_package_writing_contract(tmp_path):
    from types import SimpleNamespace
    from app.api_views.prompt_adaptation import package_digest
    package=SimpleNamespace(directory=tmp_path,prompt_bundle={})
    first=package_digest(package)
    (tmp_path/'writing_contracts.yaml').write_text('schema_version: 1\nprofiles: []\n',encoding='utf-8')
    assert package_digest(package)!=first


@pytest.mark.parametrize('initial_rules',[{},None])
def test_candidate_group_api_saves_and_rejects_missing_members(tmp_path,monkeypatch,initial_rules):
    from fastapi.testclient import TestClient
    import app.main as main
    from test_template_name_and_field_edit import _store,_create_task
    store,_=_store(tmp_path,monkeypatch)
    with TestClient(main.app) as client:
        task_id,state=_create_task(client,store)
        data=client.get(f'/api/templates/{task_id}/definition').json()
        fs=data['definition']['fields']
        writer=next(f['id'] for f in fs if f['owner']=='writer')
        # The tiny parser fixture has one field; add a second synthetic writer field.
        import copy
        from app.structured_template import _schema
        definition=store.get_artifact(state.metadata['structured_template_ref'])
        definition['rules']=initial_rules
        new=copy.deepcopy(fs[0]);new['id']='related_background';new['owner']='writer'
        definition['fields'].append(new)
        definition['blocks'].append({'index':999,'kind':'paragraph','parts':[{'field':new['id']}]})
        definition['output_schema']=_schema(definition['fields']);definition['writer_schema']=_schema(definition['fields'],True)
        state=store.get_task(task_id);state.metadata['structured_template_ref']=store.put_artifact(task_id,'structured_template_candidate',definition);store.put_task(state,state.revision)
        data=client.get(f'/api/templates/{task_id}/definition').json()
        other=new['id']
        groups=[{'id':'related','label':'关联组','members':{writer:'topic',other:'data'},'instruction':'共同上下文'}]
        response=client.put(f'/api/templates/{task_id}/definition',json={'expected_revision':data['revision'],'writing_groups':groups})
        assert response.status_code==200,response.text
        updated=response.json()
        assert updated['writing_contract']['groups'][0]['members']==groups[0]['members']
        assert 'confirmed_template_ref' not in store.get_task(task_id).metadata
        groups[0]['members']['nonexistent']='background'
        response=client.put(f'/api/templates/{task_id}/definition',json={'expected_revision':updated['revision'],'writing_groups':groups})
        assert response.status_code==422
