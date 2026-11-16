"""D 方案验证通道：模型自决联网搜索（function calling）+ 思考流 + SSE 回答流。

刻意不进 OpenAPI（G-OPENAPI 不变）；临时页 `static/chat-test.html` 只用于验证 D。
搜索一律走 `core/historical_web.py` 的公开通道（`SearchQuery` / `request` / `page_read_error`），
不另写搜索 HTTP 客户端，也不绕开正文可读性门禁。
"""
from __future__ import annotations
import asyncio,json,threading,time,urllib.error,urllib.request

from fastapi import APIRouter,Request
from fastapi.responses import StreamingResponse

from core.config import MODEL_KEY,MODEL_NAME,MODEL_REASONING_EFFORT,MODEL_THINKING,MODEL_URL
from core.historical_web import SearchQuery,page_read_error
from core.historical_web import request as web_request

router=APIRouter(include_in_schema=False)

MAX_TOOL_ROUNDS=2            # 最多两轮「模型→工具→模型」，之后强制出答案（防失控成本）
MAX_SEARCHES_PER_ROUND=3     # 单轮最多执行 3 次搜索；超出的 tool_call 直接回预算错误
MAX_FETCH_PER_SEARCH=2       # 每次搜索最多读 2 篇正文（可读性门禁跑在正文上）
MAX_FETCH_CHARS=1500
FETCH_DEADLINE_S=20          # 单次搜索里补正文的总预算，超时只用摘要
MAX_HISTORY=20
MAX_TOKENS=8000
SEARCH_PRICE_CNY=0.005

SYSTEM=('你是网络舆情分析助手，帮助用户分析舆情、撰写研判、改写文稿。'
        '问题涉及近期事件、最新进展、具体时间地点人物等你可能不知道或已过时的信息时，'
        '先调用 web_search 再作答；引用搜索到的信息时在句末给出可点击来源链接；'
        '搜索不到或结果不可读时如实说明依据有限。回答用中文，简洁准确。')

TOOLS=[{"type":"function","function":{
    "name":"web_search",
    "description":"联网搜索实时信息。当用户询问近期事件、最新进展、具体时间地点人物等你的知识可能过时或缺失的信息时调用。",
    "parameters":{"type":"object","properties":{
        "query":{"type":"string","description":"搜索词，≤128 字符"},
        "count":{"type":"integer","description":"返回条数，1~10，默认 8"}},
        "required":["query"]}}}]


class _NullStore:
    """搜索通道只要求 `ctx.store.append_event`；对话没有任务账本，就地记账供费用统计。"""
    def __init__(self):self.events=[]
    def append_event(self,task_id,event):self.events.append(event)


class _Ctx:
    def __init__(self):
        self.task_id='chat'
        self.store=_NullStore()


def _endpoint():
    url=(MODEL_URL or '').rstrip('/')
    if not url.endswith('/chat/completions'):url+='/chat/completions'
    return url


def _body(messages,allow_tools):
    params={'model':MODEL_NAME,'messages':messages,'stream':True,'max_tokens':MAX_TOKENS}
    if allow_tools:params.update(tools=TOOLS,tool_choice='auto')
    if MODEL_THINKING in ('enabled','disabled'):params['thinking']={'type':MODEL_THINKING}
    if MODEL_REASONING_EFFORT in ('low','high','max'):params['reasoning_effort']=MODEL_REASONING_EFFORT
    return params


