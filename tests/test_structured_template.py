import asyncio,hashlib,io,zipfile
from pathlib import Path
import pytest
from jsonschema import ValidationError
from app.ooxml import read_docx
from app.template_compare import parse_report_document,compare_reports
from app.structured_template import build_structured_template,validate_values,render_structured_docx,load_confirmed_template,revise_candidate
from app.storage import Store
from app.schemas import TaskState
from app.workflow import Dependencies,run_template
from app.structured_writer import write_structured_preview

def docx(path,text):
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'+text+'</w:t></w:r></w:p></w:body></w:document>')
    return parse_report_document(str(path))

def pair(tmp_path):
    return [docx(tmp_path/'a.docx','共计100条，重点关注农业。'),docx(tmp_path/'b.docx','共计200条，重点关注教育。')]


async def semantic_analyst(role,payload):
    assert role=='template_analyst'
    assert payload['policy'] and payload['local_hypothesis'] and len(payload['source_reports'])>=2
    blocks=[];fields=[]
    for position,b in enumerate(payload['source_reports'][0]['blocks']):
        if b['index'] not in payload['target_blocks']:continue
        sources=[{'report_id':d['id'],'block':d['blocks'][position]['index']} for d in payload['source_reports']]
        fid=f'b{b["index"]}_analysis'
        blocks.append({'index':b['index'],'kind':'paragraph','purpose':'本月分析','parts':[{'field':fid}],'sources':sources})
        fields.append({'id':fid,'display_name':'本月分析','owner':'writer','kind':'analysis','source_type':'analysis',
            'semantic':'本月重点领域分析','rule':'只使用本月证据','format':'完整句子','missing_policy':'block','reason':'相同类别仍随月份变化','binding':None,
            'sources':[{**s,'text':d['blocks'][position]['text']} for s,d in zip(sources,payload['source_reports'])]})
    return {'summary':'按语义重划字段','blocks':blocks,'fields':fields,'unresolved_items':[]}

def test_two_reports_generate_schema_and_render_preserves_fixed_words(tmp_path):
    docs=pair(tmp_path);template=build_structured_template(docs,'comparison')
    numeric=next(f for f in template['fields'] if f['owner']=='data')
    text=next(f for f in template['fields'] if f['owner']=='writer')
    assert numeric['sources'][0]['text']=='100'
    assert numeric['sources'][1]['text']=='200'
    values={numeric['id']:{'value':'300','source_refs':['metrics']},text['id']:{'value':'医疗','source_refs':['r1']}}
    result=render_structured_docx(template,values,{'metrics','r1'})
    p=tmp_path/'result.docx';p.write_bytes(result)
    assert read_docx(p)['blocks'][0]['text']=='共计300条，重点关注医疗。'
    assert len(template['source_reports'])==2
    with pytest.raises(ValueError,match='two_distinct'):build_structured_template([docs[0],docs[0]],'x')
    with pytest.raises(ValueError,match='at_least_two'):build_structured_template(docs[:1],'x')

def test_render_replaces_split_runs_without_removing_fixed_formatting(tmp_path):
    from lxml import etree as ET
    docs=pair(tmp_path);path=tmp_path/'a.docx'
    with zipfile.ZipFile(path) as z:xml=z.read('word/document.xml').decode()
    xml=xml.replace('共计100条','共计1</w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>00条')
    with zipfile.ZipFile(path,'w') as z:z.writestr('word/document.xml',xml)
    docs[0]=parse_report_document(str(path));template=build_structured_template(docs,'comparison')
    values={f['id']:{'value':'300' if f['owner']=='data' else '医疗','source_refs':['r']} for f in template['fields']}
    out=tmp_path/'out.docx';out.write_bytes(render_structured_docx(template,values,{'r'}))
    assert read_docx(out)['blocks'][0]['text']=='共计300条，重点关注医疗。'
    with zipfile.ZipFile(out) as z:assert b'<w:b' in z.read('word/document.xml')

def test_schema_protects_fields_and_provenance(tmp_path):
    template=build_structured_template(pair(tmp_path),'comparison')
    numeric=next(f for f in template['fields'] if f['owner']=='data')
    text=next(f for f in template['fields'] if f['owner']=='writer')
    with pytest.raises(ValidationError):validate_values(template,{numeric['id']:{'value':'300','source_refs':['r1']}},{'r1'},True)
    with pytest.raises(ValidationError):validate_values(template,{'unknown':{'value':'x','source_refs':['r1']}},{'r1'})
    with pytest.raises(ValueError,match='source_ref'):validate_values(template,{text['id']:{'value':'x','source_refs':['invented']}},{'r1'},True)
    with pytest.raises(ValidationError):validate_values(template,{},set(),require_complete=True)

