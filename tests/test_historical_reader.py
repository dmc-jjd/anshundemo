import asyncio
import pytest
from app.historical_reader import HistoricalReader
from app.historical_web import page_read_error
from app.schemas import ToolResult
from app.tool_executor import RunContext
from test_frozen_writer import fixture

@pytest.mark.parametrize('body',[
    '当前环境异常，完成验证后继续访问。去验证',
    '<html><script>challenge()</script><h1>Just a moment</h1>Verify you are human</html>',
    '请完成安全验证，拖动滑块后继续',
    '请登录后查看全文',
    'Sign in to continue reading',
    'Access denied 403 Forbidden',
    '访问过于频繁，请稍后重试',
    '文章已被删除',
    '<html><body> </body></html>',
])
def test_unreadable_page_classes(body):assert page_read_error(body)

def test_real_article_about_verification_is_not_a_verification_screen():
    assert page_read_error('安顺警方提醒：不要向陌生人提供短信验证码，遇诈骗应及时报警。') is None

def setup(tmp_path,urls):
    store,_=fixture(tmp_path);ref=store.put_artifact('r','historical_search',{'query':'安顺 冬季安全','results':[{'url':url,'title':'冬季风险资料','date':'2025-11-01'} for url in urls]})
    return store,ref

def executor_for(store,contents,calls,replacement=None):
    async def executor(call,context):
        if call.tool_name=='search_historical_web':
            calls.append(('search',call.arguments['query']))
            ref=store.put_artifact('r','historical_search',{'query':call.arguments['query'],'results':[{'url':replacement,'title':'官方替代来源','date':'2025-11-01'}] if replacement else []})
            return ToolResult(status='ok',data_ref=ref)
        url=call.arguments['url'];calls.append(('fetch',url));body=contents[url]
        error=page_read_error(body)
        ref=store.put_artifact('r','historical_page',{'url':url,'title':'原网页标题','content':body,'published_at':'2025-11-01','search_ref':call.arguments['search_ref']})
        return ToolResult(status='error' if error else 'ok',data_ref=ref,error_code='historical_page_unreadable' if error else None,warnings=[error] if error else [])
    return executor

def test_skip_bad_page_auto_reads_next_source_and_remembers_across_instances(tmp_path):
    bad='https://mp.weixin.qq.com/bad';good='https://www.anshun.gov.cn/good';store,search=setup(tmp_path,[bad,good]);calls=[];refs={search}
    executor=executor_for(store,{bad:'请完成安全验证',good:'安顺市2025年11月发布冬季用火用电安全提示。'},calls)
    async def run():
        first=HistoricalReader(RunContext(store,'r',phase='writing'),refs,executor)
        result=await first.fetch({'search_ref':search,'url':bad})
        assert result['actual_url']==good and result['requested_url']==bad
        assert result['data']['url']==good and result['data']['excerpts']
        assert len(result['skipped_sources'])==1
        second=HistoricalReader(RunContext(store,'r',phase='writing'),refs,executor)
        cached=await second.fetch({'search_ref':search,'url':bad})
        assert cached['actual_url']==good and cached['cache_used'] is True
    asyncio.run(run())
    assert calls==[('fetch',bad),('fetch',good)]
    assert store.get_task('r').metadata['historical_reader']['fetch_count']==2

def test_automatically_supplements_search_only_once(tmp_path):
    bad='https://example.com/login';good='https://www.anshun.gov.cn/article';store,search=setup(tmp_path,[bad]);calls=[]
    executor=executor_for(store,{bad:'登录后继续阅读',good:'安顺市2025年11月提出冬季道路交通安全措施。'},calls,replacement=good)
    result=asyncio.run(HistoricalReader(RunContext(store,'r',phase='writing'),{search},executor).fetch({'search_ref':search,'url':bad}))
    assert result['actual_url']==good
    assert [kind for kind,_ in calls]==['fetch','search','fetch']
    page=store.get_artifact(result['ref']);assert page['url']==good and page['search_ref']!=search

