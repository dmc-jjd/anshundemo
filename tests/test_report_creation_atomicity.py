from concurrent.futures import ThreadPoolExecutor

import pytest

from core.package_store import PackageStores
from core.schemas import TaskState
from core.storage import Store
from test_report_package_regressions import isolated


def state(task_id='r', package='anshun_monthly'):
    return TaskState(id=task_id, kind='report', phase='queued', package=package)


@pytest.mark.parametrize('stage', ['key', 'parameters', 'task'])
def test_creation_failure_rolls_back_rows_files_and_key(tmp_path, stage):
    store = Store(tmp_path)
    connection = store.connect()
    try:
        sql = {
            'key': "CREATE TRIGGER reject_create BEFORE INSERT ON idempotency BEGIN SELECT RAISE(ABORT, 'injected'); END",
            'parameters': "CREATE TRIGGER reject_create BEFORE INSERT ON artifacts BEGIN SELECT RAISE(ABORT, 'injected'); END",
            'task': "CREATE TRIGGER reject_create BEFORE INSERT ON tasks BEGIN SELECT RAISE(ABORT, 'injected'); END",
        }[stage]
        connection.execute(sql)
        connection.commit()
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError, match='injected'):
            store.create_report_once(state(), {'issue_number': 1}, 'report:key')
        for table in ('tasks', 'artifacts', 'idempotency'):
            assert connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] == 0
        assert list(store.files.iterdir()) == []
        connection.execute('DROP TRIGGER reject_create')
        connection.commit()
        result = store.create_report_once(state('retry'), {'issue_number': 1}, 'report:key')
        assert result.id == 'retry'
        assert store.get_artifact(result.metadata['report_parameters_ref'])['parameters'] == {'issue_number': 1}
    finally:
        connection.close()


def test_parallel_creation_same_key_has_one_task_and_parameter_owner(tmp_path):
    store = Store(tmp_path)
    def create(i):
        return store.create_report_once(state(str(i)), {'issue_number': 7}, 'report:key')
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(create, range(2)))
    assert results[0].id == results[1].id
    assert len(store.list_tasks()) == 1
    assert store.artifact_belongs_to_task(results[0].metadata['report_parameters_ref'], results[0].id)
    assert len(list(store.files.iterdir())) == 1


def test_key_and_parameters_stay_in_explicit_package(tmp_path):
    stores = PackageStores(tmp_path)
    for package in ('anshun_monthly', 'ruyuan_yuebao'):
        result = stores.create_report_once(state(package, package), {'issue_number': 2}, 'report:same')
        assert result.id == package and stores.get_task(result.id).package == package
        assert stores.store_for(package).artifact_belongs_to_task(result.metadata['report_parameters_ref'], package)


def test_rollback_retains_preexisting_shared_artifact(tmp_path):
    store = Store(tmp_path)
    payload = {'parameters': {'issue_number': 1}, 'source': 'report_processing_form'}
    ref = store.put_artifact('old', 'report_parameters', payload)
    with store.connect() as connection:
        connection.execute("CREATE TRIGGER reject_create BEFORE INSERT ON tasks BEGIN SELECT RAISE(ABORT, 'injected'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        store.create_report_once(state(), {'issue_number': 1}, 'report:key')
    assert store.get_artifact(ref) == payload
    assert store.artifact_belongs_to_task(ref, 'old')


def test_http_idempotent_creation_enqueues_once(isolated, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main
    store, refs, queued = isolated
    monkeypatch.setattr(main, 'UPLOADS', store.uploads_for('anshun_monthly'))
    body = {'package': 'ruyuan_yuebao', 'file_ids': ['fixture'],
            'template_ref': refs['ruyuan_yuebao'], 'issue_number': 1}
    with TestClient(main.app) as client:
        first = client.post('/api/report-tasks', json=body, headers={'idempotency-key': 'same'})
        second = client.post('/api/report-tasks', json=body, headers={'idempotency-key': 'same'})
    assert first.status_code == second.status_code == 200
    assert first.json()['id'] == second.json()['id'] and queued == [first.json()['id']]


def test_failed_queue_registration_is_visible_and_retryable_without_new_task(tmp_path):
    from app.api_views.report_creation import enqueue_report
    store = Store(tmp_path)
    created = store.create_report_once(state(), {}, 'report:key')
    class Queue:
        calls = []
        fail = True
        def add_task(self, *args):
            if self.fail:raise RuntimeError('queue unavailable')
            self.calls.append(args)
    queue = Queue()
    with pytest.raises(RuntimeError, match='queue unavailable'):
        enqueue_report(store, created, queue, 'runner', 'deps')
    assert store.get_task('r').metadata['report_dispatch'] == 'failed'
    retry = store.create_report_once(state('other'), {}, 'report:key')
    assert retry.id == 'r' and len(store.list_tasks()) == 1
    queue.fail = False
    result = enqueue_report(store, retry, queue, 'runner', 'deps')
    assert result.metadata['report_dispatch'] == 'registered'
    assert queue.calls == [('runner', 'deps', 'r')]


def test_file_replace_failure_releases_claim_and_removes_staging_file(tmp_path, monkeypatch):
    import core.storage as storage
    store = Store(tmp_path)
    def fail(*args):raise OSError('disk unavailable')
    with monkeypatch.context() as patch:
        patch.setattr(storage.os, 'replace', fail)
        with pytest.raises(OSError, match='disk unavailable'):
            store.create_report_once(state(), {'issue_number': 1}, 'report:key')
    assert list(store.files.iterdir()) == [] and store.list_tasks() == []
    assert store.create_report_once(state('retry'), {}, 'report:key').id == 'retry'


def test_legacy_dangling_claim_can_be_retried(tmp_path):
    store = Store(tmp_path)
    store.idempotent('report:key', 'nonexistent')
    assert store.create_report_once(state(), {}, 'report:key').id == 'r'


def test_identical_parameters_for_distinct_tasks_have_owned_references(tmp_path):
    store = Store(tmp_path)
    first = store.create_report_once(state('first'), {'issue_number': 1}, 'report:first')
    second = store.create_report_once(state('second'), {'issue_number': 1}, 'report:second')
    for task in (first, second):
        assert store.artifact_belongs_to_task(task.metadata['report_parameters_ref'], task.id)


@pytest.mark.parametrize('after_commit', [False, True])
def test_http_dispatch_state_write_failure_can_retry_same_task(isolated, monkeypatch, after_commit):
    from fastapi.testclient import TestClient
    import app.main as main
    store, refs, queued = isolated
    monkeypatch.setattr(main, 'UPLOADS', store.uploads_for('anshun_monthly'))
    put = store.put_task
    failed = []
    def faulty(task, *args, **kwargs):
        if task.kind == 'report' and not failed:
            failed.append(True)
            if after_commit:put(task, *args, **kwargs)
            raise OSError('dispatch state unavailable')
        return put(task, *args, **kwargs)
    monkeypatch.setattr(store, 'put_task', faulty)
    body = {'package': 'ruyuan_yuebao', 'file_ids': ['fixture'], 'template_ref': refs['ruyuan_yuebao']}
    with TestClient(main.app, raise_server_exceptions=False) as client:
        first = client.post('/api/report-tasks', json=body, headers={'idempotency-key': 'write-failure'})
        assert first.status_code == 500 and queued == []
        original = next(t for t in store.list_tasks() if t.kind == 'report')
        second = client.post('/api/report-tasks', json=body, headers={'idempotency-key': 'write-failure'})
    assert second.status_code == 200
    assert second.json()['id'] == original.id and queued == [original.id]
