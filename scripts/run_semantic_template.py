"""Run real historical reports through semantic review; never confirms a template."""
import asyncio,json,sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage import Store
from app.schemas import TaskState
from app.workflow import Dependencies,run_template


async def main():
    store=Store()
    if len(sys.argv)>1:
        task_id=sys.argv[1]
    else:
        paths=[str(p.resolve()) for month in (6,7,8) for p in Path.cwd().glob(f'2026年{month}月*报告.docx')]
        if len(paths)!=3:raise ValueError('expected real June, July, August reports')
        task_id=uuid.uuid4().hex
        store.put_task(TaskState(id=task_id,kind='template',phase='queued',metadata={'paths':paths}))
    Path('data/current-template-task.txt').write_text(task_id,encoding='utf-8')
    print('task_id='+task_id,flush=True)
    result=await run_template(Dependencies(store),task_id)
    print(json.dumps({'task_id':task_id,'phase':result.phase,'candidate_ref':result.metadata.get('structured_template_ref'),
                      'error':result.metadata.get('template_error')},ensure_ascii=False),flush=True)


if __name__=='__main__':asyncio.run(main())
