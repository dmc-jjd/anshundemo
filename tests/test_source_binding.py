import asyncio,json
import pytest
from pydantic import ValidationError
from app.source_binding import SourceCatalog,NumberedAnswers,NumberedRevision,NumberedSlot
from app.structured_writer import StructuredAnswers,write_structured_preview
from app.workflow import Dependencies
from test_frozen_writer import fixture
from test_section_two import analysis_plan


def test_outlook_answer_schemas_accept_four_or_five_and_reject_three_or_six():
    items=[{'category':f'未来风险{i}','history_refs':[1],
        'historical_basis':'依据已经核对的季节条件和未来活动变化开展风险研判',
        'trigger':'未来季节条件变化且原有隐患未得到及时处理',
        'risk_path':'个体风险可能因处置迟滞而逐步扩大，产生重复损失并引起更多当事人反映诉求',
        'early_signals':['同一区域重复出现类似风险信号'],'owner':'相关主管部门',
        'action':'提前核对重点场所和相关主体的实际隐患，明确处置责任和整改进度，核验受影响群体反映的问题',
        'objective':'提前处理隐患并减少重复损失和诉求积累'} for i in range(6)]
    for count in (4,5):
        numbered=NumberedAnswers.model_validate({'outlook_items':items[:count]})
        structured=StructuredAnswers.model_validate({'outlook_items':[{**item,'history_refs':['risk-knowledge']} for item in items[:count]]})
        assert len(numbered.outlook_items)==len(structured.outlook_items)==count
    for count in (3,6):
        with pytest.raises(ValidationError):NumberedAnswers.model_validate({'outlook_items':items[:count]})
        with pytest.raises(ValidationError):StructuredAnswers.model_validate({'outlook_items':[{**item,'history_refs':['risk-knowledge']} for item in items[:count]]})

def test_model_gets_numbers_and_program_binds_all_reference_fields():
    catalog=SourceCatalog({'facts-real','record-real'})
    packet=catalog.project({'fact_ref':'facts-real','evidence':[{'ref':'record-real','title':'案件原文'}]})
    assert packet=={'fact_ref':1,'evidence':[{'ref':2,'title':'案件原文'}]}
    plan=analysis_plan('unused').model_dump();plan['chains'][0]['source_refs']=[1];plan['chains'][1]['source_refs']=[2]
    wire=NumberedAnswers.model_validate({'analysis_plan':plan,'values':{'x':{'value':'严肃分析正文','source_refs':[2,1]}}})
    bound=StructuredAnswers.model_validate(catalog.bind(wire.model_dump()))
    assert bound.analysis_plan.chains[0].source_refs==['facts-real']
    assert bound.analysis_plan.chains[1].source_refs==['record-real']
    assert bound.values['x']['source_refs']==['record-real','facts-real']

@pytest.mark.parametrize('invalid',['facts-real','facts-real:top10#1','1',True,1.2,0])
def test_model_cannot_return_raw_ids_or_noninteger_numbers(invalid):
    with pytest.raises(ValidationError):NumberedAnswers.model_validate({'values':{'x':{'value':'正文','source_refs':[invalid]}}})
    with pytest.raises(ValidationError):NumberedSlot.model_validate({'slot_id':'x','value':'正文','source_refs':[invalid]})
    with pytest.raises(ValidationError):NumberedRevision.model_validate({'patches':[{'field_id':'x','before':'原文','after':'修订','issue_ids':['issue'],'source_refs':[invalid]}]})

def test_unknown_numbers_cannot_bind_and_dynamic_tool_numbers_never_shift():
    allowed={'facts-real'};catalog=SourceCatalog(allowed);assert catalog.project({'ref':'facts-real'})['ref']==1
    with pytest.raises(ValueError,match='未知资料编号'):catalog.bind({'source_refs':[999]})
    allowed.add('tool-result-real');assert catalog.project({'ref':'tool-result-real'})['ref']==2
    assert catalog.bind({'history_refs':[1,2]})=={'history_refs':['facts-real','tool-result-real']}
    assert catalog.project({'ref':'facts-real'})['ref']==1
    assert catalog.project({'before':'facts-real','title':'facts-real','value':['facts-real']})=={'before':'facts-real','title':'facts-real','value':['facts-real']}

