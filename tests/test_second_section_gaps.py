import pytest
from app.section_two import HistoricalResearch,HistoryTopic,HistoryCitation,forecast_window,validate_history,render_outlook,render_analysis
from app.frozen_report import FrozenReport,query_materials
from app.tool_executor import RunContext
from test_frozen_writer import fixture
from test_section_two import mixed_research,history_fixture,analysis_plan,outlook_item


@pytest.mark.parametrize('knowledge',[
    '气温下降、室内活动增多可能增加学校呼吸道传播风险。此为一般季节机制，未核实安顺本季监测数据，不代表本地已高发。',
    '气温下降后居民燃煤取暖增多，通风不足可能导致一氧化碳中毒。此为条件性机制，本地取暖结构与往年接报数据未核实。',
    '黔中冬季山区若出现低温雨雪，桥面可能结冰，通行风险上升。仅作季节条件推演，未有本地同期案例或高发统计支持。',
])
def test_seasonal_denials_are_not_positive_historical_claims(tmp_path,knowledge):
    store,_=fixture(tmp_path);result=mixed_research(store);result.topics[1].knowledge_basis=knowledge
    good,errors=validate_history(result,store,'r',forecast_window(FrozenReport(store,'r')))
    assert len(good)==4 and not errors
    assert good[1]['knowledge_ref'] and not good[1]['frequency_supported']


def test_denial_does_not_erase_a_separate_invented_statistic(tmp_path):
    store,_=fixture(tmp_path);result=mixed_research(store)
    result.topics[1].knowledge_basis='未核实安顺本季数据，不代表本地已高发；但统计显示2025年本地发生22起事故，应优先排查。'
    good,errors=validate_history(result,store,'r',forecast_window(FrozenReport(store,'r')))
    assert len(good)==3 and any('具体地方历史事实需取证' in e for e in errors)

def test_outlook_uses_same_denial_rules_as_candidate_validation(tmp_path):
    from app.section_two import asserted_knowledge
    assert '高发' not in asserted_knowledge('未有本地同期案例或高发统计支持。')
    assert '往年' not in asserted_knowledge('不代表往年本地已经出现过成规模的道路结冰事故。')
    assert '22起' in asserted_knowledge('不代表高发但统计显示2025年发生22起事故。')


@pytest.mark.parametrize('negation',['并非','不','并未出现','不属于'])
@pytest.mark.parametrize('frequency',['高发','多发','频发','高频','屡发'])
def test_negated_official_frequency_quote_cannot_support_frequency(tmp_path,frequency,negation):
    store,_=fixture(tmp_path)
    quote=f'安顺市2025年11月风险提示：冬季道路交通问题{negation}{frequency}，仍需做好一般性安全防范。'
    ref=store.put_artifact('r','historical_page',{'url':'https://www.anshun.gov.cn/negated-frequency','title':'风险提示','published_at':'2025-11-15T08:00:00+00:00','content':quote})
    proposal=HistoricalResearch(topics=[HistoryTopic(category='冬季道路交通',rationale='需要核实官方摘录是否真正支持高发结论，不能把否定表述当作肯定依据。',evidence=[HistoryCitation(page_ref=ref,period='2025-11',quote=quote,location_quote='安顺市',basis='official_frequency')])])
    good,errors=validate_history(proposal,store,'r',forecast_window(FrozenReport(store,'r')))
    assert not good
    assert any('季节性提示不能冒充高频依据' in error for error in errors)


def test_seasonal_citation_does_not_bypass_knowledge_fact_boundary(tmp_path):
    store,_=fixture(tmp_path);result=mixed_research(store)
    citation=result.topics[0].evidence[0].model_copy(deep=True);citation.basis='seasonal_context'
    result.topics[1].evidence=[citation]
    result.topics[1].knowledge_basis='安顺历年冬季高发取暖中毒事故，应据此认定本地历史规律并提前安排重点防范。'
    good,errors=validate_history(result,store,'r',forecast_window(FrozenReport(store,'r')))
    assert len(good)==3
    assert any('具体地方历史事实需取证' in error for error in errors)


def test_seasonal_citation_does_not_bypass_outlook_fact_boundary(tmp_path):
    store,_=fixture(tmp_path);window=forecast_window(FrozenReport(store,'r'));result=mixed_research(store)
    citation=result.topics[0].evidence[0].model_copy(deep=True);citation.basis='seasonal_context'
    result.topics[1].evidence=[citation]
    topics,errors=validate_history(result,store,'r',window)
    assert len(topics)==4 and not errors
    items=[outlook_item(topic) for topic in topics]
    for item,topic in zip(items,topics):item.basis_type=topic['basis_type']
    items[1].historical_basis='入冬后若取暖用火用电增加而设施检查不到位，可能出现安全隐患，应按季节条件提前排查。'
    assert len(render_outlook(items,topics,window)[0])==4
    items[1].historical_basis='安顺历年冬季高发取暖中毒事故，应据此认定本地历史规律并提前安排重点防范。'
    with pytest.raises(ValueError,match='季节推演不能冒充本地历史高发或具体历史事实'):
        render_outlook(items,topics,window)


