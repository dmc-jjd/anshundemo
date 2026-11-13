"""确认链路的手工草稿入口 + 确认后的只读 LLM 审核。

两类判据（对应 docs/模板字段手动定义设计.md §11-1 的未闭环点与本次用户需求）：
1. **手工草稿能确认**，但没有草稿时原模型研判校验不放宽；伪造 `MANUAL-1` 也进不来。
2. **advice 只读**：产物只有意见列表，不写 `confirmed_template_ref` / blocks / fields，
   不推进 task revision；自创严重度被拒。
"""
from __future__ import annotations

import zipfile

from fastapi.testclient import TestClient

import app.main as main
from app.agent import get_prompt
from app.schemas import TaskState
from app.storage import Store
from app.structured_template import build_structured_template
from app.template_advice import ADVICE_KIND
from app.template_compare import parse_report_document
from app.template_review import POLICY_VERSION, digest
from app.workflow import Dependencies

RULES = {'event_threshold': .65, 'first_warning_scope': 'negative_or_warning',
         'ranking': 'negative_warning_member_count'}


def docx(path, text):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('word/document.xml',
                         '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                         '<w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')
    return parse_report_document(str(path))


def _fixture(tmp_path, monkeypatch, *, model_validation=True):
    """模板任务：有候选、有研判输入包；模型 validation 可选（缺省=只有手工入口）。"""
    documents = [docx(tmp_path / 'a.docx', '共计100条，重点关注农业。'),
                 docx(tmp_path / 'b.docx', '共计200条，重点关注教育。')]
    definition = build_structured_template(documents, 'comparison')
    store = Store(tmp_path / 'data')
    task = TaskState(id='task-template', kind='template', phase='awaiting_template_confirmation')
    candidate_ref = store.put_artifact(task.id, 'structured_template_candidate', definition)
    packet = {'source_reports': [{'id': f'r{index + 1}', 'path': doc['path'], 'sha256': doc['sha256'],
                                 'blocks': doc['blocks']}
                                for index, doc in enumerate(documents)]}
    task.metadata.update(structured_template_ref=candidate_ref, comparison_ref='comparison',
                         template_input_ref=store.put_artifact(task.id, 'template_model_input', packet))
    if model_validation:
        validation = {'validation': 'passed', 'candidate_hash': digest(definition),
                      'candidate_ref': candidate_ref, 'policy_version': POLICY_VERSION,
                      'input_ref': task.metadata['template_input_ref'],
                      'input_hash': digest(packet), 'review_refs': ['template_model_response-x']}
        task.metadata['template_validation_ref'] = store.put_artifact(task.id, 'template_validation', validation)
    store.put_task(task)
    monkeypatch.setattr(main, 'store', store)
    monkeypatch.setattr(main, 'deps', Dependencies(store))
    return store, task.id, definition, candidate_ref


def _confirm(client, task_id, revision, candidate_ref):
    return client.post(f'/api/templates/{task_id}/confirm',
                       json={'expected_revision': revision, 'candidate_ref': candidate_ref,
                             'reason': '已查看模板并确认', 'rules': RULES})


def test_manual_draft_confirms_only_after_draft_exists(tmp_path, monkeypatch):
    """没有草稿 → 409（原校验不放宽）；有草稿 → 200，且确认内容就是草稿。"""
    store, task_id, _definition, candidate_ref = _fixture(tmp_path, monkeypatch, model_validation=False)
    with TestClient(main.app) as client:
        state = client.get(f'/api/tasks/{task_id}').json()
        blocked = _confirm(client, task_id, state['revision'], candidate_ref)
        assert blocked.status_code == 409
        assert blocked.json()['detail'] == 'template_semantic_review_required'

        draft = client.post(f'/api/templates/{task_id}/draft/selection',
                            json={'expected_revision': state['revision'], 'block': 0,
                                  'selected_text': '', 'choice': 'paragraph'})
        assert draft.status_code == 200, draft.text
        body = draft.json()
        confirmed = _confirm(client, task_id, body['revision'], candidate_ref)
        assert confirmed.status_code == 200, confirmed.text
        result = confirmed.json()
        version = store.get_artifact(result['metadata']['confirmed_template_ref'])
        assert version['status'] == 'confirmed_by_human'
        assert version['blocks'] == body['draft']['blocks']
        assert [field['id'] for field in version['fields']] == [field['id'] for field in body['draft']['fields']]
        validation = store.get_artifact(result['metadata']['template_validation_ref'])
        assert validation['source'] == 'manual_definition'
        assert validation['policy_version'] == 'MANUAL-1' and validation['policy_version'] != POLICY_VERSION
        assert validation['review_refs'] == [body['draft_ref']]
        assert validation['manual_log'] and validation['candidate_ref'] == candidate_ref


def test_model_review_path_is_not_relaxed(tmp_path, monkeypatch):
    """模型研判入口仍只认 POLICY_VERSION：伪造 MANUAL-1 或改 candidate_hash 都被拒。"""
    store, task_id, definition, candidate_ref = _fixture(tmp_path, monkeypatch)
    state = store.get_task(task_id)
    ref = state.metadata['template_validation_ref']
    validation = store.get_artifact(ref)
    validation['policy_version'] = 'MANUAL-1'
    stored = store.put_artifact(task_id, 'template_validation', validation)
    state.metadata['template_validation_ref'] = stored
    store.put_task(state, state.revision)

    with TestClient(main.app) as client:
        revision = client.get(f'/api/tasks/{task_id}').json()['revision']
        forged = _confirm(client, task_id, revision, candidate_ref)
        assert forged.status_code == 409
        assert forged.json()['detail'] == 'template_semantic_review_required'

    # 再把版本号改回来、只动 candidate_hash：同样被拒（没有草稿就没有手工入口）。
    state = store.get_task(task_id)
    validation = store.get_artifact(state.metadata['template_validation_ref'])
    validation.update(policy_version=POLICY_VERSION, candidate_hash='0' * 64)
    state.metadata['template_validation_ref'] = store.put_artifact(task_id, 'template_validation', validation)
    store.put_task(state, state.revision)
    with TestClient(main.app) as client:
        revision = client.get(f'/api/tasks/{task_id}').json()['revision']
        tampered = _confirm(client, task_id, revision, candidate_ref)
        assert tampered.status_code == 409
        assert tampered.json()['detail'] == 'template_semantic_review_required'
        assert definition  # 判据用的候选仍在


def test_advice_is_read_only_and_round_trips(tmp_path, monkeypatch):
    """POST 审一次 → items；产物只有意见，模板与任务状态不变；GET 能读回同一条。"""
    store, task_id, _definition, candidate_ref = _fixture(tmp_path, monkeypatch)
    calls = []

    async def adapter(role, payload):
        calls.append((role, payload))
        return {'items': [
            {'severity': '重要', 'field_id': 'bogus_field', 'message': '数量字段应写明统计口径',
             'evidence': '共计100条'},
            {'severity': '建议', 'field_id': '', 'message': '建议把相邻碎字段合并成一个语义单元',
             'evidence': '重点关注农业'},
        ]}

    monkeypatch.setattr(main, 'deps', Dependencies(store, adapter))
    with TestClient(main.app) as client:
        state = client.get(f'/api/tasks/{task_id}').json()
        confirmed = _confirm(client, task_id, state['revision'], candidate_ref)
        assert confirmed.status_code == 200, confirmed.text
        confirmed_ref = confirmed.json()['metadata']['confirmed_template_ref']
        revision = confirmed.json()['revision']

        assert client.get(f'/api/templates/{task_id}/advice').json() == {'available': False, 'items': []}

        posted = client.post(f'/api/templates/{task_id}/advice')
        assert posted.status_code == 200, posted.text
        body = posted.json()
        assert body['available'] is True and len(body['items']) == 2
        assert [item['severity'] for item in body['items']] == ['重要', '建议']
        assert body['reviewed_template_ref'] == confirmed_ref

        assert calls and calls[0][0] == 'template_analyst'
        payload = calls[0][1]
        assert payload['instruction'] == get_prompt('template_analyst.advice')
        assert payload['task']['review_mode'] == 'read_only_advice'
        assert payload['confirmed_template']['fields'] and payload['source_reports']

        artifact = store.get_artifact(body['advice_ref'])
        assert set(artifact) == {'items', 'reviewed_template_ref', 'created_at', 'review_mode'}
        assert 'fields' not in artifact and 'blocks' not in artifact

        after = client.get(f'/api/tasks/{task_id}').json()
        assert after['metadata']['confirmed_template_ref'] == confirmed_ref
        assert after['revision'] == revision

        read = client.get(f'/api/templates/{task_id}/advice').json()
        assert read['available'] is True and read['advice_ref'] == body['advice_ref']
        assert read['items'] == body['items']
        assert read['reviewed_template_ref'] == confirmed_ref


def test_advice_requires_confirmed_template(tmp_path, monkeypatch):
    store, task_id, _definition, _candidate_ref = _fixture(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        response = client.post(f'/api/templates/{task_id}/advice')
        assert response.status_code == 409
        assert response.json()['detail'] == 'confirmed_template_required'


def test_advice_rejects_self_invented_severity(tmp_path, monkeypatch):
    """严重度只允许 建议/重要：模型自创第三级 → 422，不写入任何产物。"""
    store, task_id, _definition, candidate_ref = _fixture(tmp_path, monkeypatch)

    async def adapter(role, payload):
        return {'items': [{'severity': '严重', 'field_id': '', 'message': '越界级别', 'evidence': '原文'}]}

    monkeypatch.setattr(main, 'deps', Dependencies(store, adapter))
    with TestClient(main.app) as client:
        state = client.get(f'/api/tasks/{task_id}').json()
        assert _confirm(client, task_id, state['revision'], candidate_ref).status_code == 200
        response = client.post(f'/api/templates/{task_id}/advice')
        assert response.status_code == 422
        assert response.json()['detail'] == 'advice_not_structured'
        assert client.get(f'/api/templates/{task_id}/advice').json() == {'available': False, 'items': []}
        assert ADVICE_KIND == 'template_advice'
