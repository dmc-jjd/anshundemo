"""Compare exactly two reports and persist a reviewable template candidate."""
import argparse,asyncio,json,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.config import DATA
from app.storage import Store
from app.schemas import TaskState
from app.workflow import Dependencies,run_template_graph

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('reports',nargs=2,type=Path)
    args=parser.parse_args()
    store=Store(DATA);task_id=uuid.uuid4().hex
    store.put_task(TaskState(id=task_id,kind='template',phase='queued',metadata={'paths':[str(p.resolve()) for p in args.reports]}))
    asyncio.run(run_template_graph(Dependencies(store),task_id))
    state=store.get_task(task_id)
    if state.metadata.get('structured_template_ref'):
        definition=store.get_artifact(state.metadata['structured_template_ref'])
        (DATA/'structured-template-review.json').write_text(json.dumps(definition,ensure_ascii=False,indent=2),encoding='utf-8')
        (DATA/'structured-template-writer.schema.json').write_text(json.dumps(definition['writer_schema'],ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'task_id':task_id,'phase':state.phase,'source_reports':len(definition['source_reports']),
                          'fields':len(definition['fields']),'writer_fields':sum(f['owner']=='writer' for f in definition['fields']),
                          'review_items':len(definition['review_items'])},ensure_ascii=True))
    else:print(json.dumps({'task_id':task_id,'phase':state.phase,'error':'candidate_not_created'}))

if __name__=="__main__":
    main()
