"""Resume an isolated real-model trial; never touches the production task."""
import asyncio,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.storage import Store
from app.workflow import Dependencies,run_writing_graph
from app.reviewers import active_issues,review_ready

async def main():
    root=Path(sys.argv[1]).resolve()
    if root.parent!=ROOT/'data' or not root.name.startswith('review-graph-'):raise ValueError('isolated_snapshot_required')
    store=Store(root);baseline=json.loads((root/'baseline.json').read_text(encoding='utf-8'));tid=baseline['task_id']
    started=time.monotonic();seq=store.events(tid)[-1]['seq']
    state=await run_writing_graph(Dependencies(store),tid,review_only='--review-only' in sys.argv)
    draft=store.get_artifact(state.draft_ref);template=store.get_artifact(state.template_ref)
    protected={f['id'] for f in template['fields'] if f['owner']=='data'}|{k for k,v in baseline['slot_values'].items() if 'human_edit' in v['source_refs']}
    assert all(draft['slot_values'][key]==baseline['slot_values'][key] for key in protected)
    events=store.events(tid,after=seq)
    result={'task_id':tid,'elapsed_seconds':round(time.monotonic()-started,2),'phase':state.phase,'draft_ref':state.draft_ref,
        'missing':state.metadata['missing_fields'],'review_ready':review_ready(state,draft['content_hash']),
        'report':state.metadata.get('review_report'),'run':state.metadata.get('writing_review_run'),
        'issues':[{'id':i['id'],**i['details']} for i in active_issues(state)],'protected_fields_unchanged':True,
        'nodes':[e['node'] for e in events if e['type']=='graph_node' and e['status']=='started'],
        'model_calls':[{'role':e['role'],'status':e['status']} for e in events if e['type']=='model_call']}
    (root/'continued-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':asyncio.run(main())
