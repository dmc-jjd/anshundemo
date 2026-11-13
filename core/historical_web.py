"""Read-only Search/Fetch tools available to the report's research model."""
import json,time,re,urllib.request,urllib.error
from datetime import datetime,timezone
from urllib.parse import urlparse
from pydantic import BaseModel,ConfigDict,Field
from .config import SEARCH_ERROR,SEARCH_ERROR_LEGACY,search_endpoint  # SEARCH_ERROR 供壳层再导出
from .schemas import ToolResult

# 旧错误码别名：值（旧字符串）不变，名字仍可被 `web.<name>` / `from ... import` 取到，
# 既有按旧错误码匹配的调用方零改动；**派发面只抛 `search_not_configured`**（SEARCH_ERROR）。
historical_web_requires_configured_deepseek_endpoint=SEARCH_ERROR_LEGACY

class SearchQuery(BaseModel):
    model_config=ConfigDict(extra='forbid')
    query:str=Field(min_length=1,max_length=128)
    count:int=Field(default=6,ge=1,le=10)

class FetchQuery(BaseModel):
    model_config=ConfigDict(extra='forbid')
    search_ref:str
    url:str=Field(min_length=1,max_length=8192)

def page_read_error(content):
    visible=re.sub(r'<(?:script|style)\b[^>]*>[\s\S]*?</(?:script|style)>','',content,flags=re.I)
    visible=re.sub(r'<[^>]+>',' ',visible)
    compact=re.sub(r'\s+','',visible).lower()
    if not compact:return '网页正文为空，未取得可引用内容。'
    checks=[
        ('访问验证页',('当前环境异常','请完成安全验证','请输入验证码','人机验证','滑动验证','验证您是真人','verifyyouarehuman','checkingyourbrowser','justamoment','enablejavascriptandcookiestocontinue')),
        ('登录或订阅页面',('登录后查看全文','请登录后查看','登录后继续阅读','注册后阅读全文','订阅后阅读全文','signintocontinue','logintocontinue','subscribetocontinue')),
        ('访问拦截页面',('accessdenied','403forbidden','访问过于频繁','请求过于频繁','请求被拦截','访问已被禁止')),
        ('已删除或不存在页面',('404notfound','文章已被删除','内容已删除','该页面不存在')),
    ]
    # Short challenge screens must not be mistaken for a long article that
    # merely reports on verification codes or quotes a login warning.
    if len(compact)<1200:
        for kind,markers in checks:
            if any(marker in compact for marker in markers):
                return '网页返回'+kind+'，尚未取得文章正文；不能引用搜索摘要，请更换可读来源或采用有条件的季节风险。'
    return None

def tools_url(base,kind):
    """搜索工具地址：`<base>/tools/<kind>`；base 无路径段时补 `/v1`（旧行为是硬编码 /v1）。"""
    base=(base or '').rstrip('/')
    if not urlparse(base).path.strip('/'):base+='/v1'
    return base+'/tools/'+kind

def request(kind,args,ctx):
    # 搜索凭据与生成模型解耦：未配置时抛 `search_not_configured`（不带任何网络请求）。
    base,key=search_endpoint()
    url=tools_url(base,kind)
    started=time.monotonic()
    req=urllib.request.Request(url,json.dumps(args,ensure_ascii=False).encode(),{'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=40) as response:data=json.load(response)
        billable=bool(data.get('results')) if kind=='search' else bool(data.get('content'))
        ctx.store.append_event(ctx.task_id,{'type':'web_usage','operation':kind,'status':'ok','billable':billable,'estimated_cny':.005 if billable else 0,'price_source':'https://api-docs.deepseek.com/zh-cn/guides/search/','elapsed_ms':round((time.monotonic()-started)*1000)})
        return data
    except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError) as exc:
        ctx.store.append_event(ctx.task_id,{'type':'web_usage','operation':kind,'status':'error','billable':False,'estimated_cny':0,'error':type(exc).__name__,'status_code':getattr(exc,'code',None)})
        raise ValueError(f'historical_{kind}_failed:{getattr(exc,"code",type(exc).__name__)}') from exc

def search_historical_web(args,ctx):
    query=SearchQuery.model_validate(args)
    raw=request('search',{'query':query.query,'count':query.count,'need_content':False},ctx)
    results=[{k:r.get(k) for k in ('title','url','date','authority','snippet','summary','site_name')} for r in raw.get('results',[])][:query.count]
    data={'query':query.query,'results':results,'retrieved_at':datetime.now(timezone.utc).isoformat(),'note':'搜索摘要只能定位来源；必须Fetch阅读正文再作历史依据。'}
    ref=ctx.store.put_artifact(ctx.task_id,'historical_search',data)
    return ToolResult(status='ok',data_ref=ref,method='deepseek_search')

def fetch_historical_page(args,ctx):
    query=FetchQuery.model_validate(args)
    if not ctx.store.artifact_belongs_to_task(query.search_ref,ctx.task_id):raise ValueError('foreign_historical_search')
    source=ctx.store.get_artifact(query.search_ref)
    result=next((r for r in source.get('results',[]) if r['url']==query.url),None)
    parsed=urlparse(query.url)
    if result is None or parsed.scheme not in ('http','https') or parsed.username or parsed.password:raise ValueError('url_not_in_historical_search')
    data=request('fetch',{'url':query.url},ctx)
    if not data.get('content'):raise ValueError('historical_page_empty')
    error=page_read_error(data['content'])
    ref=ctx.store.put_artifact(ctx.task_id,'historical_page',{'url':query.url,'title':data.get('title') or result['title'],
        'content':data['content'],'published_at':result.get('date'),'authority':result.get('authority'),'search_ref':query.search_ref,
        'retrieved_at':datetime.now(timezone.utc).isoformat(),'read_status':'blocked' if error else 'readable','read_error':error})
    if error:return ToolResult(status='error',data_ref=ref,method='deepseek_fetch',error_code='historical_page_unreadable',warnings=[error])
    return ToolResult(status='ok',data_ref=ref,method='deepseek_fetch')

HANDLERS={f.__name__:f for f in (search_historical_web,fetch_historical_page)}
SCHEMAS={'search_historical_web':SearchQuery.model_json_schema(),'fetch_historical_page':FetchQuery.model_json_schema()}
DESCRIPTIONS={'search_historical_web':'联网搜索本地区往年同期事件与官方高发风险资料，优先政府/公安/消防/气象等原始来源',
              'fetch_historical_page':'阅读搜索结果中的原网页正文；搜索摘要不能替代原文证据'}
def native_tools():return [{'type':'function','function':{'name':n,'description':DESCRIPTIONS[n],'parameters':SCHEMAS[n]}} for n in HANDLERS]
