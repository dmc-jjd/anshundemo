import pytest
from fastapi.testclient import TestClient
import app.main as main
from app.storage import Store
from app.schemas import TaskState


def fixture(tmp_path,monkeypatch):
    store=Store(tmp_path/'data');monkeypatch.setattr(main,'store',store)
    return store


def test_report_hard_delete_files_rows_and_idempotency(tmp_path,monkeypatch):
    store=fixture(tmp_path,monkeypatch)
    task=TaskState(id='report-delete',kind='report',phase='awaiting_review')
    ref=store.put_artifact(task.id,'computed',{'count':5});task.result_refs={'result':ref};store.put_task(task)
    store.append_event(task.id,{'type':'test'});store.put_review_draft(task.id,ref,{'rows':[]})
    store.idempotent('create-report',task.id)
    sidecar=store.files/(ref+'.docx');sidecar.write_bytes(b'export')
    upload=store.root/'uploads';upload.mkdir();(upload/'shared.xlsx').write_bytes(b'input')
    with TestClient(main.app) as client:
        response=client.delete('/api/tasks/'+task.id)
        assert response.status_code==200,response.text
        assert response.json()['hard']
        assert client.get('/api/tasks/'+task.id).status_code==404
        assert client.delete('/api/tasks/'+task.id).status_code==404
    assert not sidecar.exists() and not (store.files/(ref+'.json')).exists()
    assert (upload/'shared.xlsx').exists() and store.events(task.id)==[]
    with store.connect() as c:
        for table in ('tasks','events','review_drafts','artifacts'):
            assert c.execute('SELECT count(*) FROM '+table).fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM idempotency').fetchone()[0]==0


def test_shared_artifact_references_survive_report_delete(tmp_path,monkeypatch):
    store=fixture(tmp_path,monkeypatch)
    ref=store.put_artifact('report-delete','shared',{'facts':12})
    unique=store.put_artifact('report-delete','private',{'private':True})
    store.put_task(TaskState(id='report-delete',kind='report',phase='approved',result_refs={'x':ref,'y':unique}))
    store.put_task(TaskState(id='report-keep',kind='report',phase='awaiting_review',result_refs={'x':ref}))
    with TestClient(main.app) as client:
        response=client.delete('/api/tasks/report-delete');assert response.status_code==200,response.text
    assert store.get_artifact(ref)=={'facts':12}
    with pytest.raises(KeyError):store.get_artifact(unique)
    assert store.get_task('report-keep')


@pytest.mark.parametrize('phase',['queued','processing','analyzing','writing','template_model_reviewing'])
def test_running_task_delete_rejected(tmp_path,monkeypatch,phase):
    store=fixture(tmp_path,monkeypatch)
    store.put_task(TaskState(id='busy',kind='report',phase=phase))
    with TestClient(main.app) as client:
        response=client.delete('/api/tasks/busy')
    assert response.status_code==409 and response.json()['detail']=='task_still_running'
    assert store.get_task('busy')


def test_generic_template_delete_reuses_reference_protection(tmp_path,monkeypatch):
    from test_template_delete import _confirmed_task
    store=fixture(tmp_path,monkeypatch);task,ref=_confirmed_task(store,tmp_path)
    store.put_task(TaskState(id='consumer',kind='report',phase='approved',template_ref=ref))
    with TestClient(main.app) as client:
        denied=client.delete('/api/tasks/'+task.id);assert denied.status_code==409
        assert denied.json()['detail']=='template_in_use'
        result=client.delete('/api/tasks/'+task.id+'?force=true');assert result.status_code==200
    assert store.get_artifact(ref)


def test_package_router_deletes_only_owning_store(tmp_path):
    from core.package_store import PackageStores
    from app.api_views.task_delete import delete_task
    router=PackageStores(tmp_path/'packages')
    left=router.store_for('left');right=router.store_for('right')
    left.put_task(TaskState(id='left-task',package='left',kind='report',phase='awaiting_review'))
    right.put_task(TaskState(id='right-task',package='right',kind='report',phase='awaiting_review'))
    router.get_task('left-task')
    error,payload=delete_task(router,'left-task')
    assert error is None and payload['hard']
    with pytest.raises(KeyError):router.get_task('left-task')
    assert right.get_task('right-task')


def test_transitive_reference_survives_deletion(tmp_path,monkeypatch):
    store=fixture(tmp_path,monkeypatch)
    leaf=store.put_artifact('remove','leaf',{'value':1})
    parent=store.put_artifact('remove','parent',{'nested':[leaf]})
    store.put_task(TaskState(id='remove',kind='report',phase='approved'))
    store.put_task(TaskState(id='survivor',kind='report',phase='approved',result_refs={'parent':parent}))
    store.delete_task('remove')
    assert store.get_artifact(leaf)=={'value':1} and store.get_artifact(parent)['nested']==[leaf]
