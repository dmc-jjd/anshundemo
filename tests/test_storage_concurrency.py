from concurrent.futures import ThreadPoolExecutor
import json
import threading

from core.schemas import TaskState
from core.storage import Store, ConflictError


def test_two_connections_cannot_overwrite_same_revision(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.put_task(TaskState(id='r', kind='report', phase='queued'))
    before = store.get_task('r')
    barrier = threading.Barrier(2)
    connect = store.connect

    class Connection:
        def __init__(self): self.raw = connect()
        def __enter__(self): self.raw.__enter__(); return self
        def __exit__(self, *args): return self.raw.__exit__(*args)
        def execute(self, sql, args=()):
            cursor = self.raw.execute(sql, args)
            # Force both legacy non-transactional readers to observe the same snapshot.
            # A serializing transaction holds the lock before reading and needs no barrier.
            if sql.startswith('SELECT revision,state') and not self.raw.in_transaction:
                row = cursor.fetchone()
                barrier.wait(timeout=5)
                return type('Cursor', (), {'fetchone': lambda unused: row})()
            return cursor
    monkeypatch.setattr(store, 'connect', Connection)
    def writer(label):
        state = before.model_copy(deep=True)
        state.metadata['winner'] = label
        try:
            store.put_task(state, before.revision)
            return 'ok'
        except ConflictError as exc:
            return str(exc)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(writer, ['a', 'b']))
    assert sorted(results) == ['ok', 'stale_task_revision']
    current = store.get_task('r')
    assert current.revision == before.revision + 1
    assert current.metadata['winner'] in ('a', 'b')


def test_pause_metadata_survives_stale_work_until_explicit_resume(tmp_path):
    store = Store(tmp_path)
    store.put_task(TaskState(id='r', kind='report', phase='paused',
                             metadata={'paused_from_phase': 'queued', 'paused_at': 'saved'}))
    state = store.get_task('r')
    state.phase = 'writing'
    state.metadata.clear()
    store.put_task(state, state.revision)
    assert state.phase == 'paused' and state.metadata['paused_at'] == 'saved'
    state.phase = 'queued'
    store.put_task(state, state.revision, allow_resume=True)
    assert store.get_task('r').phase == 'queued'
