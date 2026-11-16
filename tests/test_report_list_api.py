"""左栏「历史生成报告」三条路由（`app/editor_api.py`）：列表 / 软删除 / 恢复。

判据只有三条硬约束：
- **只列有报告的任务**：有 `final_docx_ref` 的算 `saved`，有别的可读 docx 产物的算 `draft`，
  什么报告都没有的任务不进列表（这是「不列空壳任务」的机械判据）；
- **软删除只写一个时间戳**：`metadata['report_deleted_at']` 有值，artifact 行与磁盘
  `{ref}.docx` 的 sha256 前后一致（一个字节都不动）；
- **恢复**：清掉键后条目回到列表。
"""
from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.editor_api import DELETED_KEY, META_KEY
from app.schemas import TaskState, now
from app.storage import Store

TOKENS = {'Authorization': 'local-demo'}


def _env(tmp_path, monkeypatch):
    """临时 Store；docx 落盘根由 `editor_api` 按**任务所属包**从 store 反推（M3），无需注入。"""
    store = Store(tmp_path / 'data')
    monkeypatch.setattr(main, 'store', store)
    return store


def _task(store, task_id, **metadata):
    store.put_task(TaskState(id=task_id, kind='report', phase='awaiting_final_review',
                             metadata=metadata))


def _docx(store, task_id, text, kind='export_meta'):
    """写一份「磁盘上真有字节」的 docx 工件（与 main.py::export 同口径）。"""
    data = text.encode('utf-8')
    ref = store.put_artifact(task_id, kind, {'bytes': len(data), 'updated_at': now()})
    path = store.root / 'artifacts' / f'{ref}.docx'
    path.write_bytes(data)
    return ref, path


def _saved(store, task_id, text, **metadata):
    """有 final_docx_ref 的任务（状态 已保存）。"""
    _task(store, task_id, **metadata)
    ref, path = _docx(store, task_id, text, kind='final_docx')
    state = store.get_task(task_id)
    state.metadata[META_KEY] = ref
    store.put_task(state, state.revision)
    return ref, path


def _client():
    return TestClient(main.app)


def test_list_only_tasks_that_have_a_report(tmp_path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    _saved(store, 'r-saved', '已保存报告正文', template_name='安顺月报 · 2026年10月')
    _task(store, 'r-draft', report_month='2026-09')
    _docx(store, 'r-draft', '草稿报告正文')          # 只有生成产物，没有 final_docx_ref
    _task(store, 'r-empty')                          # 什么报告都没有

    with _client() as client:
        response = client.get('/api/reports/editable')

    assert response.status_code == 200, response.text
    items = response.json()
    ids = [item['task_id'] for item in items]
    assert ids == ['r-draft', 'r-saved'], f'实测 {ids}'      # 更新时间倒序
    assert 'r-empty' not in ids, '没有报告的任务被列进来了'
    by_id = {item['task_id']: item for item in items}
    assert by_id['r-saved']['status'] == 'saved'
    assert by_id['r-draft']['status'] == 'draft'
    assert by_id['r-saved']['name'] == '安顺月报 · 2026年10月'   # metadata['template_name'] 优先
    assert by_id['r-draft']['name'] != ''                      # 没有 template_name 时走 display_name
    assert by_id['r-saved']['bytes'] == len('已保存报告正文'.encode('utf-8'))
    assert by_id['r-saved']['url'] == '/api/tasks/r-saved/final-docx'
    assert by_id['r-draft']['url'].startswith('/api/artifacts/')


def test_list_sorts_by_updated_at_desc(tmp_path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    _saved(store, 'r-old', '旧报告')
    _saved(store, 'r-new', '新报告')
    state = store.get_task('r-new')
    state.metadata['updated_at'] = '2099-01-01T00:00:00+00:00'   # 显式更新 → 排最前
    store.put_task(state, state.revision)

    with _client() as client:
        ids = [item['task_id'] for item in client.get('/api/reports/editable').json()]

    assert ids[0] == 'r-new', f'实测 {ids}'


def test_soft_delete_only_writes_timestamp_and_keeps_artifact(tmp_path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    ref, path = _saved(store, 'r-saved', '软删除不动字节')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    with _client() as client:
        response = client.delete('/api/reports/editable/r-saved')
        assert response.status_code == 200, response.text
        assert response.json()['deleted_at']
        assert [item['task_id'] for item in client.get('/api/reports/editable').json()] == []
        # 工件与磁盘文件仍在，编辑版仍可下载
        assert store.get_artifact(ref)['bytes'] == len('软删除不动字节'.encode('utf-8'))
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        assert client.get('/api/tasks/r-saved/final-docx').status_code == 200

    assert store.get_task('r-saved').metadata[DELETED_KEY]


def test_delete_is_idempotent(tmp_path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    _saved(store, 'r-saved', '重复删除')

    with _client() as client:
        first = client.delete('/api/reports/editable/r-saved')
        second = client.delete('/api/reports/editable/r-saved')

    assert first.status_code == second.status_code == 200
    assert first.json()['deleted_at'] == second.json()['deleted_at']


def test_restore_brings_it_back(tmp_path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    _saved(store, 'r-saved', '恢复回来')

    with _client() as client:
        client.delete('/api/reports/editable/r-saved')
        assert client.get('/api/reports/editable').json() == []
        restored = client.post('/api/reports/editable/r-saved/restore')
        assert restored.status_code == 200, restored.text
        assert restored.json() == {'task_id': 'r-saved', 'restored': True}
        assert [item['task_id'] for item in client.get('/api/reports/editable').json()] == ['r-saved']

    assert DELETED_KEY not in store.get_task('r-saved').metadata


@pytest.mark.parametrize('method, path', [
    ('delete', '/api/reports/editable/nope'),
    ('post', '/api/reports/editable/nope/restore'),
])
def test_missing_task_is_404(tmp_path, monkeypatch, method, path):
    _env(tmp_path, monkeypatch)
    with _client() as client:
        response = getattr(client, method)(path)
    assert response.status_code == 404
    assert response.json()['detail'] == 'task_not_found'
