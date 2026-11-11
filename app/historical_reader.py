"""Bounded source substitution with task-scoped failed-URL memory."""
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode
from .historical_web import FetchQuery,page_read_error
from .schemas import ToolCall
from .tool_executor import execute_tool
from .section_two import source_excerpts
import uuid


def url_key(url):
    parsed=urlsplit(url)
    return urlunsplit((parsed.scheme.lower(),parsed.netloc.lower(),parsed.path,urlencode(sorted(parse_qsl(parsed.query,keep_blank_values=True))),''))


class HistoricalReader:
    def __init__(self,context,refs,executor=execute_tool,max_attempts=3,max_fetches=12):
        self.context=context;self.store=context.store;self.task_id=context.task_id;self.refs=refs;self.executor=executor
        self.max_attempts=max_attempts;self.max_fetches=max_fetches
        state=self.store.get_task(self.task_id)
        self.state=state.metadata.get('historical_reader',{})
        if self.state.get('fact_ref')!=state.fact_ref:self.state={'fact_ref':state.fact_ref,'failed_urls':{},'read_urls':{},'fetch_count':0}
        for ref in sorted(refs):
            if not ref.startswith('historical_page-'):continue
            page=self.store.get_artifact(ref);error=page_read_error(page.get('content',''))
            if error:self.state['failed_urls'][url_key(page['url'])]={'url':page['url'],'reason':error,'ref':ref}
            else:self.state['read_urls'][url_key(page['url'])]=ref
        self.persist()

    def persist(self):
        state=self.store.get_task(self.task_id);state.metadata['historical_reader']=self.state;self.store.put_task(state,state.revision)

    async def call(self,name,args):
        return await self.executor(ToolCall(call_id=uuid.uuid4().hex,tool_name=name,arguments=args,reason='按候选来源自动读取，跳过不可读页面'),self.context)

    def packet(self,ref):
        self.refs.add(ref);page=self.store.get_artifact(ref)
        return {'ref':ref,'data':{k:v for k,v in page.items() if k!='content'}|{'excerpts':source_excerpts(page['content'])}}

    async def search(self,args):
        result=await self.call('search_historical_web',args)
        if result.status!='ok':return {'error':result.error_code,'details':result.warnings}
        self.refs.add(result.data_ref);data=self.store.get_artifact(result.data_ref)
        data['results']=[row for row in data['results'] if url_key(row['url']) not in self.state['failed_urls']]
        return {'ref':result.data_ref,'data':data}

    async def fetch(self,args):
        query=FetchQuery.model_validate(args)
        if not self.store.artifact_belongs_to_task(query.search_ref,self.task_id):return {'error':'foreign_historical_search'}
        search=self.store.get_artifact(query.search_ref)
        if not any(row.get('url')==query.url for row in search.get('results',[])):return {'error':'url_not_in_historical_search'}
        self.refs.add(query.search_ref)
        def ordered(rows,requested=None):
            return sorted(rows,key=lambda r:(r.get('url')!=requested,not (urlsplit(r.get('url','')).hostname or '').endswith('.gov.cn')))
        queue=[(query.search_ref,row['url']) for row in ordered(search.get('results',[]),query.url)]
        seen=set();skipped=[];attempts=0;researched=False
        while True:
            if not queue:
                if researched or attempts>=self.max_attempts or self.state['fetch_count']>=self.max_fetches or not search.get('query'):break
                researched=True
                alternative=await self.search({'query':search['query'][:116]+' 官网 原文','count':6})
                if alternative.get('error'):break
                queue.extend((alternative['ref'],row['url']) for row in ordered(alternative['data']['results']))
                continue
            search_ref,url=queue.pop(0);key=url_key(url)
            if key in seen:continue
            seen.add(key)
            if key in self.state['failed_urls']:
                skipped.append(self.state['failed_urls'][key]);self.store.append_event(self.task_id,{'type':'historical_source_skipped','url':url,'reason':'本任务已记录不可读，不重复请求'})
                continue
            cached=self.state['read_urls'].get(key)
            if cached:
                page=self.store.get_artifact(cached)
                if not page_read_error(page.get('content','')):
                    return {**self.packet(cached),'requested_url':query.url,'actual_url':url,'cache_used':True,'skipped_sources':skipped}
            if attempts>=self.max_attempts or self.state['fetch_count']>=self.max_fetches:break
            attempts+=1;self.state['fetch_count']+=1;self.persist()
            result=await self.call('fetch_historical_page',{'search_ref':search_ref,'url':url})
            page=self.store.get_artifact(result.data_ref) if result.data_ref else {}
            error=page_read_error(page.get('content','')) if result.status=='ok' else ';'.join(result.warnings) or result.error_code
            if not error:
                self.state['read_urls'][key]=result.data_ref;self.persist()
                if url!=query.url:self.store.append_event(self.task_id,{'type':'historical_source_substituted','requested_url':query.url,'actual_url':url,'ref':result.data_ref})
                return {**self.packet(result.data_ref),'requested_url':query.url,'actual_url':url,'skipped_sources':skipped}
            failure={'url':url,'reason':error,'ref':result.data_ref};self.state['failed_urls'][key]=failure;skipped.append(failure);self.persist()
            self.store.append_event(self.task_id,{'type':'historical_source_skipped',**failure})
        self.store.append_event(self.task_id,{'type':'historical_sources_exhausted','requested_url':query.url,'attempts':attempts,'fetch_count':self.state['fetch_count']})
        return {'error':'no_readable_historical_source','requested_url':query.url,'skipped_sources':skipped,
                'fallback':{'basis_type':'seasonal','verified_local_history':False},'details':['自动换源未取得可读正文；可选有清楚条件依据的季节风险，不得冒充已核实的地方历史事实。']}
