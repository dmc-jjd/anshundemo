import asyncio
import copy
import pytest
from fastapi.testclient import TestClient
from app.schemas import TaskState
from app.storage import Store
from app.workflow import Dependencies,run_template
from app.template_compare import compare_reports
from app.template_review import make_input,compile_review
from app.structured_template import build_structured_template,render_structured_docx
from app.ooxml import read_docx
from test_structured_template import docx,semantic_analyst


def reports(tmp_path):
    return [docx(tmp_path/f'{i}.docx',text) for i,text in enumerate([
        '重点涉及交通管理、社会治理，网站、移动客户端传播。',
        '重点涉及交通管理、城市管理，网站、移动客户端传播。',
        '重点涉及市场监管、教育管理，短视频、微博传播。'])]


def test_three_reports_model_corrects_coincidental_fixed_words_and_word_output(tmp_path):
    docs=reports(tmp_path);local=build_structured_template(docs,'comparison')
    assert len(local['source_reports'])==3
    assert '交通管理' in ''.join(p.get('text','') for b in local['blocks'] for p in b['parts'])
    packet=make_input(docs,compare_reports(docs),local)
    result=asyncio.run(semantic_analyst('template_analyst',{**packet,'target_blocks':[0]}))
    template=compile_review(result,packet,'comparison')
    assert len(template['fields'][0]['sources'])==3
    assert not any(p.get('text') for b in template['blocks'] for p in b['parts'])
    path=tmp_path/'preview.docx'
    fid=template['fields'][0]['id']
    path.write_bytes(render_structured_docx(template,{fid:{'value':'本月主要涉及医疗服务，在短视频平台传播。','source_refs':['current']}},{'current'}))
    text=read_docx(path)['blocks'][0]['text']
    assert '交通管理' not in text and '网站' not in text and '医疗服务' in text


@pytest.mark.parametrize('corruption',['source','coverage','reconstruction','binding'])
def test_rejects_unverifiable_or_incomplete_model_template(tmp_path,corruption):
    docs=reports(tmp_path);packet=make_input(docs,compare_reports(docs),build_structured_template(docs,'x'))
    result=asyncio.run(semantic_analyst('template_analyst',{**packet,'target_blocks':[0]}))
    if corruption=='source':result['fields'][0]['sources'][0]['text']='伪造片段'
    if corruption=='coverage':
        result['fields'][0]['sources'].pop();result['blocks'][0]['sources'].pop()
    if corruption=='reconstruction':result['blocks'][0]['parts'].insert(0,{'text':'额外文字'})
    if corruption=='binding':result['fields'][0]['binding']={'tool':'calculate_metrics','path':['invented']}
    with pytest.raises(ValueError):compile_review(result,packet,'x')


def test_model_failure_and_weak_summary_block_confirmation_then_retry(tmp_path,monkeypatch):
    import app.main as main
    docs=reports(tmp_path);store=Store(tmp_path/'store')
    store.put_task(TaskState(id='t',kind='template',phase='queued',metadata={'paths':[d['path'] for d in docs]}))
    async def weak(role,payload):return {'summary':'只有摘要','source_files':[]}
    failed=asyncio.run(run_template(Dependencies(store,weak),'t'))
    assert failed.phase=='template_review_failed' and 'structured_template_ref' not in failed.metadata
    monkeypatch.setattr(main,'store',store)
    with TestClient(main.app) as client:
        rejected=client.post('/api/templates/t/confirm',json={'expected_revision':failed.revision,'candidate_ref':'old','reason':'test'})
        assert rejected.status_code==409
    ready=asyncio.run(run_template(Dependencies(store,semantic_analyst),'t'))
    assert ready.phase=='awaiting_template_confirmation',ready.metadata.get('template_error')
    assert len(store.get_artifact(ready.metadata['structured_template_ref'])['source_reports'])==3
    assert ready.metadata['template_validation_ref']


