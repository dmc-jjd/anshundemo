import asyncio,copy,json
import pytest
from app.workflow import Dependencies,build_writing_graph,run_writing_graph
from app.structured_writer import save_draft
from app.reviewers import review_ready,resolve_human_review
from app.writing_review import edit_structured
from test_frozen_writer import fixture

def seeded(tmp_path,human=False):
    store,template=fixture(tmp_path);state=store.get_task('r')
    values={'b17_warning_count':{'value':'2','source_refs':[state.fact_ref]},'b5_issue_no':{'value':'10','source_refs':[state.fact_ref]},
        'w1':{'value':'这一判断基于季节机制的推演，相关风险可能增加。','source_refs':[state.fact_ref]},
        'w2':{'value':'人工已确认的私有原文不可再次发给模型' if human else '其他机器正文','source_refs':['human_edit'] if human else [state.fact_ref]}}
    state=save_draft(store,state,template,values,{state.fact_ref,'human_edit'},{},[])
    return store,template,state

def clean_review(payload):
    return {'summary':'已按提供的事实与规则检查。','issues':[],'semantic_judgments':[{'candidate_id':c['candidate_id'],'label':c['allowed_labels'][-1],'confidence':'low','reason':'示例未满足明确命中判据。'} for c in payload.get('style',{}).get('semantic_candidates',[])]}

def test_actual_graph_has_distinct_reviews_and_records_real_node_execution(tmp_path):
    store,template,state=seeded(tmp_path);calls=[]
    async def adapter(role,payload):calls.append(role);return clean_review(payload)
    graph=build_writing_graph(Dependencies(store,adapter),review_only=True)
    assert {'write_draft','format_review','content_review','revise_draft','await_final_review'}<=set(graph.get_graph().nodes)
    result=asyncio.run(run_writing_graph(Dependencies(store,adapter),'r',review_only=True))
    assert calls==['format_reviewer','content_reviewer']
    nodes=[e['node'] for e in store.events('r') if e['type']=='graph_node' and e['status']=='started']
    assert nodes==['validate_input','local_validation','style_detection','format_review','content_review','final_format_review','await_final_review']
    assert result.phase=='awaiting_final_review' and review_ready(result,store.get_artifact(result.draft_ref)['content_hash'])

def test_final_format_review_never_loops_back_to_revision(tmp_path):
    store,_,_=seeded(tmp_path)
    graph=build_writing_graph(Dependencies(store),review_only=True)
    edges=graph.get_graph().edges
    assert {e.target for e in edges if e.source=='final_format_review'}=={'await_final_review'}

def test_repair_loop_preserves_facts_data_and_human_fields(tmp_path):
    store,template,state=seeded(tmp_path,True);fact=store.get_artifact(state.fact_ref);before=store.get_artifact(state.draft_ref);calls=[]
    async def adapter(role,payload):
        assert '人工已确认的私有原文' not in json.dumps(payload,ensure_ascii=False)
        calls.append(role)
        if role=='writer':
            field=payload['editable_fields'][0];return {'patches':[{'field_id':field['id'],'before':field['value'],'after':'气温变化时相关风险可能增加，应提前排查隐患。','issue_ids':[payload['issues'][0]['id']],'source_refs':field['source_refs']}]}
        answer=clean_review(payload)
        if role=='content_reviewer' and '这一判断' in payload['fields'][0]['value']:
            answer['issues']=[{'field_id':'w1','kind':'meta_text','severity':'blocking','quote':'这一判断基于季节机制的推演，','description':'方法说明混入正文。','suggestion':'直接写条件与风险，保留可能。','action':'revise'}]
        return answer
    state=asyncio.run(run_writing_graph(Dependencies(store,adapter),'r',True));draft=store.get_artifact(state.draft_ref)
    assert calls==['format_reviewer','content_reviewer','writer','content_reviewer','format_reviewer']
    assert store.get_artifact(state.fact_ref)==fact and draft['slot_values']['b17_warning_count']==before['slot_values']['b17_warning_count']
    assert draft['slot_values']['w2']==before['slot_values']['w2']
    assert state.metadata['writing_review_run']['round']==2 and review_ready(state,draft['content_hash'])
    count=len(calls);edit_structured(store,'r',{'w1':'人工终审后确认的正文'},draft['content_hash'])
    state=store.get_task('r');assert len(calls)==count and review_ready(state,store.get_artifact(state.draft_ref)['content_hash'])

