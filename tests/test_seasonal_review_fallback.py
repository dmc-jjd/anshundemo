import asyncio,copy
from app.section_two import HistoryTopic,HistoricalResearch,validate_history,forecast_window,seasonal_knowledge_usable
from app.historical_research import prepare_history
from app.frozen_report import FrozenReport
from app.tool_executor import RunContext
from app.workflow import Dependencies,run_writing_graph
from app.structured_writer import save_draft
from test_frozen_writer import fixture
from test_writing_graph import seeded,clean_review


def test_unreadable_history_can_use_independent_seasonal_knowledge(tmp_path):
    store,_=fixture(tmp_path);window=forecast_window(FrozenReport(store,'r'))
    page=store.put_artifact('r','historical_page',{'url':'https://example.test/a','content':'','published_at':'2025-11-01'})
    topic=HistoryTopic(candidate_id='c1',category='冬季取暖安全',basis_type='historical',applies_to_months=[11,12],
        knowledge_basis='若入冬后室内使用炭火而通风不足，可能积聚一氧化碳，宜提前检查取暖设施与通风条件。',
        rationale='围绕未来两个月的季节触发条件开展前瞻分析。'*30,
        evidence=[{'page_ref':page,'period':'2025-11','quote':'安顺市发布冬季取暖安全风险提示，提醒提前检查隐患。','location_quote':'安顺市','basis':'historical_case'}])
    topics,errors=validate_history(HistoricalResearch(topics=[topic]),store,'r',window)
    assert len(topics)==1 and topics[0]['basis_type']=='seasonal' and topics[0]['downgraded_from']=='historical'
    assert topics[0]['evidence']==[] and errors and not topics[0]['frequency_supported']
    assert store.get_artifact(topics[0]['knowledge_ref'])['verified_local_history'] is False
    assert seasonal_knowledge_usable('冬季是呼吸道传染病高发季节，若室内人员聚集而通风不足，可能增加传播风险。')
    assert not seasonal_knowledge_usable('安顺市历年冬季高发取暖中毒事故，统计显示2025年发生过十起事故。')


def seasonal_candidates(categories):
    return [{'id':f'c{i+1}','category':category,'basis_type':'seasonal','context_factors':['season'],
        'knowledge_basis':'若未来季节和活动节奏变化，而设施检查与诉求核查不及时，可能积累安全隐患或利益纠纷。',
        'local_facts_to_verify':[],'comparison_reason':'结合未来月份的触发条件、影响对象和可提前干预性进行预警比较。'} for i,category in enumerate(categories)]


def assert_seasonal_fallback_result(store,calls,result,categories):
    assert len(calls)==4 and result['status']=='ready' and len(result['topics'])==5
    assert result['seasonal_fallback_categories']==categories
    assert all(t['basis_type']=='seasonal' and not t['evidence'] for t in result['topics'])
    assert all(store.get_artifact(t['knowledge_ref'])['verified_local_history'] is False for t in result['topics'])
    assert not any(e['type']=='web_usage' for e in store.events('r'))


def test_three_failed_selections_reuse_compared_seasonal_candidates_without_more_calls(tmp_path):
    store,_=fixture(tmp_path);calls=[]
    categories=['凝冻出行风险','取暖用火风险','年末工资结算风险','冬季人员聚集风险','节庆聚餐风险']
    candidates=seasonal_candidates(categories)
    async def adapter(role,payload):
        calls.append(payload)
        if 'candidate_comparison' not in payload:return {'candidates':candidates}
        return {'topics':[],'gaps':['历史网页不可读，未取得本地同期事故资料。']}
    _,result=asyncio.run(prepare_history(FrozenReport(store,'r'),RunContext(store,'r',model_adapter=adapter)))
    assert_seasonal_fallback_result(store,calls,result,categories)


def test_three_valid_seasonal_topics_are_not_ready_and_are_topped_up_to_five(tmp_path):
    store,_=fixture(tmp_path);calls=[]
    categories=['凝冻出行风险','取暖用火风险','年末工资结算风险','冬季人员聚集风险','节庆聚餐风险']
    candidates=seasonal_candidates(categories)
    async def adapter(role,payload):
        calls.append(payload)
        if 'candidate_comparison' not in payload:return {'candidates':candidates}
        return {'topics':[{'candidate_id':candidate['id'],'category':candidate['category'],'basis_type':'seasonal','applies_to_months':[11,12],
            'knowledge_basis':candidate['knowledge_basis'],'rationale':candidate['comparison_reason'],'evidence':[]} for candidate in candidates[:3]],'gaps':['没有本地历史网页。']}
    _,result=asyncio.run(prepare_history(FrozenReport(store,'r'),RunContext(store,'r',model_adapter=adapter)))
    assert_seasonal_fallback_result(store,calls,result,categories[3:])
    assert [t['category'] for t in result['topics']]==categories


