"""旧结构草稿（缺 content_hash）的三个审核页动作不许 500；新结构草稿行为逐项不变。

测试判据来自演示阻塞单：draft-view / writing-review / exports 在旧草稿上原本抛 KeyError: content_hash。
"""
import hashlib
from fastapi.testclient import TestClient
import app.main as main
from app.schemas import TaskState
from app.storage import Store

LEGACY = {'sections': [], 'slot_values': {'w1': {'value': '人工填写的正文', 'source_refs': ['human_edit']}},
          'chart_refs': {}, 'evidence_refs': [], 'recommendations': []}


def _env(tmp_path, monkeypatch, draft):
    store = Store(tmp_path / 'store')
    facts = store.put_artifact('t', 'facts', {'metrics': {}})
    payload = {**draft, 'fact_ref': facts}
    draft_ref = store.put_artifact('t', 'draft', payload)
    store.put_task(TaskState(id='t', kind='report', phase='awaiting_final_review', fact_ref=facts,
                             draft_ref=draft_ref, template_ref='anshun-monthly-colored'))
    monkeypatch.setattr(main, 'store', store)
    monkeypatch.setattr(main, 'DATA', tmp_path / 'data')
    (tmp_path / 'data' / 'artifacts').mkdir(parents=True)
    monkeypatch.setattr(main, 'export_docx', lambda *args, **kwargs: b'PK-legacy-export')
    monkeypatch.setattr(main, 'effective_features', lambda store, state: {})
    return store


def test_legacy_draft_view_and_writing_review_do_not_500(tmp_path, monkeypatch):
    store = _env(tmp_path, monkeypatch, LEGACY)
    with TestClient(main.app) as client:
        view = client.get('/api/tasks/t/draft-view')
        assert view.status_code == 200
        body = view.json()
        assert body['draft']['slot_values']['w1']['value'] == '人工填写的正文'
        assert body['draft_schema_outdated'] is True and body['draft_hash'] is None
        assert body['detail'].startswith('draft_schema_outdated: ') and '内容指纹' in body['detail']
        assert body['review_ready'] is False and body['can_approve'] is False
        review = client.get('/api/tasks/t/writing-review')
        assert review.status_code == 200
        assert review.json()['draft_schema_outdated'] is True and review.json()['ready'] is False
        assert client.get('/api/tasks/t/writing-review').status_code == 200
    events = [e for e in store.events('t') if e.get('type') == 'draft_schema_outdated']
    assert len(events) == 1, '多次触达只留一条审计：跳过并发校验不许静默，也不许刷屏'
    assert events[0]['artifact'] == store.get_task('t').draft_ref
    assert events[0]['missing'] == ['content_hash']


def test_legacy_draft_exports_and_slot_values_are_not_500(tmp_path, monkeypatch):
    store = _env(tmp_path, monkeypatch, LEGACY)
    with TestClient(main.app) as client:
        drafted = client.post('/api/tasks/t/exports', json={'mode': 'draft'})
        assert drafted.status_code == 200
        assert store.get_artifact(drafted.json()['artifact_id'])['draft_hash'] is None
        final = client.post('/api/tasks/t/exports', json={'mode': 'final'})
        assert final.status_code == 409
        assert final.json()['detail'].startswith('draft_schema_outdated: ')
        slot = client.post('/api/tasks/t/slot-values', json={'values': {}})
        assert slot.status_code == 409
        assert slot.json()['detail'].startswith('draft_schema_outdated: ')
    assert 'content_hash' not in store.get_artifact(store.get_task('t').draft_ref)


def test_current_schema_draft_path_unchanged(tmp_path, monkeypatch):
    digest = hashlib.sha256(b'current-draft').hexdigest()
    store = _env(tmp_path, monkeypatch, {**LEGACY, 'content_hash': digest})
    with TestClient(main.app) as client:
        view = client.get('/api/tasks/t/draft-view').json()
        assert view['draft_hash'] == digest and view['draft_schema_outdated'] is False and view['detail'] is None
        review = client.get('/api/tasks/t/writing-review').json()
        assert review['draft_hash'] == digest and review['draft_schema_outdated'] is False
        exported = client.post('/api/tasks/t/exports', json={'mode': 'draft'})
        assert exported.status_code == 200
        assert store.get_artifact(exported.json()['artifact_id'])['draft_hash'] == digest
        assert client.post('/api/tasks/t/exports', json={'mode': 'final'}).json()['detail'] == 'current_approval_required'
    assert [e for e in store.events('t') if e.get('type') == 'draft_schema_outdated'] == []
