import asyncio,copy,json
from pathlib import Path
import pytest
from test_frozen_writer import fixture
from app.section_two import HistoricalResearch,HistoryTopic,HistoryCitation,OutlookItem,AnalysisPlan,forecast_window,validate_history,render_outlook,render_analysis,POLICY_VERSION
from app.frozen_report import FrozenReport

def history_fixture(store,count=4):
    topics=[]
    categories=('冬季道路交通','居民用火用电','年末劳动报酬','冬季人员聚集','低温凝冻出行','节庆聚餐安全')
    for category in categories[:count]:
        quote=f'安顺市2025年11月{category}问题多发，相关部门提示做好前置风险防范。'
        ref=store.put_artifact('r','historical_page',{'url':'https://www.anshun.gov.cn/'+category,'title':category,'published_at':'2025-11-15T08:00:00+00:00','content':quote})
        topics.append(HistoryTopic(category=category,rationale='本地区往年同期有官方高发提示，与下两个月的季节和社会活动变化相关。',evidence=[HistoryCitation(page_ref=ref,period='2025-11',quote=quote,location_quote='安顺市',basis='official_frequency')]))
    return HistoricalResearch(topics=topics)

def test_historical_scope_quotes_and_frequency_are_not_guessed(tmp_path):
    store,_=fixture(tmp_path);report=FrozenReport(store,'r');window=forecast_window(report)
    assert window['periods']==['2026-11','2026-12']
    result=history_fixture(store);good,errors=validate_history(result,store,'r',window)
    assert len(good)==4 and not errors
    forged=result.model_copy(deep=True);forged.topics[0].evidence[0].quote='安顺市不存在于网页的虚构高发统计和数字。'
    forged_good,forged_errors=validate_history(forged,store,'r',window)
    assert len(forged_good)==3 and any('不足4类' in error for error in forged_errors)
    wrong_month=result.model_copy(deep=True);wrong_month.topics[0].evidence[0].period='2025-08'
    assert len(validate_history(wrong_month,store,'r',window)[0])==3
    single_cases=result.model_copy(deep=True)
    for topic in single_cases.topics:topic.evidence[0].basis='recurrence_case'
    cases=validate_history(single_cases,store,'r',window)[0]
    assert len(cases)==4 and all(t['basis_label']=='历史同期案例参考' and not t['frequency_supported'] for t in cases)
    seasonal=result.model_copy(deep=True)
    for topic in seasonal.topics:topic.evidence[0].basis='seasonal_advisory'
    assert not validate_history(seasonal,store,'r',window)[0]
    linked=result.model_copy(deep=True)
    for topic in linked.topics:
        citation=topic.evidence[0];citation.url=store.get_artifact(citation.page_ref)['url'];citation.page_ref='';citation.quote='';citation.location_quote='';citation.excerpt_index=0
    assert len(validate_history(linked,store,'r',window)[0])==4

def outlook_item(topic):
    return OutlookItem(category=topic['category'],history_refs=[topic['evidence'][0]['page_ref']],
        historical_basis='往年十一月本地官方曾提示这一领域问题多发，应结合今年暴露的薄弱环节研判',
        trigger='季节变化叠加相关活动集中，而前期排查处置不充分',risk_path='风险隐患可能先造成个体损失，再因处置迟滞积累同类诉求，扩散为区域治理争议',
        early_signals=['同一区域同类求助集中出现'],owner='相关主管部门',action='在风险窗口前核查重点区域的实际隐患，逐项明确处置责任和复核依据，发现连续同类投诉后优先联合核查',objective='尽早处理实质问题并防止重复损失和诉求聚集')

def test_forward_outlook_accepts_four_or_five_categories_and_matched_sources(tmp_path):
    store,_=fixture(tmp_path);report=FrozenReport(store,'r');window=forecast_window(report)
    topics,errors=validate_history(history_fixture(store,6),store,'r',window)
    assert len(topics)==6 and not errors
    items=[outlook_item(topic) for topic in topics]
    for count in (4,5):
        text,refs=render_outlook(items[:count],topics,window)
        assert len(text)==count and all('11月—12月' in x and '若' in x and '应重点跟踪' in x for x in text)
    with pytest.raises(ValueError,match='4—5类'):render_outlook(items[:3],topics,window)
    with pytest.raises(ValueError,match='4—5类'):render_outlook(items,topics,window)
    changed=copy.deepcopy(items[:4]);changed[0].history_refs=items[1].history_refs
    with pytest.raises(ValueError,match='未对应'):render_outlook(changed,topics,window)
    invented=copy.deepcopy(items[:4]);invented[0].historical_basis='2022年本地共发生999起相关事故，呈现持续高发态势，应对未来窗口重点预防'
    with pytest.raises(ValueError):render_outlook(invented,topics,window)