def test_five_review_rounds_then_human_is_final_without_model_reentry(tmp_path):
    store,template,state=seeded(tmp_path);calls=[]
    async def adapter(role,payload):
        calls.append(role)
        if role=='writer':
            f=payload['editable_fields'][0];return {'patches':[{'field_id':f['id'],'before':f['value'],'after':f['value']+'待复核。','issue_ids':[i['id'] for i in payload['issues']],'source_refs':f['source_refs']}]}
        reply=clean_review(payload)
        if role=='content_reviewer':reply['issues']=[{'field_id':'w1','kind':'logic','severity':'blocking','quote':payload['fields'][0]['value'],'description':'测试中的逻辑问题仍未解除。','suggestion':'补足条件与影响关系。','action':'revise'}]
        return reply
    state=asyncio.run(run_writing_graph(Dependencies(store,adapter),'r',True))
    assert state.metadata['writing_review_run']['round']==5 and calls.count('writer')==4
    draft=store.get_artifact(state.draft_ref);assert not review_ready(state,draft['content_hash'])
    count=len(calls);state=asyncio.run(run_writing_graph(Dependencies(store,adapter),'r',True));assert len(calls)==count
    issues=[i['id'] for i in state.review_items if i['kind']=='writing_review' and i['status']=='open']
    resolve_human_review(store,'r',draft['content_hash'],issues,'已在最终人工审核中逐项核对并确认保留。')
    state=store.get_task('r');assert review_ready(state,draft['content_hash']) and len(calls)==count

def test_reviewer_failure_is_visible_and_cannot_silently_pass(tmp_path):
    store,_,_=seeded(tmp_path)
    async def failure(*args):raise RuntimeError('test provider unavailable')
    state=asyncio.run(run_writing_graph(Dependencies(store,failure),'r',True))
    assert all(v['status']=='error' for v in state.metadata['review_report']['reviewers'].values())
    assert not review_ready(state,store.get_artifact(state.draft_ref)['content_hash'])
    assert set(state.metadata['review_report']['reviewers'])=={'format_reviewer','content_reviewer'}
    assert state.metadata['writing_review_run']['format_limit_reached'] is True
    assert state.metadata['writing_review_run']['blocked_at']=='final_review'
    assert len([i for i in state.review_items if i['kind']=='writing_review' and i['blocking'] and i['status']=='open'])==2

def test_style_skill_runs_real_upstream_detection_and_keeps_closed_labels(tmp_path):
    from app.style_skill import detect_style,skill_context
    from app.reviewers import numbers
    assert numbers('从十月份看，涉及2条')==numbers('从10月份看，涉及2条')
    assert numbers('从十月份看，涉及2条')!=numbers('从10月份看，涉及3条')
    store,template,state=seeded(tmp_path)
    template['fields'][1].update(kind='analysis',display_name='研判分析')
    draft=store.get_artifact(state.draft_ref)
    draft['slot_values']['w1']['value']='这一判断基于季节机制和地形条件推演，已有资料仅作背景参考。风险可能增加。'
    _,report=detect_style(store,'r',draft,template['fields'])
    assert report['skill']['commit']==skill_context()['commit'] and 'density' in report['metrics']
    assert report['project_findings'] and report['semantic_candidates']

