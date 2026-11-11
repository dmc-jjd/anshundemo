from __future__ import annotations
import asyncio,zipfile
from pathlib import Path
import pytest
from pydantic import ValidationError
from app.schemas import DraftVersion,TaskState,HumanDecision,ToolCall
from app.storage import Store,ConflictError
from app.tool_executor import RunContext,execute_tool
from app.tool import propose_keyword_event_candidates,propose_vector_event_neighbors,calculate_metrics,cluster_event_themes,classify_records,render_chart
from app.workflow import _args_for,Dependencies,run_report_graph
from app.template_compare import parse_report_document,compare_reports
from app.ooxml import UnreadableDocument
from app.model_client import invoke_agent,ModelUnavailable
from app.schemas import ToolDecision
from app.report_validation import validate_draft,apply_writer_patch

def fixture_store(tmp_path,records):
    s=Store(tmp_path); t=TaskState(id='t1',kind='report',phase='processing'); s.put_task(t)
    ref=s.put_artifact('t1','records',{'records':records})
    return s,RunContext(s,'t1'),ref

def rec(i,title,day):
    return {'id':str(i),'title':title,'summary':'','published':day,'source_ref':{'file_hash':'f','sheet':'s','row':i},'sentiment':'负面','platform':'网站'}

def test_five_recommendation_limit():
    DraftVersion(id='d',fact_ref='f',template_ref='t',recommendations=['x']*5)
    with pytest.raises(ValidationError): DraftVersion(id='d',fact_ref='f',template_ref='t',recommendations=['x']*6)
    assert not DraftVersion(id='d',fact_ref='f',template_ref='t').missing_recommendation_evidence
    assert DraftVersion(id='d',fact_ref='f',template_ref='t',missing_recommendation_evidence=True).missing_recommendation_evidence

def test_stale_decision_keeps_original(tmp_path):
    s=Store(tmp_path); t=TaskState(id='t',kind='report',phase='awaiting_review',review_items=[{'id':'q','status':'open','blocking':True}]); s.put_task(t)
    s.apply_decision('t',HumanDecision(item_id='q',expected_revision=0,action='exclude',reason='source invalid'))
    with pytest.raises(ConflictError): s.apply_decision('t',HumanDecision(item_id='q',expected_revision=0,action='confirm',reason='stale'))
    assert s.get_task('t').review_items[0]['decision']['action']=='exclude'

def test_follow_up_days_later_and_sources_survive(tmp_path):
    records=[rec(1,'安顺某桥梁施工封路引发拥堵','2026-10-01'),rec(2,'安顺某桥梁施工封路后续通行恢复','2026-10-05'),rec(3,'本地学校秋季运动会开幕','2026-10-05')]
    s,ctx,ref=fixture_store(tmp_path,records)
    first=propose_keyword_event_candidates({'records_ref':ref},ctx)
    second=propose_vector_event_neighbors({'keyword_candidates_ref':first.data_ref,'min_score':0.15},ctx)
    a=s.get_artifact(first.data_ref); b=s.get_artifact(second.data_ref)
    assert set(a['all_record_ids'])==set(b['all_record_ids'])=={'1','2','3'}
    assert all(r['source_ref']['row']==i+1 for i,r in enumerate(s.get_artifact(ref)['records']))
    assert any(set(x['record_ids'])=={'1','2'} for x in b['neighbors']) or any({'1','2'}<=set(g['member_ids']) for g in a['groups'])
    assert all(x['status']=='candidate' for x in b['neighbors'])
    assert 'confirmed_event_count' not in s.get_artifact(calculate_metrics({'records_ref':ref},ctx).data_ref)

def test_vector_prerequisite_and_frozen_mutation(tmp_path):
    s,ctx,ref=fixture_store(tmp_path,[rec(1,'test','2026-10-01')])
    result=asyncio.run(execute_tool(ToolCall(call_id='x',tool_name='propose_vector_event_neighbors'),ctx))
    assert result.error_code=='missing_keyword_candidates'
    t=s.get_task('t1'); t.fact_ref='facts-1'; s.put_task(t,t.revision)
    result=asyncio.run(execute_tool(ToolCall(call_id='y',tool_name='calculate_metrics',arguments={'records_ref':ref}),ctx))
    assert result.error_code=='frozen_facts'