def test_upload_three_reports_rejects_duplicate_and_old_candidate_confirmation(tmp_path,monkeypatch):
    import app.main as main
    store=Store(tmp_path/'store');uploads=tmp_path/'uploads';uploads.mkdir()
    docs=reports(uploads)
    monkeypatch.setattr(main,'store',store);monkeypatch.setattr(main,'UPLOADS',uploads)
    monkeypatch.setattr(main,'deps',Dependencies(store,semantic_analyst))
    with TestClient(main.app) as client:
        assert client.post('/api/template-tasks',json={'file_ids':['0']}).status_code==422
        assert client.post('/api/template-tasks',json={'file_ids':['0','0','1']}).json()['detail']=='duplicate_reports'
        created=client.post('/api/template-tasks',json={'file_ids':['0','1','2']})
        assert created.status_code==200
        state=store.get_task(created.json()['id']);assert state.phase=='awaiting_template_confirmation'
        definition=client.get(f'/api/templates/{state.id}/definition').json()
        assert len(definition['definition']['source_reports'])==3 and definition['model_review_validated']
        request={'expected_revision':state.revision,'candidate_ref':'old','reason':'test','rules':{'event_threshold':.65,'first_warning_scope':'warning','ranking':'negative_warning_member_count'}}
        assert client.post(f'/api/templates/{state.id}/confirm',json=request).json()['detail']=='stale_template_candidate'
        request['candidate_ref']=definition['artifact_ref']
        changed=client.put(f'/api/templates/{state.id}/definition',json={'expected_revision':state.revision,'fields':{definition['definition']['fields'][0]['id']:{'display_name':'重点领域分析'}}}).json()
        assert client.post(f'/api/templates/{state.id}/confirm',json=request).status_code==409
        request.update(expected_revision=changed['revision'],candidate_ref=changed['artifact_ref'])
        assert client.post(f'/api/templates/{state.id}/confirm',json=request).status_code==200


def test_retry_reuses_only_validated_batches_and_keeps_all_report_context(tmp_path):
    docs=[docx(tmp_path/f'{i}.docx',f'报告{i}首段。</w:t></w:r></w:p><w:p><w:r><w:t>二段。</w:t></w:r></w:p><w:p><w:r><w:t>三段。</w:t></w:r></w:p><w:p><w:r><w:t>四段。') for i in range(3)]
    store=Store(tmp_path/'store');store.put_task(TaskState(id='t',kind='template',phase='queued',metadata={'paths':[d['path'] for d in docs]}))
    calls=[]
    async def fails_second(role,payload):
        calls.append(payload['target_blocks'])
        assert all(len(d['blocks'])==4 for d in payload['source_reports'])
        if payload['target_blocks']==[3]:raise TimeoutError('test timeout')
        return await semantic_analyst(role,payload)
    failed=asyncio.run(run_template(Dependencies(store,fails_second),'t'))
    assert failed.phase=='template_review_failed' and len(failed.metadata['template_review_checkpoints'])==1
    calls.clear()
    async def resume(role,payload):
        calls.append(payload['target_blocks']);return await semantic_analyst(role,payload)
    ready=asyncio.run(run_template(Dependencies(store,resume),'t'))
    assert ready.phase=='awaiting_template_confirmation',ready.metadata.get('template_error')
    assert calls==[[3]]


def test_business_question_has_visible_evidence_and_blocks_confirmation(tmp_path,monkeypatch):
    import app.main as main
    docs=reports(tmp_path);store=Store(tmp_path/'store')
    store.put_task(TaskState(id='t',kind='template',phase='queued',metadata={'paths':[d['path'] for d in docs]}))
    async def analyst(role,payload):
        result=await semantic_analyst(role,payload)
        result['unresolved_items']=[{'question':'是否保留第三份独有的分析内容？','reason':'历史口径存在差异','sources':[{'report_id':'r3','block':0}]}]
        return result
    state=asyncio.run(run_template(Dependencies(store,analyst),'t'))
    monkeypatch.setattr(main,'store',store)
    with TestClient(main.app) as client:
        definition=client.get('/api/templates/t/definition').json()
        q=definition['questions'][0]
        assert '短视频' in q['details']['sources'][0]['text']
        request={'expected_revision':state.revision,'candidate_ref':definition['artifact_ref'],'reason':'test','rules':{'event_threshold':.65,'first_warning_scope':'warning','ranking':'negative_warning_member_count'}}
        assert client.post('/api/templates/t/confirm',json=request).json()['detail']=='unresolved_template_review'
        request['resolutions']={q['id']:'根据本月数据决定具体风险分析。'}
        accepted=client.post('/api/templates/t/confirm',json=request)
        assert accepted.status_code==200
        template=store.get_artifact(accepted.json()['metadata']['confirmed_template_ref'])
        assert template['business_decisions'][0]['answer']==request['resolutions'][q['id']]