def test_all_sources_unreadable_end_with_bounded_seasonal_handoff_not_fake_evidence(tmp_path):
    urls=['https://example.com/a','https://example.com/b','https://example.com/c'];store,search=setup(tmp_path,urls);calls=[]
    executor=executor_for(store,{url:'Access denied' for url in urls},calls)
    reader=HistoricalReader(RunContext(store,'r',phase='writing'),{search},executor,max_attempts=2,max_fetches=2)
    result=asyncio.run(reader.fetch({'search_ref':search,'url':urls[0]}))
    assert result['error']=='no_readable_historical_source' and 'ref' not in result
    assert result['fallback']=={'basis_type':'seasonal','verified_local_history':False}
    assert len(calls)==2
    again=asyncio.run(reader.fetch({'search_ref':search,'url':urls[0]}));assert again['error'] and len(calls)==2

def test_fragment_variants_do_not_repeat_failed_request(tmp_path):
    one='https://example.com/challenge#one';two='https://example.com/challenge#two';good='https://example.com/good';store,search=setup(tmp_path,[one,two,good]);calls=[]
    executor=executor_for(store,{one:'请完成安全验证',good:'安顺市冬季风险提醒，需提前做好相关安全防范。'},calls)
    result=asyncio.run(HistoricalReader(RunContext(store,'r',phase='writing'),{search},executor).fetch({'search_ref':search,'url':one}))
    assert result['actual_url']==good and calls==[('fetch',one),('fetch',good)]

def test_arbitrary_url_is_not_fetched_or_substituted(tmp_path):
    store,search=setup(tmp_path,['https://example.com/approved']);calls=[]
    executor=executor_for(store,{},calls)
    result=asyncio.run(HistoricalReader(RunContext(store,'r',phase='writing'),{search},executor).fetch({'search_ref':search,'url':'https://example.com/unapproved'}))
    assert result['error']=='url_not_in_historical_search' and not calls

def test_research_agent_continues_after_program_substitutes_a_blocked_page(tmp_path,monkeypatch):
    import app.historical_reader as module
    from app.historical_research import prepare_history
    from app.frozen_report import FrozenReport
    bad='https://example.com/verify';good='https://www.anshun.gov.cn/winter';store,search=setup(tmp_path,[bad,good]);calls=[]
    executor=executor_for(store,{bad:'请完成安全验证',good:'安顺市2025年11月提示，入冬后应提前排查取暖用火用电、通风和线路方面的隐患。'},calls)
    original=module.HistoricalReader
    monkeypatch.setattr(module,'HistoricalReader',lambda ctx,refs:original(ctx,refs,executor))
    categories=['取暖用火用电','道路凝冻安全','森林野外用火','节日消费风险','冬季人员聚集']
    async def model(role,payload):
        if 'candidate_comparison' not in payload:return {'candidates':[{'id':f'c{i+1}','category':category,'basis_type':'seasonal','context_factors':['season'],
            'knowledge_basis':'若入冬后相关活动增加且排查不充分，可能形成安全隐患，应按未来条件提前预防。','local_facts_to_verify':[],
            'comparison_reason':'该风险与未来冬季窗口有关，应比较具体触发条件和前置措施，避免单纯复述本月事件。'} for i,category in enumerate(categories)]}
        if not payload.get('tool_results'):return {'tool_calls':[{'function':{'name':'fetch_historical_page','arguments':{'search_ref':search,'url':bad}}}]}
        result=payload['tool_results'][-1];assert result['actual_url']==good
        return {'topics':[{'candidate_id':f'c{i+1}','category':category,'basis_type':'seasonal','applies_to_months':[11,12],
            'knowledge_basis':'若入冬后相关活动增加且排查不充分，可能形成安全隐患，应按未来条件提前预防。',
            'rationale':'该风险与未来冬季窗口有关，应比较具体触发条件和前置措施，避免复述本月事件。',
            'evidence':[{'page_ref':result['ref'],'period':'2025-11','quote':'安顺市2025年11月提示，入冬后应提前排查取暖用火用电、通风和线路方面的隐患。','basis':'seasonal_advisory'}] if i==0 else []} for i,category in enumerate(categories[:4])],'gaps':[]}
    _,packet=asyncio.run(prepare_history(FrozenReport(store,'r'),RunContext(store,'r',phase='writing',model_adapter=model)))
    assert packet['status']=='ready' and len(packet['topics'])==4
    assert packet['topics'][0]['evidence'][0]['url']==good
    assert calls==[('fetch',bad),('fetch',good)]
