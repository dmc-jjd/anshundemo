"""Per-response token metering and explicit, configurable price estimates."""
import copy,json,uuid
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from urllib.parse import urlparse
from .config import MODEL_NAME,MODEL_URL

SOURCE='https://api-docs.deepseek.com/zh-cn/quick_start/pricing/'
PRICE_VERSION='deepseek-official-2026-11-08'
PRICES={
 'deepseek-flash':{'off_peak':{'cached_input':.02,'input':1,'output':4},'peak':{'cached_input':.04,'input':2,'output':8}},
 'deepseek-v4-pro':{'off_peak':{'cached_input':.15,'input':4.5,'output':13.5},'peak':{'cached_input':.30,'input':9,'output':27}}}
ALIASES={'deepseek-v4-flash':'deepseek-flash','deepseek-v4-flash-vision-exp':'deepseek-flash','DeepSeek-V4.1-Flash-1017':'deepseek-flash','DeepSeek-V4-Pro-0813':'deepseek-v4-pro'}

def configuration(store):
    path=store.root/'token-pricing.json'
    config=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'mode':'auto','currency':'CNY','source':SOURCE,'version':PRICE_VERSION,'models':copy.deepcopy(PRICES),'historical_model':None}
    config.setdefault('web_per_1000',{'search':5.,'fetch':5.})
    return config

def save_configuration(store,config):
    from pydantic import BaseModel,ConfigDict,Field
    from typing import Literal
    class Rates(BaseModel):
        model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
        cached_input:float=Field(ge=0,le=100000)
        input:float=Field(ge=0,le=100000)
        output:float=Field(ge=0,le=100000)
    class Price(BaseModel):
        model_config=ConfigDict(extra='forbid')
        off_peak:Rates
        peak:Rates
    class Settings(BaseModel):
        model_config=ConfigDict(extra='forbid')
        mode:Literal['auto','off_peak','peak']
        currency:Literal['CNY']='CNY'
        models:dict[str,Price]
        source:str=SOURCE
        version:str=PRICE_VERSION
        historical_model:str|None=None
        web_per_1000:dict[str,float]=Field(default_factory=lambda:{'search':5.,'fetch':5.})
    data=Settings.model_validate(config).model_dump();data['version']='user-configured'
    if data['historical_model'] and data['historical_model'] not in data['models']:raise ValueError('historical_pricing_model_missing')
    import math
    if set(data['web_per_1000'])!={'search','fetch'} or any(not math.isfinite(v) or not 0<=v<=100000 for v in data['web_per_1000'].values()):raise ValueError('invalid_web_pricing')
    path=store.root/'token-pricing.json';tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)
    return data

def normalized(raw):
    if not isinstance(raw,dict) or not isinstance(raw.get('prompt_tokens'),int) or not isinstance(raw.get('completion_tokens'),int):return None
    prompt=max(0,raw['prompt_tokens']);output=max(0,raw['completion_tokens'])
    hit=raw.get('prompt_cache_hit_tokens',(raw.get('prompt_tokens_details') or {}).get('cached_tokens'))
    if not isinstance(hit,int) and isinstance(raw.get('prompt_cache_miss_tokens'),int):hit=prompt-raw['prompt_cache_miss_tokens']
    known=isinstance(hit,int) and 0<=hit<=prompt
    hit=hit if known else 0
    return {'input_tokens':prompt,'output_tokens':output,'total_tokens':prompt+output,
            'cache_hit_tokens':hit,'cache_miss_tokens':prompt-hit,'cache_split_known':known,
            'reasoning_tokens':max(0,(raw.get('completion_tokens_details') or {}).get('reasoning_tokens') or 0)}

def record_response(context,role,raw,invocation_id,turn,started_at):
    request_id=uuid.uuid4().hex;usage=normalized(raw.get('usage'))
    context.store.append_event(context.task_id,{'type':'model_usage','request_id':request_id,'invocation_id':invocation_id,
        'role':role,'phase':context.store.get_task(context.task_id).phase,'model':raw.get('model') or MODEL_NAME,'provider_host':urlparse(MODEL_URL).hostname,
        'turn':turn+1,'requested_at':started_at,'usage':usage,'metered':usage is not None})
    return request_id

def band(at,mode):
    if mode in ('peak','off_peak'):return [mode]
    try:t=datetime.fromisoformat(at.replace('Z','+00:00')).astimezone(timezone(timedelta(hours=8)))
    except (ValueError,AttributeError):return ['off_peak','peak']
    hour=t.hour+t.minute/60
    # The official tariff exempts Chinese public holidays. Without a verified
    # holiday calendar, working-hour weekdays remain an explicit estimate range.
    return ['off_peak','peak'] if t.weekday()<5 and (9<=hour<12 or 14<=hour<18) else ['off_peak']