def test_template_workflow_retains_two_source_comparison_before_confirmation(tmp_path):
    docs=pair(tmp_path);store=Store(tmp_path/'store')
    store.put_task(TaskState(id='template',kind='template',phase='queued',metadata={'paths':[d['path'] for d in docs]}))
    result=asyncio.run(run_template(Dependencies(store,semantic_analyst),'template'))
    assert result.phase=='awaiting_template_confirmation'
    candidate=store.get_artifact(result.metadata['structured_template_ref'])
    assert candidate['comparison_ref']==result.metadata['comparison_ref']
    assert len(candidate['source_reports'])==2 and candidate['writer_schema']['additionalProperties'] is False
    with pytest.raises(ValueError):load_confirmed_template(store,result.metadata['structured_template_ref'])

def test_writer_uses_confirmed_schema_and_tools_own_numeric_slots(tmp_path):
    store=Store(tmp_path/'store');template=build_structured_template(pair(tmp_path),'comparison')
    numeric=next(f for f in template['fields'] if f['owner']=='data');numeric['binding']={'tool':'calculate_metrics','path':['record_count']}
    template['status']='confirmed_by_human';ref=store.put_artifact('t','template_version',template)
    records=store.put_artifact('t','records',{'records':[{'id':'r1','title':'医疗服务','source':'媒体','published':'2026-10-01'}]})
    metrics=store.put_artifact('t','metrics',{'record_count':300})
    fact=store.put_artifact('t','facts',{'metrics':{'record_count':300}})
    store.put_task(TaskState(id='t',kind='report',phase='facts_frozen',fact_ref=fact,template_ref=ref,result_refs={'import_records':records,'calculate_metrics':metrics}))
    async def writer(role,payload):
        assert role=='writer'
        keys=list(payload['output_values_schema']['properties'])
        assert numeric['id'] not in keys
        return {'values':{key:{'value':'医疗','source_refs':[payload['evidence'][0]['ref']]} for key in keys}}
    result=asyncio.run(write_structured_preview(Dependencies(store,writer),'t'))
    draft=store.get_artifact(result.draft_ref)
    assert draft['structured_template_ref']==ref
    assert draft['slot_values'][numeric['id']]['value']=='300'
    assert store.events('t')[-1]['missing']==[]
    assert draft['fact_ref']==fact
    assert result.metadata['missing_fields']==[]

def test_candidate_edits_keep_two_report_provenance_immutable(tmp_path):
    template=build_structured_template(pair(tmp_path),'comparison')
    field=template['fields'][0]
    changed=revise_candidate(template,{field['id']:{'semantic':'本月总记录数','binding':{'tool':'calculate_metrics','path':['record_count']}}})
    assert changed['fields'][0]['sources']==field['sources']
    assert changed['source_reports']==template['source_reports']
    assert changed['fields'][0]['binding']['path']==['record_count']
    assert template['fields'][0]['binding'] is None
    with pytest.raises(ValueError):revise_candidate(template,{field['id']:{'sources':[]}})
    with pytest.raises(ValueError):revise_candidate({**template,'status':'confirmed_by_human'},{})

def test_api_confirmation_keeps_schema_and_requires_template_selection(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main
    store=Store(tmp_path/'store');uploads=tmp_path/'uploads';uploads.mkdir()
    (uploads/'test.xlsx').write_bytes(b'not a readable workbook')
    docs=pair(tmp_path)
    store.put_task(TaskState(id='template',kind='template',phase='queued',metadata={'paths':[d['path'] for d in docs]}))
    task=asyncio.run(run_template(Dependencies(store,semantic_analyst),'template'))
    assert task.phase=='awaiting_template_confirmation',task.metadata.get('template_error')
    candidate=task.metadata['structured_template_ref'];template=store.get_artifact(candidate)
    monkeypatch.setattr(main,'store',store);monkeypatch.setattr(main,'deps',Dependencies(store));monkeypatch.setattr(main,'UPLOADS',uploads)
    with TestClient(main.app) as client:
        assert client.post('/api/report-tasks',json={'file_ids':['test']}).status_code==409
        assert client.post('/api/report-tasks',json={'file_ids':['test'],'template_ref':candidate}).status_code==409
        definition=client.get('/api/templates/template/definition').json()
        assert definition['definition']['source_reports']==template['source_reports']
        confirmed=client.post('/api/templates/template/confirm',json={'expected_revision':task.revision,'candidate_ref':candidate,'reason':'test explicit human review','rules':{'event_threshold':.65,'first_warning_scope':'negative_or_warning','ranking':'negative_warning_member_count'}})
        assert confirmed.status_code==200
        ref=confirmed.json()['metadata']['confirmed_template_ref']
        assert load_confirmed_template(store,ref)['writer_schema']==template['writer_schema']
        assert client.put('/api/templates/template/definition',json={'expected_revision':confirmed.json()['revision'],'fields':{}}).status_code==409
        assert any(t['id']==ref for t in client.get('/api/templates').json())
