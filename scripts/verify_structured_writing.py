"""Run writing ONLY on an isolated SQLite snapshot; never modify live facts."""
import asyncio,hashlib,json,os,sqlite3,sys,time,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

async def main():
    from app.storage import Store
    from app.workflow import Dependencies
    from app.structured_writer import write_structured_preview
    from app.structured_template import render_structured_docx
    task_id='5108c8a9871a4ae5a97aab6dacd915ff'
    target=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'data'/('writing-verification-'+time.strftime('%Y%m%d-%H%M%S'))
    if not target.exists():
        target.mkdir()
        with sqlite3.connect('file:'+str(ROOT/'data/demo.sqlite3')+'?mode=ro',uri=True) as source:
            with sqlite3.connect(target/'demo.sqlite3') as dest:source.backup(dest)
    store=Store(target);state=store.get_task(task_id);facts_before=store.get_artifact(state.fact_ref)
    print('COPY',target,flush=True)
    started=time.monotonic();state=await write_structured_preview(Dependencies(store),task_id)
    assert store.get_artifact(state.fact_ref)==facts_before
    draft=store.get_artifact(state.draft_ref);template=store.get_artifact(state.template_ref)
    charts={name:store.get_artifact(ref) for name,ref in draft['chart_refs'].items()}
    output=target/'10月报告-写作验证草稿.docx'
    output.write_bytes(render_structured_docx(template,draft['slot_values'],set(draft['evidence_refs']),charts=charts))
    for name,payload in charts.items():
        import base64
        (target/(name+'.png')).write_bytes(base64.b64decode(payload['png_base64']))
    model_events=[e for e in store.events(task_id) if e['type']=='model_call' and e.get('role')=='writer']
    summary={'copy_root':str(target),'task_id':task_id,'fact_ref':state.fact_ref,'draft_ref':state.draft_ref,
             'elapsed_seconds':round(time.monotonic()-started,2),'filled':len(draft['slot_values']),
             'missing':state.metadata['missing_fields'],'issues':state.metadata['writer_issues'],
             'charts':list(charts),'preview_only':state.metadata['preview_only'],'output':str(output),
             'fact_unchanged':True,'writer_calls_total_including_old':len(model_events),
             'last_usage':[e.get('usage') for e in model_events[-6:]]}
    (target/'result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=True),flush=True)
if __name__=='__main__':asyncio.run(main())
