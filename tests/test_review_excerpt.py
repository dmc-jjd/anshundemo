import copy
import pytest
from fastapi.testclient import TestClient
from app.structured_writer import save_draft
from app.structured_template import _schema
from app.reviewers import review_policy
from test_writing_graph import seeded


def fixture(tmp_path,monkeypatch):
    import app.main as main
    store,template,state=seeded(tmp_path)
    template=copy.deepcopy(template)
    next(f for f in template['fields'] if f['id']=='w2').update(kind='paragraph_list',value_schema={'type':'array','items':{'type':'string','minLength':1},'minItems':1,'maxItems':5})
    template['output_schema']=_schema(template['fields']);template['writer_schema']=_schema(template['fields'],True)
    state.template_ref=store.put_artifact('r','template',template);store.put_task(state,state.revision)
    values=store.get_artifact(state.draft_ref)['slot_values']
    values['w1']={'value':'前文保持。需要核对的原句。后文保持。','source_refs':[state.fact_ref]}
    values['w2']={'value':['第一条保持。','第二条原句甲。第二条原句乙。','第三条保持。'],'source_refs':[state.fact_ref]}
    state=save_draft(store,state,template,values,{state.fact_ref,'human_edit'},{},[])
    state.phase='awaiting_final_review';hash=store.get_artifact(state.draft_ref)['content_hash']
    state.metadata['review_report']={'draft_hash':hash,'profile':'anshun_monthly','policy_version':review_policy('anshun_monthly'),
        'reviewers':{role:{'status':'issues','draft_hash':hash} for role in ('format_reviewer','content_reviewer')}}
    state.metadata['writing_review_run']={'review_item_order':['keep','string','array-a','array-b']}
    for key,field,quote in [('keep','w1','前文保持。'),('string','w1','需要核对的原句。'),('array-a','w2','第二条原句甲。'),('array-b','w2','第二条原句乙。')]:
        state.review_items.append({'id':key,'kind':'writing_review','reviewer':'content_reviewer','status':'open','blocking':True,'draft_hash':hash,
            'details':{'field_id':field,'quote':quote,'description':'需要人工核查。','suggestion':'核对后保留或修改。','action':'revise'}})
    store.put_task(state,state.revision)
    monkeypatch.setattr(main,'store',store)
    return store,TestClient(main.app),hash,copy.deepcopy(values)


def test_retain_without_note_and_stable_numbers(tmp_path,monkeypatch):
    store,client,hash,before=fixture(tmp_path,monkeypatch)
    assert [i['number'] for i in client.get('/api/tasks/r/writing-review').json()['issues']]==[1,2,3,4]
    assert client.post('/api/tasks/r/writing-review/resolve',json={'expected_hash':hash,'issue_ids':['keep']}).status_code==200
    view=client.get('/api/tasks/r/writing-review').json()
    assert [i['number'] for i in view['issues']]==[2,3,4]
    state=store.get_task('r');assert store.get_artifact(state.draft_ref)['slot_values']==before
    assert next(i for i in state.review_items if i['id']=='keep')['decision']['reason']=='人工已核对，保留当前内容。'
    assert not any(e['type']=='model_call' for e in store.events('r'))


def test_resolved_final_issues_keep_original_and_suggestion_visible(tmp_path,monkeypatch):
    store,client,hash,_=fixture(tmp_path,monkeypatch)
    state=store.get_task('r')
    next(i for i in state.review_items if i['id']=='keep')['reviewer']='format_reviewer'
    store.put_task(state,state.revision)
    response=client.post('/api/tasks/r/writing-review/resolve',json={'expected_hash':hash,'issue_ids':['keep','string'],'reason':'人工已完成最终核查。'})
    assert response.status_code==200
    view=client.get('/api/tasks/r/writing-review').json()
    assert [i['id'] for i in view['issues']]==['array-a','array-b']
    history=view['resolved_issues']
    assert [(i['id'],i['reviewer']) for i in history]==[('keep','format_reviewer'),('string','content_reviewer')]
    assert all(i['status']=='resolved' for i in history)
    assert history[0]['details']['quote']=='前文保持。'
    assert history[0]['details']['suggestion']=='核对后保留或修改。'
    assert history[1]['details']['quote']=='需要核对的原句。'
    assert all(i['decision']['reason']=='人工已完成最终核查。' for i in history)