def mixed_research(store):
    result=history_fixture(store)
    result.topics[1]=HistoryTopic(candidate_id='c2',category='取暖用火用电风险',basis_type='seasonal',applies_to_months=[11,12],
        knowledge_basis='入冬后若取暖用火用电增加而设施检查不到位，可能出现安全隐患，这是季节条件推演。',
        rationale='面向未来两个月分析条件和可观察信号，不将一般季节机制称为本地高发。')
    result.topics[2].basis_type='local_activity';result.topics[2].applies_to_months=[11,12]
    result.topics[2].evidence[0].basis='local_activity'
    return result

def test_mixed_evidence_allows_seasonal_reasoning_and_requires_local_activity_sources(tmp_path):
    store,_=fixture(tmp_path);window=forecast_window(FrozenReport(store,'r'))
    result=mixed_research(store);topics,errors=validate_history(result,store,'r',window)
    assert len(topics)==4 and not errors
    assert [t['basis_type'] for t in topics]==['historical','seasonal','local_activity','historical']
    knowledge=topics[1]['knowledge_ref'];assert knowledge and store.artifact_belongs_to_task(knowledge,'r')
    assert store.get_artifact(knowledge)['verified_local_history'] is False
    result.topics[2].evidence=[]
    assert len(validate_history(result,store,'r',window)[0])==3
    result=mixed_research(store);result.topics[1].knowledge_basis='统计显示安顺往年冬季高发二十起中毒事件，应提前防范相关问题。'
    assert len(validate_history(result,store,'r',window)[0])==3
    result=mixed_research(store);result.topics[1].applies_to_months=[7,8]
    assert len(validate_history(result,store,'r',window)[0])==3

def test_model_memory_comparison_then_selection_can_finish_without_forced_network(tmp_path):
    from app.historical_research import prepare_history
    from app.section_two import CandidateComparison
    from app.tool_executor import RunContext
    from pydantic import ValidationError
    store,_=fixture(tmp_path);calls=[]
    categories=['低温道路通行','取暖用火安全','岁末劳资纠纷','地方聚餐活动','冬季人员聚集']
    candidates=[{'id':f'c{i+1}','category':name,'basis_type':'seasonal','context_factors':['season'],
                 'knowledge_basis':'若季节和活动节奏变化而检查处置不充分，可能积累个体损失并产生重复诉求。',
                 'local_facts_to_verify':[],'comparison_reason':'应比较未来窗口触发条件和影响对象，并优先选择能够提前发现和干预的风险。'} for i,name in enumerate(categories)]
    assert len(CandidateComparison(candidates=candidates).candidates)==5
    with pytest.raises(ValidationError):CandidateComparison(candidates=candidates[:4])
    async def adapter(role,payload):
        calls.append(payload)
        if 'candidate_comparison' not in payload:
            assert 'available_tools' not in payload  # Planning uses model memory only.
            return {'candidates':candidates}
        return {'topics':[{'candidate_id':f'c{i+1}','category':name,'basis_type':'seasonal','applies_to_months':[11,12],
            'knowledge_basis':candidates[i]['knowledge_basis'],'rationale':candidates[i]['comparison_reason'],'evidence':[]} for i,name in enumerate(categories[:4])],'gaps':[]}
    ctx=RunContext(store,'r',phase='writing',model_adapter=adapter)
    _,packet=asyncio.run(prepare_history(FrozenReport(store,'r'),ctx))
    assert packet['status']=='ready' and len(packet['candidate_comparison']['candidates'])==5 and len(packet['topics'])==4
    assert len(calls)==2 and not any(e['type']=='web_usage' for e in store.events('r'))
    assert packet['window']['maximum_lookback_years']==5
    asyncio.run(prepare_history(FrozenReport(store,'r'),ctx))
    assert len(calls)==2  # Ready evidence/knowledge packet is reusable.