def test_review_context_has_rendered_template_but_never_reopens_human_or_data(tmp_path):
    from app.reviewers import begin_run,payload_for
    store,template,state=seeded(tmp_path,True);begin_run(store,'r',True)
    _,_,machine,payload,_=payload_for(store,store.get_task('r'),'format_reviewer')
    assert set(machine)=={'w1'} and payload['fields'][0]['text']==payload['fields'][0]['value']
    assert payload['template_layout'][0]['rendered_text']==machine['w1']['value']
    assert '人工已确认的私有原文' not in json.dumps(payload,ensure_ascii=False)

def test_review_collects_all_contract_errors_and_resolves_exact_quote_anchor(tmp_path):
    from app.reviewers import begin_run,run_reviewer
    store,_,_=seeded(tmp_path);begin_run(store,'r',True);calls=[]
    async def adapter(role,payload):
        calls.append(payload);answer=clean_review(payload)
        if len(calls)==1:
            answer['issues']=[{'field_id':'b17_warning_count','kind':'fact','quote':'拼接……原句','description':'测试：不应重开只读字段。','suggestion':'仅审查可编辑机器字段。','evidence_refs':['invented_reference']},
                {'field_id':'w1','kind':'logic','quote':'拼接……原句','description':'测试：引文必须准确定位。','suggestion':'使用原句编号进行定位。'}]
        else:
            anchor=payload['quote_catalog'][0]
            assert len(payload['correction_errors'])==2  # quote 已由程序自动定位，不再计入合同错误（只剩 field_id + evidence_refs）
            answer['issues']=[{'field_id':anchor['field_id'],'quote_id':anchor['id'],'kind':'logic','action':'report_only','description':'测试：按原句编号核查。','suggestion':'核对后保留当前表述。'}]
        return answer
    state=asyncio.run(run_reviewer(Dependencies(store,adapter),'r','format_reviewer'))
    issue=next(i for i in state.review_items if i['kind']=='writing_review' and i['status']=='open')
    assert issue['details']['quote']==calls[-1]['quote_catalog'][0]['text']
    assert len(calls)==2 and state.metadata['review_report']['reviewers']['format_reviewer']['status']=='issues'

def test_invalid_content_repair_gets_next_review_and_error_feedback_within_stage_budget(tmp_path):
    store,_,_=seeded(tmp_path);calls=[];repairs=0
    async def adapter(role,payload):
        nonlocal repairs
        calls.append(role)
        if role=='writer':
            repairs+=1;f=payload['editable_fields'][0]
            if repairs==2:assert payload['correction_errors'] and f['value_schema']['minLength']==1
            return {'patches':[{'field_id':f['id'],'before':f['value'],'after':'' if repairs==1 else '已按证据补足的可能风险与干预条件。','issue_ids':[payload['issues'][0]['id']],'source_refs':f['source_refs']}]}
        answer=clean_review(payload)
        if role=='content_reviewer' and repairs<2:answer['issues']=[{'field_id':'w1','kind':'logic','quote':payload['fields'][0]['value'],'description':'该处需要补足条件。','suggestion':'保留原有不确定性，补足条件。','action':'revise'}]
        return answer
    state=asyncio.run(run_writing_graph(Dependencies(store,adapter),'r',True))
    assert repairs==2 and calls==['format_reviewer','content_reviewer','writer','writer','content_reviewer','format_reviewer']
    assert state.metadata['writing_review_run']['stage_rounds']['content_reviewer']==2
    assert state.metadata['writing_review_run']['round']==2 and 'repair_error' not in state.metadata['writing_review_run']
    assert review_ready(state,store.get_artifact(state.draft_ref)['content_hash'])