def _stream_once(messages,allow_tools,emit):
    """跑一轮流式请求：思考增量即时下发，正文增量即时下发，顺手组装 tool_calls。"""
    if not (MODEL_URL and MODEL_NAME and MODEL_KEY):raise RuntimeError('model_not_configured')
    req=urllib.request.Request(_endpoint(),json.dumps(_body(messages,allow_tools),ensure_ascii=False).encode(),
                               {'Authorization':'Bearer '+MODEL_KEY,'Content-Type':'application/json'})
    text,calls,usage,thinking_open=[],{},None,False
    with urllib.request.urlopen(req,timeout=180) as response:
        for raw in response:
            line=raw.decode('utf-8','replace').strip()
            if not line.startswith('data:'):continue
            payload=line[5:].strip()
            if payload=='[DONE]':break
            try:chunk=json.loads(payload)
            except ValueError:continue
            if chunk.get('usage'):usage=chunk['usage']
            for choice in chunk.get('choices') or []:
                delta=choice.get('delta') or {}
                thought=delta.get('reasoning_content')
                if thought:
                    thinking_open=True
                    emit({'type':'thinking','text':thought})
                for part in delta.get('tool_calls') or []:
                    slot=calls.setdefault(part.get('index',0),{'id':None,'name':None,'arguments':''})
                    if part.get('id'):slot['id']=part['id']
                    fn=part.get('function') or {}
                    if fn.get('name'):slot['name']=fn['name']
                    if fn.get('arguments'):slot['arguments']+=fn['arguments']
                piece=delta.get('content')
                if piece:
                    if thinking_open:
                        emit({'type':'thinking_end'});thinking_open=False
                    text.append(piece)
                    emit({'type':'delta','text':piece})
    if thinking_open:emit({'type':'thinking_end'})
    return ''.join(text),[calls[k] for k in sorted(calls)] if calls else [],usage


def _clean_call(call):
    """把模型给的参数收敛到通道硬限制内：name 只认 web_search，query ≤128，count ∈ 1..10。"""
    if call.get('name')!='web_search':raise ValueError('unknown_tool:'+str(call.get('name')))
    try:args=json.loads(call.get('arguments') or '{}')
    except ValueError as exc:raise ValueError('invalid_tool_arguments') from exc
    if not isinstance(args,dict):raise ValueError('invalid_tool_arguments')
    query=args.get('query')
    if not isinstance(query,str) or not query.strip():raise ValueError('missing_query')
    try:count=int(args.get('count',8))
    except (TypeError,ValueError):count=8
    return query.strip()[:128],min(max(count,1),10)


def _search(query,count,ctx,deadline):
    """搜索 + 给前 2 条补正文；正文过 `page_read_error` 门禁，不可读就只留摘要与原因。"""
    normalized=SearchQuery.model_validate({'query':query,'count':count})
    raw=web_request('search',{'query':normalized.query,'count':normalized.count,'need_content':False},ctx)
    rows=[]
    for item in (raw.get('results') or [])[:5]:
        rows.append({'title':item.get('title'),'url':item.get('url'),'date':item.get('date'),
                     'site_name':item.get('site_name'),'authority':item.get('authority'),
                     'snippet':(item.get('snippet') or item.get('summary') or '')[:400]})
    for row in rows[:MAX_FETCH_PER_SEARCH]:
        url=row.get('url') or ''
        if not url.startswith(('http://','https://')) or time.monotonic()>deadline:continue
        try:page=web_request('fetch',{'url':url},ctx)
        except Exception as exc:
            row['read_error']=f'fetch_failed:{type(exc).__name__}'
            continue
        content=page.get('content') or ''
        error=page_read_error(content)
        if error:row['read_error']=error
        else:row['content']=content[:MAX_FETCH_CHARS]
    return rows


def _add_usage(total,usage):
    if not usage:return
    total['prompt_tokens']+=int(usage.get('prompt_tokens') or 0)
    total['completion_tokens']+=int(usage.get('completion_tokens') or 0)
    total['reasoning_tokens']+=int(((usage.get('completion_tokens_details') or {}).get('reasoning_tokens')) or 0)


