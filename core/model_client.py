from __future__ import annotations
import asyncio,json,time,uuid,urllib.request,urllib.error
from datetime import datetime,timezone
from pydantic import BaseModel,ValidationError
from .config import MODEL_URL,MODEL_NAME,MODEL_KEY,MODEL_THINKING,MODEL_REASONING_EFFORT

class ModelUnavailable(RuntimeError): pass
class TaskPaused(BaseException): pass

# Roles granted a generous request timeout (180s). Thinking/reasoning stays as
# configured (enabled) so the model can comply with strict structured schemas;
# the longer timeout covers the slower thinking-enabled latency.
LONG_TIMEOUT_ROLES = frozenset({
    'template_analyst', 'writer', 'writer_data_planner', 'historical_researcher',
    'format_reviewer', 'content_reviewer',
    'event_judge', 'event_classifier', 'event_summarizer', 'data_processor',
})


def classify_model_error(exc) -> str:
    """把模型调用异常翻译成用户可读的失败原因。"""
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        if code == 401: return '模型接口鉴权失败（API Key 无效或过期）'
        if code in (402, 403): return '模型账户额度已用完或无权限（token 配额不足）'
        if code == 404: return '模型名称或接口路径不存在'
        if code == 429: return '模型接口限流（请求过于频繁）'
        if code >= 500: return '模型服务暂时不可用（服务端错误 %s）' % code
        return '模型接口返回错误（HTTP %s）' % code
    if isinstance(exc, (urllib.error.URLError, TimeoutError)):
        reason = getattr(exc, 'reason', None) or exc
        rname = type(reason).__name__ if not isinstance(reason, str) else str(reason)
        if isinstance(reason, TimeoutError) or 'time' in rname.lower() or 'timed out' in str(reason).lower():
            return '网络不稳定（请求超时）'
        return '网络不稳定（连接失败：%s）' % rname
    if isinstance(exc, ValidationError): return '模型输出不符合要求（结构化输出校验失败）'
    if isinstance(exc, ModelUnavailable): return '模型不可用（未配置或响应为空）'
    return '模型调用失败（%s）' % type(exc).__name__

def _raise_if_paused(context):
    if context.store.get_task(context.task_id).phase=='paused':raise TaskPaused()