def test_inline_string_replaces_only_quote_and_only_resolves_selected_issue(tmp_path,monkeypatch):
    store,client,hash,before=fixture(tmp_path,monkeypatch)
    issue=next(i for i in client.get('/api/tasks/r/writing-review').json()['issues'] if i['id']=='string')
    response=client.post('/api/tasks/r/writing-review/string/edit',json={'expected_hash':hash,'replacement':'人工确认后的新句。','location':issue['locations'][0]})
    assert response.status_code==200,response.text
    state=store.get_task('r');draft=store.get_artifact(state.draft_ref)
    assert draft['slot_values']['w1']['value']=='前文保持。人工确认后的新句。后文保持。'
    assert draft['slot_values']['w1']['source_refs']==['human_edit']
    assert all(draft['slot_values'][k]==v for k,v in before.items() if k!='w1')
    assert next(i for i in state.review_items if i['id']=='string')['status']=='resolved'
    assert next(i for i in state.review_items if i['id']=='keep')['status']=='open'
    assert client.post('/api/tasks/r/writing-review/array-a/edit',json={'expected_hash':hash,'replacement':'错误旧稿提交。'}).status_code==409
    assert not any(e['type']=='model_call' for e in store.events('r'))


def test_array_quote_keeps_other_paragraphs_and_refreshes_next_location(tmp_path,monkeypatch):
    store,client,hash,before=fixture(tmp_path,monkeypatch)
    assert client.post('/api/tasks/r/writing-review/array-a/edit',json={'expected_hash':hash,'replacement':'第二条原句甲的人工终审版本。'}).status_code==200
    state=store.get_task('r');draft=store.get_artifact(state.draft_ref)
    assert draft['slot_values']['w2']['value']==['第一条保持。','第二条原句甲的人工终审版本。第二条原句乙。','第三条保持。']
    view=client.get('/api/tasks/r/writing-review').json();remaining=next(i for i in view['issues'] if i['id']=='array-b')
    assert remaining['number']==4 and remaining['locations'][0]['start']==len('第二条原句甲的人工终审版本。')
    assert client.post('/api/tasks/r/writing-review/array-b/edit',json={'expected_hash':view['draft_hash'],'replacement':'第二条原句乙的修订版。','location':remaining['locations'][0]}).status_code==200
    draft=store.get_artifact(store.get_task('r').draft_ref)
    assert draft['slot_values']['w2']['value']==['第一条保持。','第二条原句甲的人工终审版本。第二条原句乙的修订版。','第三条保持。']
    assert draft['slot_values']['b17_warning_count']==before['b17_warning_count']


def test_ambiguous_quote_requires_explicit_location(tmp_path,monkeypatch):
    store,client,hash,_=fixture(tmp_path,monkeypatch)
    state=store.get_task('r');draft=store.get_artifact(state.draft_ref);template=store.get_artifact(state.template_ref)
    values=draft['slot_values'];values['w1']['value']='需要核对的原句。中间保留。需要核对的原句。'
    state=save_draft(store,state,template,values,set(draft['evidence_refs']),{},[]);hash=store.get_artifact(state.draft_ref)['content_hash']
    issue=next(i for i in client.get('/api/tasks/r/writing-review').json()['issues'] if i['id']=='string');assert len(issue['locations'])==2
    request={'expected_hash':hash,'replacement':'替换后一处。'}
    assert client.post('/api/tasks/r/writing-review/string/edit',json=request).json()['detail']=='review_excerpt_location_required'
    request['location']=issue['locations'][1]
    assert client.post('/api/tasks/r/writing-review/string/edit',json=request).status_code==200
    assert store.get_artifact(store.get_task('r').draft_ref)['slot_values']['w1']['value']=='需要核对的原句。中间保留。替换后一处。'


@pytest.mark.parametrize('replacement,error',[('','review_excerpt_empty'),('需要核对的原句。','review_excerpt_unchanged_use_retain')])
def test_empty_and_unchanged_edits_do_not_write(tmp_path,monkeypatch,replacement,error):
    store,client,hash,before=fixture(tmp_path,monkeypatch)
    response=client.post('/api/tasks/r/writing-review/string/edit',json={'expected_hash':hash,'replacement':replacement})
    assert response.status_code==409 and response.json()['detail']==error
    assert store.get_artifact(store.get_task('r').draft_ref)['slot_values']==before
