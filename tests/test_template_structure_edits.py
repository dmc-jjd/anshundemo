import copy
import pytest
from app.template_structure_edits import apply_structure_edits

def template():
    return {'fields':[{'id':'list','owner':'writer','kind':'paragraph_list','value_schema':{'type':'array','items':{'type':'string'},'minItems':4,'maxItems':6}}],
            'blocks':[{'index':0,'kind':'repeat','parts':[{'field':'list'}],'source_block_indexes':[0]}],
            'source_reports':[{'path':'source.docx','sha256':'abc'}]}

def test_edits_validate_sources_preserve_original_and_insert_optional_paragraph():
    original=template();before=copy.deepcopy(original)
    documents=[{'blocks':[{'index':0,'kind':'paragraph','text':'五是风险正文。'}]}]
    edits={'reason':'用户选择全部类别和独立第五段','field_updates':{'list':{'value_schema':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':12}}},
           'insertions':[{'after_index':0,'style_from_index':0,'source_report':0,'source_blocks':[0],'paragraphs':[{'prefix':'五是','field':{'id':'risk5','display_name':'第五条','semantic':'可选第五条风险','rule':'无第五项时省略'},'optional':True}]}]}
    result=apply_structure_edits(original,edits,documents)
    assert original==before
    assert result['fields'][0]['value_schema']['maxItems']==12
    assert result['blocks'][1]['optional'] is True
    assert result['blocks'][1]['parts']==[{'text':'五是'},{'field':'risk5'}]
    assert 'risk5' not in result['output_schema']['required']
    assert result['writer_schema']['properties']['risk5']['properties']['value']['minLength']==0
    edits['insertions'][0]['paragraphs'][0]['prefix']='伪造前缀'
    with pytest.raises(ValueError):apply_structure_edits(original,edits,documents)

def test_structure_edits_cannot_replace_bound_fields_or_use_unknown_sources():
    t=template();t['fields'][0]['owner']='data'
    with pytest.raises(ValueError):apply_structure_edits(t,{'reason':'测试','field_updates':{'list':{'semantic':'改成写手'}}},[])

def test_anchored_parts_binding_and_optional_group_are_validated():
    t=template();t['blocks'][0]={'index':0,'kind':'paragraph','parts':[{'text':'“'},{'field':'list'},{'text':'”'}]}
    result=apply_structure_edits(t,{'reason':'移除外引号','block_updates':[{'index':0,'expected_parts':t['blocks'][0]['parts'],'parts':[{'field':'list'}],'optional':True}],'field_updates':{'list':{'optional':True}}},[])
    assert result['blocks'][0]['render_rebuild'] and result['blocks'][0]['optional']
    assert 'list' not in result['output_schema']['required']
    with pytest.raises(ValueError,match='stale_structure_parts'):
        apply_structure_edits(t,{'reason':'过期','block_updates':[{'index':0,'expected_parts':[],'parts':[{'field':'list'}]}]},[])

def test_candidate_api_updates_schema_without_confirming_and_rejects_bad_sources(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main
    from test_template_name_and_field_edit import _store,_create_task
    store,_=_store(tmp_path,monkeypatch)
    with TestClient(main.app) as client:
        task_id,_=_create_task(client,store)
        url=f'/api/templates/{task_id}/definition'
        before=client.get(url).json()
        writer=next(f for f in before['definition']['fields'] if f['owner']=='writer')
        schema={**writer['value_schema'],'maxLength':5000}
        request={'expected_revision':before['revision'],'structural_changes':{'reason':'用户已决定调整字段长度','field_updates':{writer['id']:{'value_schema':schema}}}}
        response=client.put(url,json=request)
        assert response.status_code==200,response.text
        after=response.json()
        assert next(f for f in after['definition']['fields'] if f['id']==writer['id'])['value_schema']==schema
        assert not store.get_task(task_id).metadata.get('confirmed_template_ref')
        assert client.put(url,json=request).status_code==409
        request['expected_revision']=after['revision'];request['structural_changes']['insertions']=[{'after_index':0}]
        assert client.put(url,json=request).status_code==422