def test_case_reference_can_deny_frequency_without_being_mistaken_for_frequency_claim(tmp_path):
    store,_=fixture(tmp_path);window=forecast_window(FrozenReport(store,'r'));research=history_fixture(store)
    for topic in research.topics:topic.evidence[0].basis='historical_case'
    topics,_=validate_history(research,store,'r',window)
    items=[OutlookItem(category=t['category'],history_refs=[t['evidence'][0]['page_ref']],
        historical_basis='该条资料仅作本地历史案例参考，不作历史高发认定，未来仍应根据条件提前研判',
        trigger='未来季节条件变化且原有隐患未得到及时处理',risk_path='个体风险可能因处置迟滞而逐步扩大，产生重复损失并引起更多当事人反映诉求',
        early_signals=['同一区域重复出现类似风险信号'],owner='相关主管部门',
        action='提前核对重点场所和相关主体的实际隐患，明确处置责任和整改进度，核验受影响群体反映的问题',objective='提前处理隐患并减少重复损失和诉求积累') for t in topics]
    assert len(render_outlook(items,topics,window)[0])==4
    for denied in ('本地无高发统计','未据本地高发统计认定','非本地高发统计'):
        items[0].historical_basis='该条资料仅作本地历史案例参考，'+denied+'，未来应根据条件提前研判'
        assert len(render_outlook(items,topics,window)[0])==4
    items[0].historical_basis='该条历史资料证明本地此类问题历年高发，应据此优先采取前置措施防范相关风险'
    with pytest.raises(ValueError,match='不能声称历史高发'):render_outlook(items,topics,window)

def test_cited_date_supports_unpadded_month_but_not_invented_count(tmp_path):
    store,_=fixture(tmp_path);window=forecast_window(FrozenReport(store,'r'));research=history_fixture(store)
    topics,_=validate_history(research,store,'r',window)
    items=[OutlookItem(category=t['category'],history_refs=[t['evidence'][0]['page_ref']],
        historical_basis='该资料发布于2025年11月，为本地风险研判提供已核实的参考，应结合未来条件分析',
        trigger='未来季节条件变化且原有隐患未得到及时处理',risk_path='个体风险可能因处置迟滞而逐步扩大，产生重复损失并引起更多当事人反映诉求',
        early_signals=['同一区域重复出现类似风险信号'],owner='相关主管部门',
        action='提前核对重点场所和相关主体的实际隐患，明确处置责任和整改进度，核验受影响群体反映的问题',objective='提前处理隐患并减少重复损失和诉求积累') for t in topics]
    # Test the YYYY-02 versus Chinese 2月 representation explicitly.
    for t in topics:t['evidence'][0]['period']='2025-02'
    for item in items:item.historical_basis='该资料发布于2025年2月，为本地风险研判提供已核实的参考，应结合未来条件分析'
    assert len(render_outlook(items,topics,window)[0])==4
    items[0].historical_basis+='；面向11月至12月应重点核查相关条件。'
    assert len(render_outlook(items,topics,window)[0])==4
    items[0].historical_basis='该资料显示本地发生2起同类事故，应据此核查风险并结合未来条件提前安排排查'
    with pytest.raises(ValueError,match='未支持的数字'):render_outlook(items,topics,window)

def analysis_plan(ref):
    return AnalysisPlan(overview='本月涉公共安全和权益保障的诉求较为集中，风险应从个体遭遇向责任争议的转化路径识别。',chains=[
      {'trigger':'涉事责任和实际损失长期未核清，重复诉求缺乏可核验的办理进展','escalation':'同类当事人借助对比材料持续质疑，程序分歧进一步叠加公平性和责任归属争议','impact':'原有个案由损失争议扩展为更广泛的治理信任问题','signal':'相同诉求重复提交且出现跨平台串联','owner':'属地和主管部门','mitigation':'先核对原始证据和责任链条，明确具体争议的办理进度与复核路径，公开可核实的处理结果','source_refs':[ref]},
      {'trigger':'高风险活动的现场画面与安全说明出现反差，救援处置信息又不完整','escalation':'片段画面推动风险感知上升，并从现场操作引发对项目管理和责任落实的连续追问','impact':'个案可能牵连相关区域的安全信任和公众参与意愿','signal':'旧片段反复传播并出现新的现场指认','owner':'行业主管部门','mitigation':'核查现场操作和应急保障是否真实到位，将隐患整改与事实说明同步推进，回应可验证的具体问题','source_refs':[ref]}])

def test_analysis_requires_causal_chains_and_targeted_interventions(tmp_path):
    store,_=fixture(tmp_path);ref=store.get_task('r').fact_ref
    plan=analysis_plan(ref);text,refs=render_analysis(plan,{ref})
    assert 300<=len(text)<=500 and text.count('若')==2 and '应关注' in text and refs==[ref]
    with pytest.raises(ValueError,match='本月来源'):render_analysis(plan,set())
    with pytest.raises(ValueError):AnalysisPlan(overview=plan.overview,chains=plan.chains[:1])

