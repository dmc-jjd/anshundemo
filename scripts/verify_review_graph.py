"""Run the compiled writing graph on an isolated snapshot, using real models."""
import asyncio,json,sqlite3,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.storage import Store
from app.workflow import Dependencies,run_writing_graph
from app.reviewers import review_ready,active_issues

async def main():
    tid=sys.argv[1] if len(sys.argv)>1 else 'd2511637eb694125a92616d2a276bd08'
    review_only='--review-only' in sys.argv
    target=ROOT/'data'/('review-graph-'+time.strftime('%Y%m%d-%H%M%S'));target.mkdir()
    with sqlite3.connect(ROOT/'data/demo.sqlite3') as original,sqlite3.connect(target/'demo.sqlite3') as copy:original.backup(copy)
    store=Store(target);state=store.get_task(tid);before=store.get_artifact(state.draft_ref);fact=store.get_artifact(state.fact_ref);template=store.get_artifact(state.template_ref)
    data_ids={f['id'] for f in template['fields'] if f['owner']=='data'}
    protected={k:v for k,v in before['slot_values'].items() if k in data_ids or 'human_edit' in v.get('source_refs',[])}
    first_seq=store.events(tid)[-1]['seq'];start=time.monotonic()
    baseline={'task_id':tid,'start_seq':first_seq,'revision':state.revision,'draft_ref':state.draft_ref,'fact_ref':state.fact_ref,'template_ref':state.template_ref,'slot_values':before['slot_values']}
    (target/'baseline.json').write_text(json.dumps(baseline,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'data/current-review-graph-root.txt').write_text(str(target),encoding='utf-8')
    print('COPY '+str(target),flush=True)
    state=await run_writing_graph(Dependencies(store),tid,review_only)
    draft=store.get_artifact(state.draft_ref);events=store.events(tid,after=first_seq)
    assert store.get_artifact(state.fact_ref)==fact
    assert all(draft['slot_values'].get(k)==v for k,v in protected.items())
    result={'task_id':tid,'copy_root':str(target),'elapsed_seconds':round(time.monotonic()-start,2),'fact_ref':state.fact_ref,'draft_ref':state.draft_ref,
        'phase':state.phase,'missing':state.metadata.get('missing_fields',[]),'review_ready':review_ready(state,draft['content_hash']),
        'review_report':state.metadata.get('review_report'),'run':state.metadata.get('writing_review_run'),
        'issues':[{'id':i['id'],**i['details']} for i in active_issues(state)],
        'nodes':[e['node'] for e in events if e['type']=='graph_node' and e['status']=='started'],
        'model_calls':[{'role':e['role'],'status':e['status']} for e in events if e['type']=='model_call'],
        'protected_fields_unchanged':True,'second_section':{k:draft['slot_values'].get(k) for k in ('b40_analysis_paragraph','monthly_recommendations')}}
    (target/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='second_section'},ensure_ascii=False),flush=True)

if __name__=='__main__':asyncio.run(main())