def test_corrupt_docx_explicit(tmp_path):
    p=tmp_path/'bad.docx'; p.write_bytes(b'not a docx')
    with pytest.raises(UnreadableDocument,match='unreadable_document'): parse_report_document(str(p))

def test_inserted_paragraph_preserves_exact_alignment(tmp_path):
    a={'path':'a','sha256':'a','blocks':[{'index':0,'text':'第一节'},{'index':1,'text':'固定段落'},{'index':2,'text':'结尾'}]}
    b={'path':'b','sha256':'b','blocks':[{'index':0,'text':'第一节'},{'index':1,'text':'插入文字'},{'index':2,'text':'固定段落'},{'index':3,'text':'结尾'}]}
    c=compare_reports([a,b]); assert any(x['type']=='equal' and 2 in x['base_blocks'] and 3 in x['other_blocks'] for x in c['alignments'])

def test_vector_search_bounded(tmp_path):
    records=[rec(i,f'安顺事件{i%35}进展报道第{i}次','2026-10-01') for i in range(200)]
    s,ctx,ref=fixture_store(tmp_path,records)
    first=propose_keyword_event_candidates({'records_ref':ref},ctx)
    second=propose_vector_event_neighbors({'keyword_candidates_ref':first.data_ref},ctx)
    method=s.get_artifact(second.data_ref)['method']
    assert method['evaluated_pairs']<len(records)*(len(records)-1)//2

def test_blank_source_category_remains_blank_and_cluster_is_candidate(tmp_path):
    records=[{**rec(1,'黄果树景区游客排队','2026-10-01'),'category':''},{**rec(2,'学校食堂收费争议','2026-10-02'),'category':''}]
    s,ctx,ref=fixture_store(tmp_path,records)
    field=classify_records({'records_ref':ref},ctx)
    assert field.status=='needs_review'
    assert all(x['category'] is None for x in s.get_artifact(field.data_ref)['items'])
    out=cluster_event_themes({'records_ref':ref},ctx); data=s.get_artifact(out.data_ref)
    assert out.status=='needs_review'
    assert set(data['all_record_ids'])=={'1','2'}
    assert all(x['source_ref']['row'] in (1,2) and x['status']=='candidate' for x in data['items'])

def test_event_group_decision_requires_complete_nonoverlapping_members(tmp_path):
    records=[rec(1,'甲','2026-10-01'),rec(2,'乙','2026-10-02')]
    s,ctx,ref=fixture_store(tmp_path,records)
    first=propose_keyword_event_candidates({'records_ref':ref},ctx)
    second=propose_vector_event_neighbors({'keyword_candidates_ref':first.data_ref},ctx)
    t=s.get_task('t1'); t.phase='awaiting_review'; t.review_items=[{'id':'q','kind':'event_groups','status':'open','blocking':True,'details':{'keyword_ref':first.data_ref,'vector_ref':second.data_ref}}]; s.put_task(t,t.revision)
    revision=s.get_task('t1').revision
    with pytest.raises(ValueError,match='cover_all'):
        s.apply_decision('t1',HumanDecision(item_id='q',expected_revision=revision,action='merge',reason='test',payload={'groups':[{'member_ids':['1']}] }))
    assert s.get_task('t1').revision==revision
    result=s.apply_decision('t1',HumanDecision(item_id='q',expected_revision=revision,action='merge',reason='same event verified',payload={'groups':[{'member_ids':['1','2']}] }))
    confirmed=s.get_artifact(result.result_refs['confirmed_event_groups'])
    assert confirmed['groups'][0]['member_ids']==['1','2']

def test_template_has_definitions_before_source_body():
    import json
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'templates/anshun-colored/report.template.json').read_text(encoding='utf-8'))
    from app.ooxml import read_docx
    doc=read_docx(root/'templates/anshun-colored/template-with-placeholders.docx')
    assert len(manifest['placeholders'])==99
    assert doc['blocks'][0]['text'].startswith('占位符定义')
    assert any('一、涉安信息传播态势' in b['text'] for b in doc['blocks'][100:])
    assert len([b for b in doc['blocks'] if b['kind']=='table'])==1
    assert {s['slot_type'] for s in manifest['placeholders'] if s['id'] in ('B30_RED_02','B30_RED_05')}=={'computed_judgement','narrative_from_sources'}