def test_real_writer_retry_keeps_text_and_stores_canonical_bindings(tmp_path):
    store,_=fixture(tmp_path);calls=[]
    async def model(role,payload):
        calls.append(payload)
        if 'reference_requests' in payload:
            assert payload['reference_requests'][0]['context']['value']=='保留这段有依据的正文'
            return {'selections':[{'path':request['path'],'source_refs':[payload['evidence'][0]['ref']]} for request in payload['reference_requests']]}
        key=payload['remaining_fields'][0];number=payload['evidence'][0]['ref']
        assert type(number) is int and payload['output_values_schema']['properties'][key]['properties']['source_refs']['items']['type']=='integer'
        wrong=key=='w1'
        return {'values':{key:{'value':'保留这段有依据的正文','source_refs':[999 if wrong else number]}}}
    state=asyncio.run(write_structured_preview(Dependencies(store,model),'r'));draft=store.get_artifact(state.draft_ref)
    assert draft['slot_values']['w1']['value']=='保留这段有依据的正文'
    assert 'reference_requests' in calls[1] and 'remaining_fields' not in calls[1]
    assert all(isinstance(ref,str) for key in ('w1','w2') for ref in draft['slot_values'][key]['source_refs'])
    assert draft['slot_values']['b17_warning_count']['value']=='2'
    audits=[e for e in store.events('r') if e['type']=='writer_source_catalog'];assert audits
    mapping=store.get_artifact(audits[-1]['ref'])['sources'];assert mapping and all(type(row['number']) is int for row in mapping)

@pytest.mark.parametrize('source',['1','facts-real'])
def test_safe_exact_normalization_preserves_body_without_a_second_model_call(tmp_path,source):
    from app.source_binding import invoke_numbered_writer
    from app.tool_executor import RunContext
    store,_=fixture(tmp_path);catalog=SourceCatalog({'facts-real'});calls=[]
    async def model(role,payload):
        calls.append(payload);return {'values':{'x':{'value':'原文保持','source_refs':[source]}}}
    result=asyncio.run(invoke_numbered_writer(catalog,{'evidence':[{'ref':'facts-real'}]},NumberedAnswers,RunContext(store,'r',model_adapter=model)))
    assert result['values']['x']=={'value':'原文保持','source_refs':['facts-real']} and len(calls)==1
    assert any(e['type']=='writer_source_normalized' for e in store.events('r'))

def test_three_reference_failures_keep_candidate_for_final_human_without_model_reentry(tmp_path,monkeypatch):
    import app.main as main
    from fastapi.testclient import TestClient
    store,_=fixture(tmp_path);calls=[]
    async def model(role,payload):
        calls.append(payload)
        if 'reference_requests' in payload:return {'selections':[]}
        key=payload['remaining_fields'][0]
        return {'values':{key:{'value':'已经生成但需要人工核对来源的完整候选正文','source_refs':[999 if key=='w1' else payload['evidence'][0]['ref']]}}}
    state=asyncio.run(write_structured_preview(Dependencies(store,model),'r'));state.phase='awaiting_final_review';store.put_task(state,state.revision)
    assert len([p for p in calls if 'reference_requests' in p])==2
    monkeypatch.setattr(main,'store',store);client=TestClient(main.app)
    view=client.get('/api/tasks/r/draft-view').json();assert view['pending_sources']['w1']['value']=='已经生成但需要人工核对来源的完整候选正文'
    assert 'w1' in view['missing'] and not view['can_approve']
    count=len(calls);fact=store.get_task('r').fact_ref
    response=client.post('/api/tasks/r/slot-values',json={'expected_hash':view['draft']['content_hash'],'values':{'w1':view['pending_sources']['w1']['value']}})
    assert response.status_code==200 and len(calls)==count
    latest=client.get('/api/tasks/r/draft-view').json();assert not latest['pending_sources']
    assert latest['draft']['slot_values']['w1']['source_refs']==['human_edit'] and store.get_task('r').fact_ref==fact
