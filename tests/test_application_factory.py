import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def test_importing_application_does_not_create_data_directories(tmp_path):
    target = tmp_path / 'must-not-exist'
    env = dict(os.environ, REPORT_DEMO_DATA=str(target))
    result = subprocess.run([sys.executable, '-B', '-c', 'import app.main'], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not target.exists()


def test_two_application_instances_keep_uploads_and_tasks_separate(tmp_path):
    from app.factory import create_app
    from app.settings import Settings
    first = create_app(Settings(data_root=tmp_path / 'first'))
    second = create_app(Settings(data_root=tmp_path / 'second'))
    with TestClient(first) as a, TestClient(second) as b:
        for client in (a, b):
            assert client.get('/api/status').status_code == 200
            assert client.get('/api/tasks').json() == []
        response = a.post('/api/files', files={'file': ('first.xlsx', b'synthetic', 'application/octet-stream')})
        assert response.status_code == 200
        file_id = response.json()['id']
        assert Path(response.json()['path']).is_relative_to(tmp_path / 'first')
        assert not list((tmp_path / 'second').rglob(file_id + '.xlsx'))
        assert a.get('/api/tasks').json() == []
        assert b.get('/api/tasks').json() == []


def test_factory_keeps_openapi_contract():
    from app.factory import create_app
    from app.main import app
    assert create_app().openapi() == app.openapi()


def test_default_factory_can_read_legacy_data_root(tmp_path):
    from app.factory import create_app
    from app.settings import Settings
    from core.storage import Store
    from core.schemas import TaskState
    legacy = Store(tmp_path)
    legacy.put_task(TaskState(id='legacy', kind='report', phase='queued'))
    with TestClient(create_app(Settings(tmp_path))) as client:
        assert [task['id'] for task in client.get('/api/tasks').json()] == ['legacy']


def test_factory_context_survives_threadpool_and_background_tasks(tmp_path):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from fastapi import BackgroundTasks
    from core import paths
    from core.schemas import TaskState
    from app.factory import create_app
    from app.settings import Settings
    from app.runtime import store

    first, second = [create_app(Settings(tmp_path / name)) for name in ('a', 'b')]
    seen = []
    async def capture():
        await asyncio.sleep(.01)
        seen.append(str(paths.data_root_base()))
    def probe(background_tasks: BackgroundTasks):
        background_tasks.add_task(capture)
        return {'root': str(paths.data_root_base()), 'tasks': [t.id for t in store.list_tasks()]}
    for name, app in [('a', first), ('b', second)]:
        app.state.services.store.put_task(TaskState(id=name, kind='report', phase='queued'))
        app.get('/probe')(probe)
    with TestClient(first) as a, TestClient(second) as b, ThreadPoolExecutor() as pool:
        results = list(pool.map(lambda client: client.get('/probe').json(), [a, b]))
        assert [r['tasks'] for r in results] == [['a'], ['b']]
        assert {r['root'] for r in results} == {str(tmp_path / 'a'), str(tmp_path / 'b')}
        assert set(seen) == {str(tmp_path / 'a'), str(tmp_path / 'b')}