def test_invalid_content_revisions_are_declined_and_stopped(tmp_path):
    store,_,state=seeded(tmp_path);draft=store.get_artifact(state.draft_ref);calls=[]
    async def adapter(role,payload):
        calls.append(role)
        if role=='writer':return {'patches':[]}
        result=clean_review(payload)
        if role=='content_reviewer':
            if calls.count(role)>1:assert 'writer_returned_no_repair' in payload['last_repair_validation_error']
            result['issues']=[{'field_id':'w1','kind':'logic','quote':payload['fields'][0]['value'],'description':'条件需要核查。','suggestion':'补足条件，保留其他有效内容。','action':'revise'}]
        return result
    state=asyncio.run(run_writing_graph(Dependencies(store,adapter),'r',True))
    assert calls==['format_reviewer','content_reviewer','writer']
    assert state.phase=='awaiting_final_review' and state.metadata['writing_review_run']['finished']
    assert store.get_artifact(state.draft_ref)==draft
    assert state.metadata['writing_review_run']['stage_repair_attempts']=={'content_reviewer':1}
    declined=[i for i in state.review_items if i['details'].get('writer_declined')]
    assert len(declined)==1 and declined[0]['status']=='open' and declined[0]['blocking']


def test_exhausted_format_repair_budget_does_not_consume_content_budget(tmp_path):
    store,_,_=seeded(tmp_path);calls=[]
    async def adapter(role,payload):
        calls.append(role)
        if role=='writer':
            f=payload['editable_fields'][0]
            return {'patches':[{'field_id':f['id'],'before':f['value'],'after':f['value']+'待复核。','issue_ids':[i['id'] for i in payload['issues']],'source_refs':f['source_refs']}]}
        result=clean_review(payload)
        result['issues']=[{'field_id':'w1','kind':'format' if role=='format_reviewer' else 'logic','quote':payload['fields'][0]['value'],'description':'该处问题仍需修订。','suggestion':'保留事实与条件，明确表达。','action':'revise'}]
        return result
    state=asyncio.run(run_writing_graph(Dependencies(store,adapter),'r',True))
    run=state.metadata['writing_review_run']
    assert run['stage_repair_attempts']=={'format_reviewer':5,'content_reviewer':4}
    assert calls.index('content_reviewer')>calls.index('writer') and calls.count('content_reviewer')==5
    assert calls.count('writer')==9 and state.phase=='awaiting_final_review'
    assert any(i['status']=='open' and i['reviewer']=='format_reviewer' for i in state.review_items)


def test_overlength_analysis_patch_does_not_discard_other_valid_field(tmp_path):
    from app.reviewers import begin_run,revise_draft
    store,template,state=seeded(tmp_path);template=copy.deepcopy(template)
    next(f for f in template['fields'] if f['id']=='w1')['display_name']='研判分析'
    state.template_ref=store.put_artifact('r','template',template);store.put_task(state,state.revision)
    values=store.get_artifact(state.draft_ref)['slot_values'];values['w1']['value']='若隐患没有及时化解，相关风险可能进一步扩大。'*17
    state=save_draft(store,state,template,values,{state.fact_ref,'human_edit'},{},[]);begin_run(store,'r',True)
    state=store.get_task('r');state.metadata['writing_review_run']['repair_stage']='content_reviewer'
    for key in ('w1','w2'):
        state.review_items.append({'id':key,'kind':'writing_review','reviewer':'content_reviewer','status':'open','blocking':True,'details':{'field_id':key,'kind':'logic','action':'revise','quote':values[key]['value']}})
    store.put_task(state,state.revision)
    async def adapter(role,payload):
        fields={f['id']:f for f in payload['editable_fields']};assert fields['w1']['value_schema']['maxLength']==500
        return {'patches':[{'field_id':key,'before':fields[key]['value'],'after':'若'+'可能扩大风险。'*73 if key=='w1' else '另一个字段已经完成有效修订。','issue_ids':[key],'source_refs':fields[key]['source_refs']} for key in ('w1','w2')]}
    assert asyncio.run(revise_draft(Dependencies(store,adapter),'r'))
    latest=store.get_task('r');draft=store.get_artifact(latest.draft_ref)
    assert draft['slot_values']['w1']==values['w1'] and draft['slot_values']['w2']['value']=='另一个字段已经完成有效修订。'
    assert latest.metadata['writing_review_run']['repair_field_errors'][0]['field_id']=='w1'
