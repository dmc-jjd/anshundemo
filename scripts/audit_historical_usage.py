"""Read-only audit of historical research runs; makes no model/web requests."""
import json,sys
from pathlib import Path
from datetime import datetime
from collections import Counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage import Store
from app.usage import estimate,configuration

def stamp(value):return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()

def audit(root,task_id):
    store=Store(Path(root));events=store.events(task_id);config=configuration(store)
    sessions=[];current=None
    for e in events:
        if e['type']=='historical_research_started':
            if current is None:current={'start':e['at'],'events':[]}
        if current is not None:current['events'].append(e)
        if e['type']=='historical_research_result' and current:
            current.update(end=e['at'],status=e['status'],topic_count=e['topic_count']);sessions.append(current);current=None
    if current:sessions.append({**current,'end':current['events'][-1]['at'],'status':'incomplete'})
    output=[]
    for index,session in enumerate(sessions,1):
        es=session.pop('events');usage=[e for e in es if e['type']=='model_usage' and e.get('role')=='historical_researcher']
        web=[e for e in es if e['type']=='web_usage'];counts=Counter(e['operation'] for e in web if e.get('billable'))
        tools=[e for e in es if e['type']=='tool_result' and e.get('tool') in ('search_historical_web','fetch_historical_page')]
        costs=[estimate(e,config) for e in usage];known=[c for c in costs if c]
        intervals=[(stamp(e['requested_at']),stamp(e['at'])) for e in usage if e.get('requested_at')]
        # A role's HTTP responses are sequential. Search/Fetch are separate from
        # these model HTTP intervals, so no overlap is added to its model time.
        output.append({'run':index,**session,'wall_seconds':round(stamp(session['end'])-stamp(session['start']),3),
            'model_seconds':round(sum(b-a for a,b in intervals),3),'web_seconds':round(sum(e.get('elapsed_ms',0) for e in web)/1000,3),
            'tool_dispatch_seconds':round(sum(e.get('elapsed_ms',0) for e in tools)/1000,3),'tool_calls':len(tools),
            'model_responses':len(usage),'unmetered_model_responses':sum(not e.get('usage') for e in usage),
            'input_tokens':sum((e.get('usage') or {}).get('input_tokens',0) for e in usage),
            'output_tokens':sum((e.get('usage') or {}).get('output_tokens',0) for e in usage),
            'cache_hit_tokens':sum((e.get('usage') or {}).get('cache_hit_tokens',0) for e in usage),
            'model_cny_min':round(sum(c['min'] for c in known),6),'model_cny_max':round(sum(c['max'] for c in known),6),
            'unpriced_responses':len(costs)-len(known),'successful_search':counts['search'],'successful_fetch':counts['fetch'],
            'web_errors':sum(e.get('status')!='ok' for e in web),
            'web_cny':round(sum(counts[k]*config['web_per_1000'][k]/1000 for k in counts),6),
            'model_errors':sum(e['type']=='model_request_error' and e.get('role')=='historical_researcher' for e in es),
            'rounds':[{'round':e['round'],'topic_count':e.get('topic_count'),'errors':e.get('errors')} for e in es if e['type']=='historical_validation']})
    totals={key:round(sum(r[key] for r in output),6) for key in ('wall_seconds','model_seconds','web_seconds','tool_dispatch_seconds','tool_calls','model_responses','input_tokens','output_tokens','cache_hit_tokens','model_cny_min','model_cny_max','successful_search','successful_fetch','web_cny','web_errors','model_errors')}
    return {'database':str(store.db.resolve()),'task_id':task_id,'source':'persisted research events only; no new requests','pricing':{'version':config['version'],'mode':config['mode'],'currency':config['currency']},'runs':output,'totals':totals}

if __name__=='__main__':
    result=audit(sys.argv[1] if len(sys.argv)>1 else 'data/section-two-writing-20261108-123555',sys.argv[2] if len(sys.argv)>2 else '5108c8a9871a4ae5a97aab6dacd915ff')
    target=Path('data/historical-usage-audit-20261108.json');target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