def test_web_tools_only_fetch_actual_search_results_and_meter_success(tmp_path,monkeypatch):
    import core.historical_web as web  # WP-S8-L1：patch 点必须在实现所在模块，app 壳上的副本静默失效
    import io
    store,_=fixture(tmp_path)
    from app.tool_executor import RunContext
    ctx=RunContext(store,'r',phase='writing')
    monkeypatch.setattr(web,'MODEL_URL','https://api.deepseek.com');monkeypatch.setattr(web,'MODEL_KEY','test-key')
    class Reply:
        def __init__(self,data):self.data=data
        def __enter__(self):return io.StringIO(json.dumps(self.data))
        def __exit__(self,*args):pass
    sent=[]
    def request(req,timeout):
        sent.append(req.full_url)
        return Reply({'results':[{'title':'原始公告','url':'https://www.anshun.gov.cn/a','date':'2025-11-01','summary':'测试'}]} if req.full_url.endswith('search') else {'title':'原始公告','content':'安顺市官方历史风险资料。'})
    monkeypatch.setattr(web.urllib.request,'urlopen',request)
    search=web.search_historical_web({'query':'安顺 2025年11月','count':3},ctx)
    with pytest.raises(ValueError):web.fetch_historical_page({'search_ref':search.data_ref,'url':'http://127.0.0.1/internal'},ctx)
    fetched=web.fetch_historical_page({'search_ref':search.data_ref,'url':'https://www.anshun.gov.cn/a'},ctx)
    assert store.get_artifact(fetched.data_ref)['content']
    assert len(sent)==2 and sum(e.get('estimated_cny',0) for e in store.events('r') if e['type']=='web_usage')==.01

def test_cached_human_second_section_is_not_researched_again(tmp_path,monkeypatch):
    from app.structured_writer import save_draft,write_structured_preview
    from app.structured_template import _schema
    from app.workflow import Dependencies
    from app.historical_research import prepare_history
    store,template=fixture(tmp_path)
    # Rename the two writer fields into the actual second-section slots.
    for field in template['fields']:
        if field['id']=='w1':field.update(id='b40_analysis_paragraph',kind='analysis')
        elif field['id']=='w2':field.update(id='monthly_recommendations',kind='paragraph_list',value_schema={'type':'array','items':{'type':'string'},'minItems':1,'maxItems':5})
    for block in template['blocks']:
        for part in block['parts']:
            if part.get('field')=='w1':part['field']='b40_analysis_paragraph'
            elif part.get('field')=='w2':part['field']='monthly_recommendations'
    template['output_schema']=_schema(template['fields']);template['writer_schema']=_schema(template['fields'],True)
    ref=store.put_artifact('r','template_version',template);state=store.get_task('r');state.template_ref=ref;store.put_task(state,state.revision)
    values={'b17_warning_count':{'value':'2','source_refs':[state.fact_ref]},'b40_analysis_paragraph':{'value':'人工最终研判','source_refs':['human_edit']},'monthly_recommendations':{'value':['人工最终预警1','人工最终预警2','人工最终预警3'],'source_refs':['human_edit']}}
    state=save_draft(store,state,template,values,{state.fact_ref,'human_edit'},{},[])
    async def forbidden(*args,**kwargs):raise AssertionError('人工兜底后不得重新联网或调用模型')
    import app.historical_research as research
    monkeypatch.setattr(research,'prepare_history',forbidden)
    state=asyncio.run(write_structured_preview(Dependencies(store,forbidden),'r'))
    draft=store.get_artifact(state.draft_ref)
    assert draft['slot_values']['monthly_recommendations']==values['monthly_recommendations']
    assert draft['slot_values']['b40_analysis_paragraph']==values['b40_analysis_paragraph']

def test_native_tool_budget_forces_final_json_instead_of_losing_evidence(tmp_path,monkeypatch):
    import io
    # WP-S8-L2：实现在 core/model_client.py，patch 必须打在被读的模块上（打壳=改副本，静默失效）。
    import core.model_client as m
    from app.tool_executor import RunContext
    from app.structured_writer import StructuredAnswers
    from app.writer_tools import native_tools
    store,_=fixture(tmp_path);choices=[]
    class Reply:
        def __init__(self,obj):self.obj=obj
        def __enter__(self):return io.StringIO(json.dumps(self.obj))
        def __exit__(self,*args):pass
    def urlopen(req,timeout):
        request=json.loads(req.data);choices.append(request['tool_choice'])
        message={'role':'assistant','content':'{"values":{}}'} if request['tool_choice']=='none' else {'role':'assistant','tool_calls':[{'id':'call'+str(len(choices)),'function':{'name':'frozen_statistics','arguments':'{"metric":"count"}'}}]}
        return Reply({'model':'test','choices':[{'message':message}],'usage':{'prompt_tokens':1,'completion_tokens':1}})
    monkeypatch.setattr(m,'MODEL_URL','https://example.invalid');monkeypatch.setattr(m,'MODEL_KEY','test');monkeypatch.setattr(m,'MODEL_NAME','test');monkeypatch.setattr(m.urllib.request,'urlopen',urlopen)
    async def tool(name,args):return {'value':'4'}
    asyncio.run(m.invoke_agent('writer',{},StructuredAnswers,RunContext(store,'r'),tools=native_tools(),tool_executor=tool))
    assert choices==['auto']*6+['none']


