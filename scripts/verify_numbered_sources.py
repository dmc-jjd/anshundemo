"""Real-model writing validation on an isolated copy; no live draft changes."""
import asyncio,copy,json,sqlite3,sys,time,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.storage import Store
from app.workflow import Dependencies,run_writing_graph

async def main():
    tid=sys.argv[1] if len(sys.argv)>1 else 'fd74945d3561454ca33f06881ef5818c'
    root=ROOT/'data'/('numbered-source-validation-'+time.strftime('%Y%m%d-%H%M%S'));root.mkdir()
    with sqlite3.connect(ROOT/'data/demo.sqlite3') as original,sqlite3.connect(root/'demo.sqlite3') as target:original.backup(target)
    store=Store(root);state=store.get_task(tid);draft=store.get_artifact(state.draft_ref);template=store.get_artifact(state.template_ref);fact=store.get_artifact(state.fact_ref)
    protected={f['id'] for f in template['fields'] if f['owner']=='data'}|{key for key,val in draft['slot_values'].items() if 'human_edit' in val['source_refs']}
    targets=[key for key in ('b17_representative_news','b40_analysis_paragraph','monthly_recommendations') if key not in protected]
    for key in targets:state.metadata.setdefault('writer_field_prompt_fingerprints',{})[key]='force-numbered-source-validation'
    store.put_task(state,state.revision);seq=store.events(tid)[-1]['seq'];started=time.monotonic()
    (root/'baseline.json').write_text(json.dumps({'task_id':tid,'draft_ref':draft['id'],'start_seq':seq,'fact_ref':state.fact_ref},ensure_ascii=False),encoding='utf-8')
    print('COPY '+str(root),flush=True)
    state=await run_writing_graph(Dependencies(store),tid);updated=store.get_artifact(state.draft_ref);events=store.events(tid,after=seq)
    assert store.get_artifact(state.fact_ref)==fact and all(updated['slot_values'][key]==draft['slot_values'][key] for key in protected)
    types=collections.Counter()
    def walk(value):
        if isinstance(value,list):
            for item in value:walk(item)
        elif isinstance(value,dict):
            for key,item in value.items():
                if key in ('source_refs','history_refs') and isinstance(item,list):types.update(type(n).__name__ for n in item)
                else:walk(item)
    for event in events:
        if event['type']=='model_exchange' and event.get('role')=='writer':
            raw=store.get_artifact(event['ref'])['response']['choices'][0]['message'].get('content')
            if raw:
                try:walk(json.loads(raw))
                except json.JSONDecodeError:pass
    catalogs=[e['ref'] for e in events if e['type']=='writer_source_catalog'];assert catalogs
    for key in targets:
        if key in updated['slot_values']:assert all(isinstance(ref,str) for ref in updated['slot_values'][key]['source_refs'])
    result={'task_id':tid,'copy_root':str(root),'elapsed_seconds':round(time.monotonic()-started,2),'phase':state.phase,'targets':targets,
        'missing':state.metadata.get('missing_fields',[]),'pending_source_fields':list(state.metadata.get('writer_pending_sources',{})),
        'writer_wire_citation_types':dict(types),'catalog_count':len(catalogs),'protected_fields_unchanged':True,
        'failed_url_count':len(state.metadata.get('historical_reader',{}).get('failed_urls',{})),
        'reader_fetch_count':state.metadata.get('historical_reader',{}).get('fetch_count',0),
        'model_calls':[{'role':e['role'],'status':e['status']} for e in events if e['type']=='model_call']}
    (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':asyncio.run(main())
