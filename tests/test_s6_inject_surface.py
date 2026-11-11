"""G-INJECT：证明 app/main.py 的 6 个注入属性在**请求期**被解析，而不是 import 期绑死。

`monkeypatch.setattr(main,'store',…)` 之所以对 15 个既有测试文件生效，靠的是
「路由函数体运行期按模块全局解析名字」。把领域组装下沉到 app/api_views/ 时，
若下沉层写 `from app.main import store`，名字会在 import 期绑死旧值、注入静默失效，
而任何 hasattr 断言都仍然为真。所以这里逐名打一次真实请求，断言新值确实被用到。
"""
import ast,io,zipfile
from pathlib import Path
from fastapi.testclient import TestClient
from app.schemas import TaskState
from app.storage import Store

INJECT_NAMES=['store','deps','UPLOADS','run_report_graph','export_docx','validate_draft']


class _Recorder:
    def __init__(self,result=None): self.calls=[]; self.result=result
    def __call__(self,*args,**kwargs): self.calls.append((args,kwargs)); return self.result


def _report_task_env(tmp_path,monkeypatch,**patch):
    """最小报告任务环境：uploads 里放好 f.xlsx，report-tasks 只建任务、不跑图。"""
    import app.main as main
    uploads=tmp_path/'uploads'; uploads.mkdir()
    (uploads/'f.xlsx').write_bytes(b'fixture; processing disabled')
    monkeypatch.setattr(main,'store',Store(tmp_path/'store'))
    monkeypatch.setattr(main,'UPLOADS',uploads)
    for name,value in patch.items(): monkeypatch.setattr(main,name,value)
    return main


def _approve_env(tmp_path,monkeypatch,structured,**patch):
    """最小 /approve 环境：只到 validate_draft / export_docx，止于 409 writing_review_required。"""
    import app.main as main
    store=Store(tmp_path/'store')
    fact=store.put_artifact('r','facts',{'metrics':{}})
    draft={'id':'d1','fact_ref':fact,'template_ref':'other','content_hash':'h1','sections':[],'slot_values':{}}
    if structured: draft['structured_template_ref']='tpl'
    draft_ref=store.put_artifact('r','draft_version',draft)
    store.put_task(TaskState(id='r',kind='report',phase='awaiting_final_review',fact_ref=fact,draft_ref=draft_ref,template_ref='other'))
    monkeypatch.setattr(main,'store',store)
    for name,value in patch.items(): monkeypatch.setattr(main,name,value)
    return main,draft


def test_store_is_used_from_module_global_at_request_time(tmp_path,monkeypatch):
    import app.main as main
    real=Store(tmp_path/'store'); seen=[]
    class _Spy:
        def __getattr__(self,name):
            seen.append(name); return getattr(real,name)
    monkeypatch.setattr(main,'store',_Spy())
    with TestClient(main.app) as client: response=client.get('/api/tasks')
    assert response.status_code==200,response.text
    assert 'list_tasks' in seen


def test_uploads_is_used_from_module_global_at_request_time(tmp_path,monkeypatch):
    import app.main as main
    uploads=tmp_path/'uploads'; uploads.mkdir()
    monkeypatch.setattr(main,'UPLOADS',uploads)
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as archive: archive.writestr('a.txt','x')
    with TestClient(main.app) as client:
        response=client.post('/api/files',files={'file':('a.xlsx',buffer.getvalue(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert response.status_code==200,response.text
    assert response.json()['path']==str(uploads/f"{response.json()['id']}.xlsx")
    assert response.json()['readable'] is True


def test_deps_is_used_from_module_global_at_request_time(tmp_path,monkeypatch):
    sentinel=object(); recorder=_Recorder()
    main=_report_task_env(tmp_path,monkeypatch,deps=sentinel,run_report_graph=recorder)
    with TestClient(main.app) as client:
        response=client.post('/api/report-tasks',json={'file_ids':['f'],'template_ref':'anshun-monthly-colored'})
    assert response.status_code==200,response.text
    assert recorder.calls and recorder.calls[0][0][0] is sentinel


def test_run_report_graph_is_used_from_module_global_at_request_time(tmp_path,monkeypatch):
    recorder=_Recorder()
    main=_report_task_env(tmp_path,monkeypatch,run_report_graph=recorder)
    with TestClient(main.app) as client:
        response=client.post('/api/report-tasks',json={'file_ids':['f'],'template_ref':'anshun-monthly-colored'})
    assert response.status_code==200,response.text
    assert len(recorder.calls)==1 and recorder.calls[0][0][1]==response.json()['id']


def test_validate_draft_is_used_from_module_global_at_request_time(tmp_path,monkeypatch):
    recorder=_Recorder(result=[])
    main,_=_approve_env(tmp_path,monkeypatch,False,validate_draft=recorder)
    with TestClient(main.app) as client:
        response=client.post('/api/tasks/r/approve',json={'draft_hash':'h1'})
    assert len(recorder.calls)==1 and recorder.calls[0][0][0].content_hash=='h1'
    assert response.status_code==409 and response.json()['detail']=='writing_review_required'


def test_export_docx_is_used_from_module_global_at_request_time(tmp_path,monkeypatch):
    recorder=_Recorder()
    main,draft=_approve_env(tmp_path,monkeypatch,True,validate_draft=_Recorder(result=[]),export_docx=recorder)
    with TestClient(main.app) as client:
        response=client.post('/api/tasks/r/approve',json={'draft_hash':'h1'})
    assert len(recorder.calls)==1
    args,kwargs=recorder.calls[0]
    assert args[0]['content_hash']=='h1' and args[1]=={'metrics':{}} and args[2] is None and args[3]=='final' and args[4]==[]
    assert 'local_store' in kwargs
    assert response.status_code==409 and response.json()['detail']=='writing_review_required'


def test_inject_names_exist_and_api_views_do_not_bind_main_at_import_time():
    import app.main as main
    assert all(hasattr(main,name) for name in INJECT_NAMES)
    offenders=[]
    for path in (Path(__file__).resolve().parents[1]/'app'/'api_views').glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node,ast.ImportFrom):
                module=node.module or ''
                names=[alias.name for alias in node.names]
                if module in ('app.main','main','app') or (not module and 'main' in names):
                    offenders.append(f'{path.name}:{node.lineno}')
            elif isinstance(node,ast.Import):
                offenders.extend(f'{path.name}:{node.lineno}' for alias in node.names if alias.name=='app.main')
    assert offenders==[]