async def invoke_agent(role_id:str,payload:dict,response_model:type[BaseModel],context,response_schema:dict|None=None,tools:list|None=None,tool_executor=None)->BaseModel:
    # 惰性: agent 在 import 期读提示词注册表（未 configure 即爆炸），而本模块要能在裸 core 下被 import。
    from .agent import AGENT_DEFINITIONS,get_prompt
    if role_id not in AGENT_DEFINITIONS: raise ValueError('unknown_role')
    if context.model_adapter is not None:
        request_payload=dict(payload)
        if tools:request_payload['available_tools']=tools
        for turn in range(7):
            _raise_if_paused(context)
            raw=await context.model_adapter(role_id,request_payload)
            if not isinstance(raw,dict) or not raw.get('tool_calls'):break
            if not tools or tool_executor is None or turn==6:raise ValueError('tool_round_limit_or_not_allowed')
            if len(raw['tool_calls'])>4:raise ValueError('too_many_tools_per_round')
            results=[]
            for call in raw['tool_calls'][:4]:
                fn=call.get('function',call);args=fn.get('arguments',{})
                if isinstance(args,str):args=json.loads(args)
                results.append(await tool_executor(fn['name'],args))
            request_payload={**payload,'available_tools':tools,'tool_results':request_payload.get('tool_results',[])+results}
        value=response_model.model_validate(raw)
        context.store.append_event(context.task_id,{'type':'model_call','role':role_id,'status':'synthetic_test','usage':'not_applicable'})
        return value
    if not (MODEL_URL and MODEL_NAME and MODEL_KEY):
        context.store.append_event(context.task_id,{'type':'model_call','role':role_id,'status':'unavailable','error':'model_not_configured','usage':'unknown'})
        raise ModelUnavailable('model_not_configured')
    started=time.monotonic()
    invocation_id=uuid.uuid4().hex
    messages=[]
    def request():
        schema=json.dumps(response_schema or response_model.model_json_schema(),ensure_ascii=False)
        system=(AGENT_DEFINITIONS[role_id].responsibility+'。'+AGENT_DEFINITIONS[role_id].boundary+
                get_prompt('model.json_output')+schema)
        if not messages:messages.extend([{'role':'system','content':system},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}])
        parameters={'model':MODEL_NAME,'messages':messages,'response_format':{'type':'json_object'},'max_tokens':24000}
        if tools:parameters.update(tools=tools,tool_choice='none' if turn==6 else 'auto')
        if MODEL_THINKING in ('enabled','disabled'):
            parameters['thinking']={'type':MODEL_THINKING}
        if MODEL_REASONING_EFFORT in ('low','high','max'):
            parameters['reasoning_effort']=MODEL_REASONING_EFFORT
        body=json.dumps(parameters,ensure_ascii=False).encode()
        url=MODEL_URL.rstrip('/')
        if not url.endswith('/chat/completions'):
            url+='/chat/completions'
        req=urllib.request.Request(url,body,{'Authorization':'Bearer '+MODEL_KEY,'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=180 if role_id in LONG_TIMEOUT_ROLES else 45) as res: return json.load(res)
    raw=None
    try:
        for turn in range(7):
            if tools and turn==6:messages.append({'role':'user','content':get_prompt('model.tool_budget_exhausted')})
            for attempt in range(3):
                _raise_if_paused(context)
                requested_at=datetime.now(timezone.utc).isoformat()
                try:
                    raw=await asyncio.to_thread(request)
                    break
                except urllib.error.HTTPError as exc:
                    context.store.append_event(context.task_id,{'type':'model_request_error','invocation_id':invocation_id,'role':role_id,'model':MODEL_NAME,'status_code':exc.code,'usage':'unknown','reason':classify_model_error(exc)})
                    if exc.code not in (429,500,502,503,504) or attempt==2:raise
                    await asyncio.sleep(2 ** attempt)
                except (urllib.error.URLError,TimeoutError) as exc:
                    context.store.append_event(context.task_id,{'type':'model_request_error','invocation_id':invocation_id,'role':role_id,'model':MODEL_NAME,'error':type(exc).__name__,'usage':'unknown','reason':classify_model_error(exc)})
                    if attempt==2: raise
                    await asyncio.sleep(2 ** attempt)
            from .usage import record_response
            usage_event_id=record_response(context,role_id,raw,invocation_id,turn,requested_at)
            audit=context.store.put_artifact(context.task_id,'model_exchange',{'role':role_id,'messages':messages,'response':raw})
            context.store.append_event(context.task_id,{'type':'model_exchange','role':role_id,'ref':audit,'turn':turn+1,'usage_event_id':usage_event_id,'invocation_id':invocation_id})
            message=(raw.get('choices') or [{}])[0].get('message') or {}
            if not message.get('tool_calls'):break
            if not tools or tool_executor is None or turn==6:raise ValueError('tool_round_limit_or_not_allowed')
            if len(message['tool_calls'])>4:raise ValueError('too_many_tools_per_round')
            messages.append({'role':'assistant',**{k:v for k,v in message.items() if k in ('content','tool_calls')}})
            for call in message['tool_calls']:
                fn=call['function'];result=await tool_executor(fn['name'],json.loads(fn['arguments']))
                messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(result,ensure_ascii=False)})
        choices=raw.get('choices')
        if not isinstance(choices,list) or not choices or not isinstance(choices[0],dict):
            raise ModelUnavailable('invalid_model_response')
        content=(choices[0].get('message') or {}).get('content')
        if not content:
            raise ModelUnavailable('empty_model_content')
        value=response_model.model_validate_json(content)
        context.store.append_event(context.task_id,{'type':'model_call','role':role_id,'status':'ok','elapsed_ms':int((time.monotonic()-started)*1000),'usage':raw.get('usage')})
        return value
    except Exception as e:
        context.store.append_event(context.task_id,{'type':'model_call','role':role_id,'status':'error','error':type(e).__name__,'reason':classify_model_error(e),'elapsed_ms':int((time.monotonic()-started)*1000),'usage':raw.get('usage') if isinstance(raw,dict) else 'unknown',
            'finish_reason':(raw['choices'][0].get('finish_reason') if isinstance(raw,dict) and isinstance(raw.get('choices'),list) and raw['choices'] and isinstance(raw['choices'][0],dict) else None)})
        raise