def seasonal_research(store,count=4):
    categories=('低温道路通行','取暖用火安全','岁末劳资纠纷','冬季人员聚集','节庆聚餐安全')
    result=HistoricalResearch(topics=[HistoryTopic(candidate_id=f'c{i+1}',category=category,basis_type='seasonal',applies_to_months=[11,12],
        knowledge_basis='入冬后若生产生活安排变化而设施检查和现场管理不到位，可能出现安全隐患，这是条件性季节机制。',
        rationale='结合未来月份的一般季节条件分析可观察信号，不将条件推演表述为本地历史高发。') for i,category in enumerate(categories[:count])])
    topics,errors=validate_history(result,store,'r',forecast_window(FrozenReport(store,'r')))
    assert len(topics)==count and not errors
    return topics


def seasonal_outlook_item(topic,paragraph=None):
    return {'category':topic['category'],'history_refs':[topic['knowledge_ref']],
        'historical_basis':'入冬后若相关活动增加而设施检查和现场管理不到位，可能出现安全隐患，应按季节条件提前核查并明确处置责任。',
        'paragraph':paragraph or (topic['category']+'方面，面向11月—12月，若气温下降、生产生活安排变化且前期隐患排查不充分，相关风险可能由个别隐患逐步转化为人员损失和重复诉求。有关部门应在风险窗口前核查重点场所、重点环节和责任落实情况，结合实际建立问题清单，逐项明确整改责任、复核依据和处置进度。对同一区域连续出现的同类求助、设备异常和现场管理缺口，应及时组织联合核查，区分直接诱因与管理漏洞，优先处理可能造成伤害或扩大损失的实质问题，并向当事人反馈可核验的办理进展。后续还应根据天气和活动变化动态调整巡查重点，做好应急物资、人员值守和跨部门信息衔接，避免仅以宣传和报备代替现场治理，切实降低重复损失和诉求聚集风险。'),
        'trigger':'未来季节条件变化且原有隐患未得到及时处理','risk_path':'个体风险可能因处置迟滞而逐步扩大，产生重复损失并引起更多当事人反映诉求',
        'early_signals':['同一区域重复出现类似风险信号'],'owner':'相关主管部门',
        'action':'提前核对重点场所和相关主体的实际隐患，明确处置责任和整改进度，核验受影响群体反映的问题','objective':'提前处理隐患并减少重复损失和诉求积累'}


def outlook_writer_fixture(tmp_path,monkeypatch,topic_count=4,max_items=5,history_packet=None):
    from app.structured_template import _schema
    store,template=fixture(tmp_path)
    template['fields']=[f for f in template['fields'] if f['id']!='w1']
    template['blocks']=[b for b in template['blocks'] if not any(p.get('field')=='w1' for p in b['parts'])]
    for field in template['fields']:
        if field['id']=='w2':field.update(id='monthly_recommendations',kind='paragraph_list',value_schema={'type':'array','items':{'type':'string'},'minItems':4,'maxItems':max_items})
    for block in template['blocks']:
        for part in block['parts']:
            if part.get('field')=='w2':part['field']='monthly_recommendations'
    template['output_schema']=_schema(template['fields']);template['writer_schema']=_schema(template['fields'],True)
    ref=store.put_artifact('r','template_version',template);state=store.get_task('r');state.template_ref=ref;store.put_task(state,state.revision)
    if history_packet is None:
        topics=seasonal_research(store,topic_count);window=forecast_window(FrozenReport(store,'r'))
        history_packet={'status':'ready','window':window,'topics':topics,'errors':[]}
    topics=history_packet['topics']
    history_ref=store.put_artifact('r','historical_research',history_packet)
    async def prepared(*args,**kwargs):return history_ref,history_packet
    import app.historical_research as research
    monkeypatch.setattr(research,'prepare_history',prepared)
    return store,topics


def fixed_exchange(short):
    path=Path(__file__).parent.parent/'data'/'artifacts'/f'model_exchange-{short}.json'
    exchange=json.loads(path.read_text(encoding='utf-8'))
    request=json.loads(next(message['content'] for message in exchange['messages'] if message['role']=='user'))
    response=json.loads(exchange['response']['choices'][0]['message']['content'])
    return request,response


