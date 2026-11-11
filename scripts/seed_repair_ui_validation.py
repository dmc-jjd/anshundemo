"""Create an explicitly simulated three-round failure for UI verification."""
import asyncio,json,sys,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage import Store
from app.schemas import TaskState
from app.workflow import Dependencies,run_template


async def main():
    root=Path('data/ui-fixtures');root.mkdir(exist_ok=True)
    paths=[]
    for i,text in enumerate(('模拟报告：交通管理问题较多。','模拟报告：市场监管问题较多。','模拟报告：教育管理问题较多。')):
        p=root/f'模拟报告{i+1}.docx'
        with zipfile.ZipFile(p,'w') as z:z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'+text+'</w:t></w:r></w:p></w:body></w:document>')
        paths.append(str(p.resolve()))
    store=Store();task_id='ui-three-round-validation'
    if any(t.id==task_id for t in store.list_tasks()):
        task_id+='-'+__import__('uuid').uuid4().hex[:6]
    store.put_task(TaskState(id=task_id,kind='template',phase='queued',metadata={'paths':paths,'simulation':True}))
    async def analyst(role,payload):
        await asyncio.sleep(.05)
        sources=[{'report_id':d['id'],'block':d['blocks'][0]['index']} for d in payload['source_reports']]
        return {'summary':'模拟统计类别字段的责任冲突','blocks':[{'index':0,'kind':'paragraph','purpose':'模拟类别统计','parts':[{'field':'b0_categories'}],'sources':sources}],
            'fields':[{'id':'b0_categories','display_name':'模拟高发问题类别','owner':'writer','kind':'list','source_type':'statistics','semantic':'模拟本月高发类别列表','rule':'按当月统计条数降序列出类别','format':'顿号分隔文字','missing_policy':'block','reason':'模拟三轮纠正失败，验证人工入口','binding':None,
                       'sources':[{**source,'text':d['blocks'][0]['text']} for source,d in zip(sources,payload['source_reports'])]}],
            'unresolved_items':[]}
    result=await run_template(Dependencies(store,analyst),task_id)
    assert result.phase=='template_manual_review',result.metadata.get('template_error')
    Path('data/ui-repair-task.txt').write_text(task_id,encoding='utf-8')
    print(json.dumps({'task_id':task_id,'phase':result.phase,'simulation':True}))


if __name__=='__main__':asyncio.run(main())