def test_fake_model_is_explicitly_marked_synthetic(tmp_path):
    s,ctx,ref=fixture_store(tmp_path,[rec(1,'甲','2026-10-01')])
    async def fake(role,payload): return {'action':'call_tool','tool_name':'calculate_metrics','arguments':{'records_ref':ref},'reason':'test'}
    ctx.model_adapter=fake
    decision=asyncio.run(invoke_agent('data_processor',{'goal':'counts'},ToolDecision,ctx))
    assert decision.tool_name=='calculate_metrics'
    assert s.events('t1')[-1]['status']=='synthetic_test'

def test_event_scope_has_no_implicit_intersection(tmp_path):
    s,ctx,ref=fixture_store(tmp_path,[rec(1,'景区游客','2026-10-01')])
    t=s.get_task('t1'); t.result_refs={'import_records':ref,'filter_records:negative':ref,'filter_records:warning':ref,'filter_records:negative_warning':ref}
    with pytest.raises(KeyError,match='event scope not confirmed'): _args_for('propose_keyword_event_candidates',t)
    t.metadata['event_scope']='negative'; assert _args_for('propose_keyword_event_candidates',t)['records_ref']==ref

def test_chart_result_is_png_with_explicit_source(tmp_path):
    s,ctx,ref=fixture_store(tmp_path,[rec(1,'甲','2026-10-01'),rec(2,'乙','2026-10-02')])
    metrics=calculate_metrics({'records_ref':ref},ctx)
    chart=render_chart({'chart_type':'sentiment','metrics_ref':metrics.data_ref},ctx)
    import base64
    data=s.get_artifact(chart.data_ref)
    assert chart.status=='ok' and data['metrics_ref']==metrics.data_ref
    assert base64.b64decode(data['png_base64']).startswith(b'\x89PNG')

def test_dynamic_planner_receives_each_template_slot_and_does_not_fallback(tmp_path):
    s=Store(tmp_path); ref=s.put_artifact('dynamic','seed',{'records':[],'groups':[],'all_record_ids':[]})
    group_ref=s.put_artifact('dynamic','automatic_event_groups',{'groups':[],'all_record_ids':[],'source_records_ref':ref,'borderline_candidates':[]})
    keys=['import_records','calculate_metrics','filter_records:positive','filter_records:neutral','filter_records:negative','filter_records:warning','filter_records:negative_or_warning','group_events','cluster_event_themes']
    state=TaskState(id='dynamic',kind='report',phase='queued',result_refs={**{k:ref for k in keys},'group_events':group_ref},metadata={'mode':'dynamic','event_scope':'negative_or_warning'})
    s.put_task(state); captured={}
    async def fake(role,payload):
        captured.update(payload)
        return {'action':'finish_processing','reason':'all goals supplied'}
    graph_result=asyncio.run(run_report_graph(Dependencies(s,fake),'dynamic'))
    result=s.get_task('dynamic')
    assert len(captured['slot_goals'])==99
    assert captured['confirmed_scope_requirements']['B30_categories_districts_top10'].startswith('用户确认')
    assert result.fallback is None
    assert graph_result['phase']=='awaiting_review'
    assert [x['kind'] for x in result.review_items if x['blocking']]==['data_review']

def test_draft_invalid_source_and_locked_count_are_blocked():
    draft=DraftVersion(id='d',fact_ref='facts',template_ref='template',sections=[{'text':'原始记录 6 条','locked':True},{'text':'有来源的分析','locked':False,'source_refs':['evidence']}],source_refs=['nonexistent'])
    issues=validate_draft(draft,{'artifact_ref':'facts','input_refs':['file'],'result_refs':{'evidence':'evidence'}})
    assert any(x.field_id=='source_refs' and x.severity=='blocking' for x in issues)
    with pytest.raises(ValueError,match='locked_field'): apply_writer_patch(draft,{0:'原始记录 7 条'},{0})


def test_empty_recommendations_distinguish_research_and_writer_pending():
    facts={'artifact_ref':'facts','input_refs':[],'result_refs':{}}
    research=DraftVersion(id='research',fact_ref='facts',template_ref='t',missing_recommendation_evidence=True)
    writing=DraftVersion(id='writing',fact_ref='facts',template_ref='t')
    research_issue=next(issue for issue in validate_draft(research,facts) if issue.field_id=='recommendations')
    writing_issue=next(issue for issue in validate_draft(writing,facts) if issue.field_id=='recommendations')
    assert '研究依据不足' in research_issue.description
    assert '写作/校验未完成' in writing_issue.description and '转人工' in writing_issue.description