def fixed_outlook_history():
    request,_=fixed_exchange('f99ce0c4d4c33f87688b')
    history=copy.deepcopy(request['historical_research'])
    for topic in history['topics']:
        if topic.get('knowledge_ref') is not None:topic['knowledge_ref']=f"replay:{topic['knowledge_ref']}"
        for citation in topic['evidence']:citation['page_ref']=f"replay:{citation['page_ref']}"
    history.update(status='ready',errors=[])
    return history


def replay_fixed_exchanges(monkeypatch):
    import app.structured_writer as writer
    invoke=writer.invoke_numbered_writer
    async def replay(catalog,*args,**kwargs):
        if not catalog.mapping:
            for number in range(1,60):
                ref=f'replay:{number}'
                catalog.allowed.add(ref);catalog.mapping[number]=ref;catalog.reverse[ref]=number
        return await invoke(catalog,*args,**kwargs)
    monkeypatch.setattr(writer,'invoke_numbered_writer',replay)


def test_writer_inherits_omitted_seasonal_basis_type(tmp_path,monkeypatch):
    from app.structured_writer import write_structured_preview
    from app.workflow import Dependencies
    store,_=outlook_writer_fixture(tmp_path,monkeypatch);calls=[]
    async def model(role,payload):
        calls.append(payload)
        return {'outlook_items':[seasonal_outlook_item(topic) for topic in payload['historical_research']['topics']]}
    state=asyncio.run(write_structured_preview(Dependencies(store,model),'r'))
    value=store.get_artifact(state.draft_ref)['slot_values']['monthly_recommendations']['value']
    assert len(value)==4 and len(calls)==1
    assert 'monthly_recommendations' not in state.metadata['missing_fields']


def test_single_item_validation_retains_truthfulness_guards(tmp_path):
    from app.section_two import render_outlook_item
    store,_=fixture(tmp_path);window=forecast_window(FrozenReport(store,'r'))
    topics,_=validate_history(history_fixture(store),store,'r',window);item=outlook_item(topics[0])
    item.history_refs=topics[1]['evidence'] and [topics[1]['evidence'][0]['page_ref']]
    with pytest.raises(ValueError) as error:render_outlook_item(item,topics,window)
    assert item.category in str(error.value) and item.history_refs[0] in str(error.value) and topics[0]['evidence'][0]['page_ref'] in str(error.value)
    item=outlook_item(topics[0]);item.historical_basis='2025年本地共发生999起相关事故，应结合未来窗口重点预防并核查处置责任'
    with pytest.raises(ValueError,match='未支持的数字'):render_outlook_item(item,topics,window)
    research=history_fixture(store)
    for topic in research.topics:topic.evidence[0].basis='historical_case'
    single_topics,_=validate_history(research,store,'r',window);item=outlook_item(single_topics[0])
    item.historical_basis='该条2025年11月历史案例被写成安顺此类问题持续高发，应据此优先采取前置措施防范相关风险'
    with pytest.raises(ValueError,match='不能声称历史高发'):render_outlook_item(item,single_topics,window)
    items=[outlook_item(topic) for topic in topics];items[1].category=items[0].category
    with pytest.raises(ValueError,match='类别重复'):render_outlook(items,topics,window)
    seasonal=seasonal_research(store);data=seasonal_outlook_item(seasonal[0]);data['basis_type']='seasonal'
    data['paragraph']='安顺历年冬季高发取暖中毒事故，应据此认定本地历史规律并提前安排重点防范。'+data['paragraph']
    with pytest.raises(ValueError,match='季节推演不能冒充'):render_outlook_item(OutlookItem(**data),seasonal,window)


def test_writer_locks_valid_items_and_repairs_only_failed_category(tmp_path,monkeypatch):
    from app.structured_writer import write_structured_preview
    from app.workflow import Dependencies
    store,canonical_topics=outlook_writer_fixture(tmp_path,monkeypatch);calls=[];originals={}
    async def model(role,payload):
        calls.append(payload);topics=payload['historical_research']['topics']
        if len(calls)==1:
            items=[seasonal_outlook_item(topic) for topic in topics]
            originals.update({item['category']:item['paragraph'] for item in items})
            items[1]['history_refs']=[topics[0]['knowledge_ref']]
            return {'outlook_items':items}
        repair=payload['outlook_repair']['invalid_items']
        assert len(repair)==1 and repair[0]['category']==topics[1]['category'] and repair[0]['item_index']==1
        assert repair[0]['item']['paragraph']==originals[topics[1]['category']]
        assert repair[0]['error_code']=='category_source_mismatch'
        assert repair[0]['allowed_numbers']==[topics[1]['knowledge_ref']]
        fixed=seasonal_outlook_item(topics[1],paragraph=originals[topics[1]['category']]+'修复后仍按原类别依据说明。')
        changed=seasonal_outlook_item(topics[0],paragraph='不应覆盖已锁定正文。'+originals[topics[0]['category']])
        return {'outlook_items':[fixed,changed]}
    state=asyncio.run(write_structured_preview(Dependencies(store,model),'r'))
    values=store.get_artifact(state.draft_ref)['slot_values']['monthly_recommendations']['value']
    assert len(calls)==2 and len(values)==4
    by_category={text.split('方面，',1)[0]:text for text in values}
    assert by_category[canonical_topics[0]['category']]==originals[canonical_topics[0]['category']]
    assert by_category[canonical_topics[1]['category']].endswith('修复后仍按原类别依据说明。')