def test_format_loop_then_content_loop_then_final_format_check(tmp_path):
    store,_,_=seeded(tmp_path);calls=[]
    async def adapter(role,payload):
        calls.append(role)
        if role=='writer':
            f=payload['editable_fields'][0];value='格式已修正，相关风险可能增加。' if payload['issues'][0]['kind']=='format' else '格式与事实均已核验，相关风险可能增加。'
            return {'patches':[{'field_id':f['id'],'before':f['value'],'after':value,'issue_ids':[payload['issues'][0]['id']],'source_refs':f['source_refs']}]}
        answer=clean_review(payload);value=payload['fields'][0]['value']
        if role=='format_reviewer' and not value.startswith('格式'):
            answer['issues']=[{'field_id':'w1','kind':'format','quote':value,'description':'格式需要先修正。','suggestion':'先完成本期格式修正。','action':'revise'}]
        if role=='content_reviewer':
            assert value.startswith('格式')
            if not value.startswith('格式与事实'):answer['issues']=[{'field_id':'w1','kind':'fact','quote':value,'description':'格式已过，事实还需修正。','suggestion':'按已经确认的事实修正。','action':'revise'}]
        return answer
    state=asyncio.run(run_writing_graph(Dependencies(store,adapter),'r',True))
    assert calls==['format_reviewer','writer','format_reviewer','content_reviewer','writer','content_reviewer','format_reviewer']
    assert state.metadata['writing_review_run']['round']==3 and review_ready(state,store.get_artifact(state.draft_ref)['content_hash'])

def test_unresolved_format_only_dispatches_content_after_limit_and_keeps_findings(tmp_path):
    store,_,_=seeded(tmp_path);calls=[]
    async def adapter(role,payload):
        calls.append(role)
        if role=='writer':
            f=payload['editable_fields'][0];return {'patches':[{'field_id':f['id'],'before':f['value'],'after':f['value']+'待复核。','issue_ids':[payload['issues'][0]['id']],'source_refs':f['source_refs']}]}
        answer=clean_review(payload)
        if role=='format_reviewer':answer['issues']=[{'field_id':'w1','kind':'format','quote':payload['fields'][0]['value'],'description':'格式始终未通过。','suggestion':'按本期规则修正格式。','action':'revise'}]
        return answer
    state=asyncio.run(run_writing_graph(Dependencies(store,adapter),'r',True))
    assert calls==['format_reviewer','writer']*5+['format_reviewer','content_reviewer']
    assert 'content_reviewer' in state.metadata['review_report']['reviewers']
    assert state.metadata['writing_review_run']['format_limit_reached'] is True
    assert state.metadata['writing_review_run']['blocked_at']=='final_review'
    assert any(i['kind']=='writing_review' and i['reviewer']=='format_reviewer' and i['status']=='open' and i['blocking'] for i in state.review_items)
    assert not review_ready(state,store.get_artifact(state.draft_ref)['content_hash'])

def test_invalid_format_repairs_also_forward_to_content_after_limit(tmp_path):
    store,_,_=seeded(tmp_path);calls=[]
    async def adapter(role,payload):
        calls.append(role)
        if role=='writer':return {'patches':[]}
        answer=clean_review(payload)
        if role=='format_reviewer':answer['issues']=[{'field_id':'w1','kind':'format','quote':payload['fields'][0]['value'],'description':'格式问题仍未修正。','suggestion':'保留问题到终稿人审。','action':'revise'}]
        return answer
    state=asyncio.run(run_writing_graph(Dependencies(store,adapter),'r',True))
    assert calls==['format_reviewer','writer','content_reviewer']
    assert state.metadata['writing_review_run']['format_limit_reached'] and state.metadata['writing_review_run']['blocked_at']=='final_review'
    assert state.metadata['review_report']['reviewers']['content_reviewer']['model_called'] is True
    assert not review_ready(state,store.get_artifact(state.draft_ref)['content_hash'])

