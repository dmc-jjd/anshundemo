"""Real model-driven search and writing on an isolated task snapshot."""
import asyncio,json,sqlite3,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.storage import Store
from app.workflow import Dependencies
from app.structured_writer import write_structured_preview
from app.section_two import role

async def main():
    target=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'data'/('section-two-writing-'+time.strftime('%Y%m%d-%H%M%S'))
    if not target.exists():
        target.mkdir()
        with sqlite3.connect('file:'+str(ROOT/'data/demo.sqlite3')+'?mode=ro',uri=True) as source:
            with sqlite3.connect(target/'demo.sqlite3') as dest:source.backup(dest)
    store=Store(target);tid=sys.argv[2] if len(sys.argv)>2 else '5108c8a9871a4ae5a97aab6dacd915ff';state=store.get_task(tid)
    old=store.get_artifact(state.draft_ref);fact_before=store.get_artifact(state.fact_ref)
    baseline_path=target/'baseline.json'
    if not baseline_path.exists():baseline_path.write_text(json.dumps({'task_id':tid,'start_seq':store.events(tid)[-1]['seq'],'recommendations':old['slot_values'].get('monthly_recommendations')},ensure_ascii=False),encoding='utf-8')
    protected={key:value for key,value in old['slot_values'].items() if key!='monthly_recommendations'}
    start_seq=json.loads(baseline_path.read_text(encoding='utf-8'))['start_seq'];started=time.monotonic()
    print('COPY',target,flush=True)
    state=await write_structured_preview(Dependencies(store),tid)
    state.phase='awaiting_final_review';store.put_task(state,state.revision)
    draft=store.get_artifact(state.draft_ref)
    assert all(draft['slot_values'].get(key)==value for key,value in protected.items())
    assert store.get_artifact(state.fact_ref)==fact_before
    history=store.get_artifact(state.metadata['historical_research_ref'])
    events=store.events(tid,after=start_seq)
    result={'task_id':tid,'start_seq':start_seq,'copy_root':str(target),'elapsed_seconds':round(time.monotonic()-started,2),'draft_ref':state.draft_ref,'fact_ref':state.fact_ref,
            'missing':state.metadata['missing_fields'],'issues':state.metadata['writer_issues'],
            'history_status':history['status'],'history_topics':[t['category'] for t in history['topics']],
            'compared_candidates':len((history.get('candidate_comparison') or {}).get('candidates',[])),
            'basis_types':[t.get('basis_type') for t in history['topics']],
            'new_web_successes':sum(e['type']=='web_usage' and e.get('billable',False) for e in events),
            'new_model_responses':sum(e['type']=='model_usage' for e in events),
            'second_section':{key:draft['slot_values'].get(key) for key in ('b40_analysis_paragraph','monthly_recommendations')}}
    (target/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True),flush=True)
if __name__=='__main__':asyncio.run(main())