def test_writer_allows_new_topic_category_while_locking_valid_items(tmp_path,monkeypatch):
    from app.structured_writer import write_structured_preview
    from app.workflow import Dependencies
    store,topics=outlook_writer_fixture(tmp_path,monkeypatch,topic_count=5);calls=[];originals={}
    async def model(role,payload):
        calls.append(payload)
        if len(calls)==1:
            items=[seasonal_outlook_item(topic) for topic in topics[:4]]
            originals.update({item['category']:item['paragraph'] for item in items})
            items[1]['history_refs']=[topics[0]['knowledge_ref']]
            return {'outlook_items':items}
        assert [entry['category'] for entry in payload['outlook_repair']['invalid_items']]==[topics[1]['category']]
        added=seasonal_outlook_item(topics[4])
        unknown=seasonal_outlook_item(topics[0]);unknown['category']='未登记风险类别'
        return {'outlook_items':[added,unknown]}
    state=asyncio.run(write_structured_preview(Dependencies(store,model),'r'))
    draft=store.get_artifact(state.draft_ref);values=draft['slot_values']['monthly_recommendations']['value']
    assert len(calls)==2 and len(values)==4
    by_category={text.split('方面，',1)[0]:text for text in values}
    assert set(by_category)=={topics[index]['category'] for index in (0,2,3,4)}
    assert by_category[topics[0]['category']]==originals[topics[0]['category']]
    assert '未登记风险类别' not in by_category


def test_writer_deterministically_submits_four_of_five_for_legacy_template(tmp_path,monkeypatch):
    from app.structured_writer import write_structured_preview
    from app.workflow import Dependencies
    store,topics=outlook_writer_fixture(tmp_path,monkeypatch,topic_count=5,max_items=4);calls=[]
    items=[seasonal_outlook_item(topic) for topic in topics]
    expected=[item['paragraph'] for item in items[:4]]
    async def model(role,payload):
        calls.append(payload);return {'outlook_items':copy.deepcopy(items)}
    state=asyncio.run(write_structured_preview(Dependencies(store,model),'r'))
    draft=store.get_artifact(state.draft_ref)
    assert len(calls)==1
    assert draft['slot_values']['monthly_recommendations']['value']==expected
    assert 'monthly_recommendations' not in state.metadata['missing_fields']


def test_writer_pending_candidate_merges_locked_and_latest_invalid_item(tmp_path,monkeypatch):
    from app.structured_writer import write_structured_preview
    from app.workflow import Dependencies
    store,topics=outlook_writer_fixture(tmp_path,monkeypatch);calls=[];originals={};latest=None
    async def model(role,payload):
        nonlocal latest
        calls.append(payload)
        if len(calls)==1:
            items=[seasonal_outlook_item(topic) for topic in topics]
            originals.update({item['category']:item['paragraph'] for item in items})
            items[1]['historical_basis']='2025年本地发生999起相关事故，应结合未来条件提前核查处置责任'
            return {'outlook_items':items}
        latest=seasonal_outlook_item(topics[1],paragraph=originals[topics[1]['category']]+f'第{len(calls)}次保留这段最新失败正文。')
        latest['historical_basis']='2025年本地发生999起相关事故，应结合未来条件提前核查处置责任'
        return {'outlook_items':[latest]}
    state=asyncio.run(write_structured_preview(Dependencies(store,model),'r'))
    draft=store.get_artifact(state.draft_ref)
    assert len(calls)==3 and draft['recommendations']==[]
    assert state.metadata['preview_only'] and 'monthly_recommendations' in state.metadata['missing_fields']
    issue=next(item for item in state.metadata['writer_issues'] if item['field_id']=='monthly_recommendations')
    pending=store.get_artifact(state.metadata['writer_pending_sources']['monthly_recommendations'])
    assert [entry['category'] for entry in pending['valid_items']]==[topics[index]['category'] for index in (0,2,3)]
    assert [entry['category'] for entry in pending['invalid_items']]==[topics[1]['category']]
    assert pending['invalid_items'][0]['item']['paragraph']==latest['paragraph']
    assert pending['invalid_items'][0]['message']
    assert [entry['category'] for entry in pending['outlook_items']]==[topic['category'] for topic in topics]
    assert pending['value']==[originals[topics[0]['category']],latest['paragraph'],originals[topics[2]['category']],originals[topics[3]['category']]]
    assert issue['error']=='writer_validation_pending'
    assert draft['missing_recommendation_evidence'] is False