def test_platform_conclusion_cannot_remain_fixed_even_when_all_reports_agree(tmp_path):
    docs=[docx(tmp_path/f'{i}.docx',f'（二）从平台上看，{i}月在各大网站、移动客户端传播。') for i in range(3)]
    packet=make_input(docs,compare_reports(docs),build_structured_template(docs,'x'))
    result={'summary':'错误地保留平台名称','blocks':[{'index':0,'kind':'paragraph','purpose':'平台分析',
        'parts':[{'text':docs[0]['blocks'][0]['text']}],
        'sources':[{'report_id':d['id'],'block':0} for d in packet['source_reports']]}],
        'fields':[],'unresolved_items':[]}
    with pytest.raises(ValueError,match='monthly_platform_left_fixed'):compile_review(result,packet,'x')


def test_three_and_four_advice_sources_compile_variable_list_and_render_five(tmp_path):
    docs=[]
    for i,count in enumerate((3,3,4)):
        paragraphs=['（二）工作建议']+[f'{j}.报告{i}的历史建议{j}。' for j in range(1,count+1)]
        docs.append(docx(tmp_path/f'advice{i}.docx','</w:t></w:r></w:p><w:p><w:r><w:t>'.join(paragraphs)))
    packet=make_input(docs,compare_reports(docs),build_structured_template(docs,'x'))
    result=asyncio.run(semantic_analyst('template_analyst',{**packet,'target_blocks':[0,1,2,3]}))
    result['blocks'][-1]['sources'].append({'report_id':'r3','block':4})
    result['unresolved_items']=[{'question':'建议序号是否自动生成？','reason':'历史带编号','sources':[{'report_id':'r3','block':4}]}]
    template=compile_review(result,packet,'x')
    assert template['review_items']==[] and template['resolved_by_policy']
    repeat=next(b for b in template['blocks'] if b['kind']=='repeat')
    assert repeat['source_block_indexes']==[1,2,3]
    field=next(f for f in template['fields'] if f['id']=='monthly_recommendations')
    assert field['display_name']=='前瞻风险与工作建议（4—5类）' and '4至5类' in field['rule']
    assert field['value_schema']['minItems']==4 and field['value_schema']['maxItems']==5 and len(field['sources'])==10
    # Fill the heading field as well, so this checks only real rendered advice.
    values={f['id']:{'value':'（二）工作建议','source_refs':['current']} for f in template['fields'] if f['id']!='monthly_recommendations'}
    values['monthly_recommendations']={'value':[f'本月建议{j}。' for j in range(1,6)],'source_refs':['current']}
    path=tmp_path/'advice.docx';path.write_bytes(render_structured_docx(template,values,{'current'}))
    rendered=[b['text'] for b in read_docx(path)['blocks']]
    assert len(rendered)==6 and rendered[-1]=='5. 本月建议5。'
    assert not any('历史' in text for text in rendered)


def test_compiler_restores_original_connectors_without_changing_dynamic_boundary(tmp_path):
    docs=[docx(tmp_path/f'connector{i}.docx',f'{i}月：“事件甲”等。') for i in range(3)]
    packet=make_input(docs,compare_reports(docs),build_structured_template(docs,'x'))
    result=asyncio.run(semantic_analyst('template_analyst',{**packet,'target_blocks':[0]}))
    field=result['fields'][0]
    for source in field['sources']:source['text']='事件甲'
    result['blocks'][0]['parts']=[{'text':'0月：“'},{'field':field['id']},{'text':'”。'}]
    compiled=compile_review(result,packet,'x')
    assert compiled['blocks'][0]['parts'][-1]['text']=='”等。'
    assert compiled['blocks'][0]['parts'][1]=={'field':field['id']}
