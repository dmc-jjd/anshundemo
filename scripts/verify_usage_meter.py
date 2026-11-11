"""One minimal real-provider call in an isolated store, without report changes."""
import asyncio,json,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.storage import Store
from app.schemas import TaskState
from app.structured_writer import StructuredAnswers
from app.model_client import invoke_agent
from app.tool_executor import RunContext
from app.usage import task_usage

async def main():
    store=Store(ROOT/'data/usage-meter-validation');task_id='usage-'+uuid.uuid4().hex
    store.put_task(TaskState(id=task_id,kind='report',phase='writing',metadata={'simulation':True,'purpose':'real HTTP token metering smoke check'}))
    await invoke_agent('writer',{'instruction':'验证用量计量。只返回 {"values":{}}，不要生成报告。'},StructuredAnswers,RunContext(store,task_id,phase='writing'))
    result=task_usage(store,task_id)
    assert result['requests']==1 and result['total_tokens']>0 and result['unpriced_requests']==0
    (store.root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['requests','input_tokens','output_tokens','total_tokens','estimated_cost_min','estimated_cost_max']},ensure_ascii=True))
if __name__=='__main__':asyncio.run(main())