def test_save_draft_marks_only_actual_research_insufficiency(tmp_path):
    from app.structured_writer import save_draft
    store,template=fixture(tmp_path);state=store.get_task('r')
    insufficient={'field_id':'w2','error':'historical_evidence_insufficient','message':'研究依据不足'}
    state=save_draft(store,state,template,{},set(),{},[insufficient])
    assert store.get_artifact(state.draft_ref)['missing_recommendation_evidence'] is True
    state=save_draft(store,state,template,{},set(),{},[{'field_id':'w2','error':'writer_validation_pending','message':'写作校验未完成'}])
    assert store.get_artifact(state.draft_ref)['missing_recommendation_evidence'] is False


def test_fixed_replay_inherits_basis_and_locks_first_round_valid_item(tmp_path,monkeypatch):
    from app.structured_writer import write_structured_preview
    from app.workflow import Dependencies
    store,topics=outlook_writer_fixture(tmp_path,monkeypatch,history_packet=fixed_outlook_history())
    replay_fixed_exchanges(monkeypatch)
    responses=[fixed_exchange(short)[1] for short in ('f99ce0c4d4c33f87688b','5c31307cb95b9732fd35')]
    calls=[]
    async def model(role,payload):
        calls.append(payload)
        return copy.deepcopy(responses[len(calls)-1])
    state=asyncio.run(write_structured_preview(Dependencies(store,model),'r'))
    draft=store.get_artifact(state.draft_ref)
    values=draft['slot_values']['monthly_recommendations']['value']
    assert len(calls)==2 and len(values)==4
    assert values[0]==responses[0]['outlook_items'][0]['paragraph']
    assert values[1:]==[item['paragraph'] for item in responses[1]['outlook_items'][1:]]
    repair=calls[1]['outlook_repair']['invalid_items']
    assert [entry['category'] for entry in repair]==['安全生产','自然灾害','社会治安']
    assert all('basis_type' not in item for item in responses[1]['outlook_items'])
    assert all(topic['basis_type']=='seasonal' for topic in topics)
    assert 'monthly_recommendations' not in state.metadata['missing_fields']


def test_fixed_replay_preserves_partial_results_and_source_errors_for_human_review(tmp_path,monkeypatch):
    from app.structured_writer import write_structured_preview
    from app.workflow import Dependencies
    store,topics=outlook_writer_fixture(tmp_path,monkeypatch,history_packet=fixed_outlook_history())
    replay_fixed_exchanges(monkeypatch)
    responses=[fixed_exchange(short)[1] for short in ('f99ce0c4d4c33f87688b','ab56a2481bdb93453bd8','ab56a2481bdb93453bd8')]
    calls=[]
    async def model(role,payload):
        calls.append(payload)
        return copy.deepcopy(responses[len(calls)-1])
    state=asyncio.run(write_structured_preview(Dependencies(store,model),'r'))
    draft=store.get_artifact(state.draft_ref)
    assert len(calls)==3 and draft['recommendations']==[]
    assert state.metadata['preview_only'] and 'monthly_recommendations' in state.metadata['missing_fields']
    issue=next(item for item in state.metadata['writer_issues'] if item['field_id']=='monthly_recommendations')
    assert issue['error']=='writer_source_pending'
    pending=store.get_artifact(state.metadata['writer_pending_sources']['monthly_recommendations'])
    assert [entry['category'] for entry in pending['valid_items']]==['交通管理','自然灾害','社会治安']
    assert [entry['category'] for entry in pending['invalid_items']]==['安全生产']
    invalid=pending['invalid_items'][0]
    assert invalid['error_code']=='category_source_mismatch'
    assert invalid['item']['paragraph']==responses[-1]['outlook_items'][2]['paragraph']
    assert invalid['allowed_refs']==['replay:14']
    assert pending['value'][0]==responses[0]['outlook_items'][0]['paragraph']
    assert pending['value'][1]==responses[-1]['outlook_items'][1]['paragraph']
    assert pending['value'][2]==responses[-1]['outlook_items'][2]['paragraph']
    assert pending['value'][3]==responses[-1]['outlook_items'][3]['paragraph']
    assert len({entry['category'] for entry in pending['outlook_items']})==4
    assert draft['missing_recommendation_evidence'] is False