def _run(messages,emit):
    conversation=[{'role':'system','content':SYSTEM}]
    for item in (messages or [])[-MAX_HISTORY:]:
        role,content=(item or {}).get('role'),(item or {}).get('content')
        if role in ('user','assistant') and isinstance(content,str) and content.strip():
            conversation.append({'role':role,'content':content[:8000]})
    if len(conversation)==1:
        emit({'type':'error','message':'messages_required'});return
    ctx=_Ctx()
    usage={'prompt_tokens':0,'completion_tokens':0,'reasoning_tokens':0}
    rounds=searches=0
    for round_no in range(MAX_TOOL_ROUNDS+1):
        allow_tools=round_no<MAX_TOOL_ROUNDS
        round_searches=0
        text,calls,round_usage=_stream_once(conversation,allow_tools,emit)
        rounds+=1
        _add_usage(usage,round_usage)
        if not calls:break
        conversation.append({'role':'assistant','content':text or None,'tool_calls':[
            {'id':call.get('id') or f'call_{index}','type':'function',
             'function':{'name':call.get('name') or '','arguments':call.get('arguments') or '{}'}}
            for index,call in enumerate(calls)]})
        for index,call in enumerate(calls):
            call_id=call.get('id') or f'call_{index}'
            if round_searches>=MAX_SEARCHES_PER_ROUND:
                emit({'type':'search_failed','reason':'search_budget_exhausted'})
                conversation.append({'role':'tool','tool_call_id':call_id,
                                     'content':json.dumps({'status':'error','error':'search_budget_exhausted'},ensure_ascii=False)})
                continue
            try:query,count=_clean_call(call)
            except ValueError as exc:
                conversation.append({'role':'tool','tool_call_id':call_id,
                                     'content':json.dumps({'status':'error','error':str(exc)},ensure_ascii=False)})
                continue
            emit({'type':'search','query':query})
            deadline=time.monotonic()+FETCH_DEADLINE_S
            round_searches+=1
            searches+=1
            try:rows=_search(query,count,ctx,deadline)
            except Exception as exc:
                reason=str(exc) or type(exc).__name__
                emit({'type':'search_failed','reason':reason})
                conversation.append({'role':'tool','tool_call_id':call_id,
                                     'content':json.dumps({'status':'error','error':reason,'query':query},ensure_ascii=False)})
                continue
            readable=sum(1 for row in rows if row.get('content'))
            emit({'type':'search_result','query':query,'hits':len(rows),'readable':readable,
                  'urls':[row['url'] for row in rows if row.get('url')]})
            conversation.append({'role':'tool','tool_call_id':call_id,'content':json.dumps(
                {'status':'ok','query':query,'results':rows,
                 'note':'read_error 非空表示该页正文不可引用，只能作线索。'},ensure_ascii=False)})
    billable=sum(1 for event in ctx.store.events if event.get('type')=='web_usage' and event.get('billable'))
    emit({'type':'done','usage':usage,'thinking_tokens':usage['reasoning_tokens'],
          'rounds':rounds,'searches':searches,'search_cost_cny':round(billable*SEARCH_PRICE_CNY,4)})


def _sse(event):
    return 'data: '+json.dumps(event,ensure_ascii=False)+'\n\n'


@router.post('/api/chat/stream')
async def chat_stream(request:Request):
    try:body=await request.json()
    except Exception:body={}
    messages=body.get('messages') if isinstance(body,dict) else None
    if not isinstance(messages,list) or not messages:
        async def rejected():
            yield _sse({'type':'error','message':'messages_required'})
        return StreamingResponse(rejected(),media_type='text/event-stream',
                                 headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
    queue=asyncio.Queue()
    loop=asyncio.get_running_loop()
    def emit(event):loop.call_soon_threadsafe(queue.put_nowait,event)
    def work():
        try:_run(messages,emit)
        except Exception as exc:emit({'type':'error','message':f'{type(exc).__name__}: {exc}'})
        finally:emit(None)
    threading.Thread(target=work,daemon=True).start()
    async def events():
        while True:
            event=await queue.get()
            if event is None:break
            yield _sse(event)
    return StreamingResponse(events(),media_type='text/event-stream',
                             headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