@pytest.mark.parametrize('claim,error',[
    ('该条2025年11月历史案例被写成安顺此类问题持续高发，应据此优先采取前置措施防范相关风险','不能声称历史高发'),
    ('该条2025年11月历史案例被写成安顺此类问题历年复现，应据此优先采取前置措施防范相关风险','不能声称跨年复现'),
])
def test_outlook_frequency_and_recurrence_require_the_items_own_citations(tmp_path,claim,error):
    store,_=fixture(tmp_path);window=forecast_window(FrozenReport(store,'r'));research=history_fixture(store)
    single_quote='安顺市2025年11月处置一起冬季道路交通个案，相关部门完成现场核查和后续安全提醒。'
    single_ref=store.put_artifact('r','historical_page',{'url':'https://www.anshun.gov.cn/single-case','title':'个案','published_at':'2025-11-15T08:00:00+00:00','content':single_quote})
    recurrence_quote='安顺市2024年11月处置另一起冬季道路交通个案，相关部门完成现场核查和后续安全提醒。'
    recurrence_ref=store.put_artifact('r','historical_page',{'url':'https://www.anshun.gov.cn/earlier-case','title':'既往个案','published_at':'2024-11-15T08:00:00+00:00','content':recurrence_quote})
    research.topics[0].evidence=[
        HistoryCitation(page_ref=single_ref,period='2025-11',quote=single_quote,location_quote='安顺市',basis='historical_case'),
        research.topics[1].evidence[0].model_copy(deep=True),
        HistoryCitation(page_ref=recurrence_ref,period='2024-11',quote=recurrence_quote,location_quote='安顺市',basis='recurrence_case'),
    ]
    topics,_=validate_history(research,store,'r',window)
    assert topics[0]['frequency_supported'] and topics[0]['recurrence_supported']
    items=[outlook_item(topic) for topic in topics]
    items[0].history_refs=[single_ref];items[0].historical_basis=claim
    with pytest.raises(ValueError,match=error):render_outlook(items,topics,window)


def test_fetch_verification_page_is_audited_but_never_successful_article(tmp_path,monkeypatch):
    import app.historical_web as web
    store,_=fixture(tmp_path);url='https://mp.weixin.qq.com/s?test=article'
    search=store.put_artifact('r','historical_search',{'results':[{'url':url,'title':'安顺冬季风险提示','date':'2025-11-15T08:00:00+00:00'}]})
    monkeypatch.setattr(web,'request',lambda *args:{'content':'环境异常 当前环境异常，完成验证后即可继续访问。 去验证 ： ， 。 视频 小程序 赞'})
    fetched=web.fetch_historical_page({'search_ref':search,'url':url},RunContext(store,'r'))
    assert fetched.status=='error' and fetched.error_code=='historical_page_unreadable'
    assert store.get_artifact(fetched.data_ref)['read_status']=='blocked'
    proposal=HistoricalResearch(topics=[HistoryTopic(category='冬季道路风险',basis_type='historical',rationale='需要核查本地冬季交通风险与未来月份的关系。',evidence=[HistoryCitation(page_ref=fetched.data_ref,excerpt_index=0,period='2025-11',basis='historical_case')])])
    good,errors=validate_history(proposal,store,'r',forecast_window(FrozenReport(store,'r')))
    assert not good and any('访问验证页' in error for error in errors)
    assert not any('片段索引无效' in error for error in errors)


def test_locality_is_derived_from_actual_page_when_model_only_says_province(tmp_path):
    store,_=fixture(tmp_path);proposal=history_fixture(store)
    for topic in proposal.topics:topic.evidence[0].location_quote='贵州'
    good,errors=validate_history(proposal,store,'r',forecast_window(FrozenReport(store,'r')))
    assert len(good)==4 and not errors
    assert all(t['evidence'][0]['location_quote']=='安顺' for t in good)


def test_source_alias_error_names_invalid_and_available_refs(tmp_path):
    store,_=fixture(tmp_path);ref=store.get_task('r').fact_ref;plan=analysis_plan(ref)
    plan.chains[0].source_refs=[ref+':top10#1']
    with pytest.raises(ValueError) as error:render_analysis(plan,{ref,'record-1'})
    assert ref+':top10#1' in str(error.value) and 'record-1' in str(error.value) and '可用ref' in str(error.value)


def test_analysis_materials_cover_distinct_events_instead_of_many_reposts(tmp_path):
    store,_=fixture(tmp_path);report=FrozenReport(store,'r')
    old=query_materials(report,{'focus':'negative_events','limit':2})
    diverse=query_materials(report,{'focus':'negative_events','limit':2,'distinct_events':True})
    assert len({item['event_id'] for item in old['items']})==1
    assert len({item['event_id'] for item in diverse['items']})==2