def estimate(item,config):
    usage=item.get('usage');model=ALIASES.get(item.get('model'),item.get('model'))
    if model=='unknown_historical':model=config.get('historical_model')
    rates=config['models'].get(model)
    official=item.get('provider_host')=='api.deepseek.com'
    custom=config.get('version')=='user-configured'
    if not usage or not rates or (not official and not custom):return None
    costs=[]
    for tariff in band(item.get('requested_at') or item['at'],config['mode']):
        rate=rates[tariff]
        for hit in ([usage['cache_hit_tokens']] if usage['cache_split_known'] else [0,usage['input_tokens']]):
            value=Decimal(hit)*Decimal(str(rate['cached_input']))+Decimal(usage['input_tokens']-hit)*Decimal(str(rate['input']))+Decimal(usage['output_tokens'])*Decimal(str(rate['output']))
            costs.append(float(value/Decimal(1000000)))
    return {'min':min(costs),'max':max(costs)}

def usage_items(store,task_id):
    events=store.events(task_id);items=[];pending={};unknown_requests=0
    for e in events:
        role=e.get('role','unknown');kind=e['type']
        if kind=='model_usage':
            items.append(e);pending[role]=True
        elif kind=='model_exchange' and not e.get('usage_event_id'):
            try:
                data=store.get_artifact(e['ref']);response=data['response']
                usage=normalized(response.get('usage'))
                items.append({'request_id':f'legacy-exchange-{e["seq"]}','role':role,'model':response.get('model') or 'unknown_historical',
                    'provider_host':'api.deepseek.com' if (response.get('model') or '').startswith(('deepseek','DeepSeek')) else None,
                    'phase':'template_model_reviewing' if role=='template_analyst' else 'writing' if role in ('writer','writer_data_planner') else 'analyzing',
                    'at':e['at'],'usage':usage,'historical':True})
                pending[role]=True
            except (KeyError,ValueError):unknown_requests+=1
        elif kind=='model_call':
            if e.get('status')=='synthetic_test':continue
            if pending.pop(role,False):continue
            usage=normalized(e.get('usage'))
            if usage:items.append({'request_id':f'legacy-call-{e["seq"]}','role':role,'model':e.get('model','unknown_historical'),
                'provider_host':e.get('provider_host'),'phase':'historical','at':e['at'],'usage':usage,'historical':True})
            elif e.get('status')!='unavailable':unknown_requests+=1
        elif kind=='model_request_error':unknown_requests+=1;pending[role]=True
    return items,unknown_requests

def task_usage(store,task_id):
    config=configuration(store);items,unknown=usage_items(store,task_id);rows={};total={'input_tokens':0,'output_tokens':0,'total_tokens':0,'cache_hit_tokens':0,'cache_miss_tokens':0,'reasoning_tokens':0}
    lower=upper=0.;unpriced=0
    for item in items:
        usage=item.get('usage');key=(item['role'],item.get('phase','unknown'),item['model'])
        row=rows.setdefault(key,{'role':key[0],'phase':key[1],'model':key[2],'requests':0,'input_tokens':0,'output_tokens':0,'total_tokens':0,'cost_min':0.,'cost_max':0.,'unpriced_requests':0})
        row['requests']+=1
        if usage:
            for k in total:total[k]+=usage.get(k,0)
            for k in ('input_tokens','output_tokens','total_tokens'):row[k]+=usage[k]
        else:unknown+=1
        cost=estimate(item,config)
        if cost:
            lower+=cost['min'];upper+=cost['max'];row['cost_min']+=cost['min'];row['cost_max']+=cost['max']
        else:unpriced+=1;row['unpriced_requests']+=1
    web=[e for e in store.events(task_id) if e['type']=='web_usage'];web_counts={kind:sum(e.get('operation')==kind and e.get('billable',False) for e in web) for kind in ('search','fetch')}
    web_cost=sum(count*config['web_per_1000'][kind]/1000 for kind,count in web_counts.items())
    return {**total,'requests':len(items),'unmetered_requests':unknown,'unpriced_requests':unpriced,
            'web_successful_requests':web_counts,'estimated_web_cost':web_cost,
            'estimated_cost_min':lower+web_cost,'estimated_cost_max':upper+web_cost,'currency':config['currency'],
            'price_source':config['source'],'price_version':config['version'],'price_mode':config['mode'],
            'rows':list(rows.values()),'note':'费用按当前配置单价估算，不是账单。每次HTTP响应只计一次；推理token已包含在输出中，不另计。历史未记录的调用无法补齐；未知模型不猜价格。工作日高峰若缺法定节假日日历，显示空闲至高峰区间。'}
