"""模板任务软删除：标记不删文件、列表/下拉消失、引用保护（force）、同名可重建。

判据（用户需求）：
1. 待确认候选与已确认模板都能删；删后不进 GET /api/templates（02 库 + 03 下拉同源）；
2. 软删除只打标记：artifact 文件仍可取、报告任务的 template_ref 不动；
3. 被报告任务引用时默认 409 并给引用数，?force=true 才删；
4. 删除后相同模板名可重新创建并确认成功（旧任务不再占位）。
"""
from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient

import app.main as main
from app.schemas import TaskState
from app.storage import Store
from app.structured_template import build_structured_template
from app.template_compare import parse_report_document
from app.workflow import Dependencies
from test_structured_template import semantic_analyst

DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
RULES = {'event_threshold': .65, 'first_warning_scope': 'negative_or_warning',
         'ranking': 'negative_warning_member_count'}


def docx(path, text):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('word/document.xml',
                         '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                         '<w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')
    return parse_report_document(str(path))


def _store(tmp_path, monkeypatch):
    store = Store(tmp_path / 'data')
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    monkeypatch.setattr(main, 'store', store)
    monkeypatch.setattr(main, 'UPLOADS', uploads)
    monkeypatch.setattr(main, 'deps', Dependencies(store, semantic_analyst))
    return store, uploads


def _documents(tmp_path):
    return [docx(tmp_path / 'a.docx', '共计100条，重点关注农业。'),
            docx(tmp_path / 'b.docx', '共计200条，重点关注教育。')]


def _candidate_task(store, tmp_path, *, name='待确认模板X', simulation=False):
    definition = build_structured_template(_documents(tmp_path), 'comparison')
    task = TaskState(id='cand-' + name, kind='template', phase='awaiting_template_confirmation',
                     metadata={'template_name': name, 'simulation': simulation})
    ref = store.put_artifact(task.id, 'structured_template_candidate', definition)
    task.metadata['structured_template_ref'] = ref
    store.put_task(task)
    return task, ref


def _confirmed_task(store, tmp_path, *, task_id='confirmed-1', name='龙川县舆情月报V1'):
    (tmp_path / task_id).mkdir(parents=True, exist_ok=True)
    definition = build_structured_template(_documents(tmp_path / task_id), 'comparison')
    task = TaskState(id=task_id, kind='template', phase='template_confirmed',
                     metadata={'template_name': name})
    version = {**definition, 'status': 'confirmed_by_human', 'version': 1, 'name': name}
    ref = store.put_artifact(task_id, 'template_version', version)
    task.metadata['confirmed_template_ref'] = ref
    store.put_task(task)
    return task, ref


def _delete(client, task_id, force=False):
    url = f'/api/template-tasks/{task_id}' + ('?force=true' if force else '')
    return client.delete(url)


def _library_ids(client):
    return {item['id'] for item in client.get('/api/templates').json()}


def test_delete_candidate_removes_from_library_and_keeps_artifacts(tmp_path, monkeypatch):
    store, _ = _store(tmp_path, monkeypatch)
    task, ref = _candidate_task(store, tmp_path)
    with TestClient(main.app) as client:
        assert task.id in _library_ids(client)
        response = _delete(client, task.id)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['phase'] == 'cancelled' and body['references'] == 0
        assert task.id not in _library_ids(client)
        # 03 页下拉只取 confirmed_by_human：候选本来就不在，删除后更不在
        dropdown = [item for item in client.get('/api/templates').json()
                    if item['status'] == 'confirmed_by_human']
        assert all(item['task_id'] != task.id for item in dropdown)

    state = store.get_task(task.id)
    assert state.phase == 'cancelled' and state.metadata['template_deleted_at']
    # 软删除：候选 artifact 文件仍可取
    assert store.get_artifact(ref)['blocks']
    assert any(event['type'] == 'template_task_deleted' and event['soft'] is True
               for event in store.events(task.id))


def test_delete_confirmed_template_without_references(tmp_path, monkeypatch):
    store, _ = _store(tmp_path, monkeypatch)
    task, ref = _confirmed_task(store, tmp_path)
    with TestClient(main.app) as client:
        assert ref in _library_ids(client)
        response = _delete(client, task.id)
        assert response.status_code == 200, response.text
        assert ref not in _library_ids(client)
    assert store.get_task(task.id).metadata['template_deleted_at']
    assert store.get_artifact(ref)['status'] == 'confirmed_by_human'  # 文件保留


def test_referenced_confirmed_template_is_rejected_then_force_deleted(tmp_path, monkeypatch):
    store, _ = _store(tmp_path, monkeypatch)
    task, ref = _confirmed_task(store, tmp_path)
    store.put_task(TaskState(id='report-using-it', kind='report', phase='awaiting_review',
                             template_ref=ref))
    with TestClient(main.app) as client:
        refused = _delete(client, task.id)
        assert refused.status_code == 409, refused.text
        body = refused.json()
        assert body['detail'] == 'template_in_use' and body['references'] == 1

        forced = _delete(client, task.id, force=True)
        assert forced.status_code == 200, forced.text
        assert forced.json()['references'] == 1
        assert ref not in _library_ids(client)

    # 报告任务的 template_ref 原封不动，仍可按工件查看
    report = store.get_task('report-using-it')
    assert report.template_ref == ref
    assert store.get_artifact(ref)


def test_delete_guards_unknown_report_double_running(tmp_path, monkeypatch):
    store, _ = _store(tmp_path, monkeypatch)
    _candidate_task(store, tmp_path, name='candidate-x')
    store.put_task(TaskState(id='a-report', kind='report', phase='awaiting_review'))
    store.put_task(TaskState(id='running-tpl', kind='template', phase='queued'))
    with TestClient(main.app) as client:
        assert _delete(client, 'no-such-task').status_code == 404
        # 内置基线不是任务，不能删
        assert _delete(client, 'anshun-monthly-colored').status_code == 404
        assert _delete(client, 'a-report').status_code == 422
        # 研判仍在后台跑：拒绝（避免被跑完的图复活）
        running = _delete(client, 'running-tpl')
        assert running.status_code == 409 and running.json()['detail'] == 'template_still_running'
        done = _delete(client, 'cand-candidate-x')
        assert done.status_code == 200
        again = _delete(client, 'cand-candidate-x')
        assert again.status_code == 409 and again.json()['detail'] == 'template_already_deleted'


def _docx_bytes(text):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        archive.writestr('word/document.xml',
                         '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                         '<w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')
    return out.getvalue()


def test_same_named_template_can_be_created_and_confirmed_after_delete(tmp_path, monkeypatch):
    store, uploads = _store(tmp_path, monkeypatch)
    name = '龙川县舆情月报V1'
    old_task, old_ref = _confirmed_task(store, tmp_path / 'old', task_id='old-duplicate', name=name)
    with TestClient(main.app) as client:
        assert any(item['name'] == name for item in client.get('/api/templates').json())
        assert _delete(client, old_task.id).status_code == 200
        assert not any(item['name'] == name for item in client.get('/api/templates').json())

        # 用相同模板名重新走「上传两份 → 建模板任务 → 确认」全链路
        ids = []
        for text, filename in [('共计100条，重点关注农业。', '10月.docx'),
                               ('共计200条，重点关注教育。', '9月.docx')]:
            uploaded = client.post('/api/files',
                                   files={'file': (filename, _docx_bytes(text), DOCX_MIME)})
            assert uploaded.status_code == 200, uploaded.text
            ids.append(uploaded.json()['id'])
        created = client.post('/api/template-tasks', json={'file_ids': ids, 'template_name': name})
        assert created.status_code == 200, created.text
        new_task_id = created.json()['id']
        state = store.get_task(new_task_id)
        assert state.metadata['template_name'] == name
        assert state.phase == 'awaiting_template_confirmation', state.metadata.get('template_error')

        definition = client.get(f'/api/templates/{new_task_id}/definition').json()
        confirmed = client.post(f'/api/templates/{new_task_id}/confirm',
                                json={'expected_revision': state.revision,
                                      'candidate_ref': definition['artifact_ref'],
                                      'reason': '同名重建验收', 'rules': RULES})
        assert confirmed.status_code == 200, confirmed.text
        new_ref = confirmed.json()['metadata']['confirmed_template_ref']
        assert new_ref != old_ref

        items = client.get('/api/templates').json()
        same_name = [item for item in items if item['name'] == name]
        assert len(same_name) == 1 and same_name[0]['id'] == new_ref
        assert old_ref not in {item['id'] for item in items}