def test_review_repairs_cannot_exceed_analysis_length_even_with_loose_template(tmp_path):
    store,template,state=seeded(tmp_path)
    template=copy.deepcopy(template);next(f for f in template['fields'] if f['id']=='w1')['display_name']='研判分析'
    state.template_ref=store.put_artifact('r','template',template);store.put_task(state,state.revision)
    values=store.get_artifact(state.draft_ref)['slot_values'];values['w1']['value']='若隐患未及时化解，相关风险可能扩大。'*20
    state=save_draft(store,state,template,values,{state.fact_ref,'human_edit'},{},[]);before=values['w1']['value'];attempts=[]
    async def adapter(role,payload):
        if role=='writer':
            attempts.append(payload);f=payload['editable_fields'][0]
            if len(attempts)==2:
                assert '300—500字' in payload['correction_errors'][0]
                return {'patches':[]}
            return {'patches':[{'field_id':'w1','before':f['value'],'after':'若'+'可能扩大风险。'*72,'issue_ids':[payload['issues'][0]['id']],'source_refs':f['source_refs']}]}
        answer=clean_review(payload)
        if role=='content_reviewer':answer['issues']=[{'field_id':'w1','kind':'logic','quote':payload['fields'][0]['value'],'description':'须保留条件并修订分析。','suggestion':'简洁说明风险与条件。','action':'revise'}]
        return answer
    state=asyncio.run(run_writing_graph(Dependencies(store,adapter),'r',True))
    assert len(attempts)==2 and store.get_artifact(state.draft_ref)['slot_values']['w1']['value']==before

def test_api_requires_reviews_then_human_resolution_and_edits_end_without_model(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main
    from app.workflow import Dependencies
    store,template,state=seeded(tmp_path);calls=[]
    from app.writer_tools import CHARTS,chart_payload
    from app.frozen_report import FrozenReport
    frozen=FrozenReport(store,'r')
    charts={key:store.put_artifact('r','writer_chart',chart_payload(frozen,key)) for key in CHARTS}
    before=store.get_artifact(state.draft_ref)
    save_draft(store,state,template,before['slot_values'],set(before['evidence_refs'])|set(charts.values()),charts,[])
    monkeypatch.setattr(main,'store',store);monkeypatch.setattr(main,'deps',Dependencies(store))
    # Isolate the review gate; chart/export correctness has separate real OOXML tests.
    monkeypatch.setattr(main,'export_docx',lambda *a,**k:b'validated elsewhere')
    monkeypatch.setattr(main,'validate_draft',lambda *a:[])
    client=TestClient(main.app);state=store.get_task('r');hash=store.get_artifact(state.draft_ref)['content_hash']
    assert client.post('/api/tasks/r/approve',json={'draft_hash':hash}).json()['detail']=='writing_review_required'
    async def adapter(role,payload):
        calls.append(role);answer=clean_review(payload)
        if role=='content_reviewer':answer['issues']=[{'field_id':'w1','kind':'logic','severity':'warning','quote':payload['fields'][0]['value'],'description':'需要人工保留的可选修订。','suggestion':'核查正文与本期口径。','action':'revise'}]
        if role=='writer':return {'patches':[]}
        return answer
    asyncio.run(run_writing_graph(Dependencies(store,adapter),'r',True))
    review=client.get('/api/tasks/r/writing-review').json();assert not review['ready'] and review['style_history']
    assert client.post('/api/tasks/r/approve',json={'draft_hash':hash}).status_code==409
    issues=[i['id'] for i in review['issues']];count=len(calls)
    assert client.post('/api/tasks/r/writing-review/resolve',json={'expected_hash':'stale','issue_ids':issues,'reason':'核查后保留当前内容。'}).status_code==409
    assert client.post('/api/tasks/r/writing-review/resolve',json={'expected_hash':hash,'issue_ids':issues,'reason':'核查后保留当前内容。'}).status_code==200
    assert client.post('/api/tasks/r/slot-values',json={'expected_hash':hash,'values':{'w1':'人工确认的最终正文'}}).status_code==200
    review=client.get('/api/tasks/r/writing-review').json();assert review['ready'] and len(calls)==count
    assert client.post('/api/tasks/r/approve',json={'draft_hash':review['draft_hash']}).status_code==200
