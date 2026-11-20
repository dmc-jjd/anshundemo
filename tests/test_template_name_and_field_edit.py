"""模板名称（默认识别 / 可编辑 / 确认后随版本走）与候选字段编辑（显示名称 / 语义 / 归属）。

判据来自用户实测的两个缺陷：
1. 新建比对任务时默认模板名 = 第一份上传文件的文件名（去后缀，`（xxx县委）` 这类区域前缀保留）；
2. 用户改的名字进 `metadata['template_name']`，`/api/tasks` 的 `display_name` 直接用它，
   没填过才回退「模板比对 · N 份报告 · 日期」；
3. 确认后 `/api/templates` 的 `name` = 用户填的名字（不是固定串、不是「N 份报告生成的结构化模板」）；
4. `display_name` / `semantic` / `owner` 改完即落盘，重读（等价刷新页面）仍是新值；
   TOP10 字段的规则口径不能把人工改过的显示名/语义盖回去；
5. 已确认版本（`status=confirmed_by_human`）不允许改，且给明确错误码。
"""
from __future__ import annotations

import copy
import io
import zipfile

import pytest

from fastapi.testclient import TestClient

import app.main as main
from app.api_views.template import apply_top10_rule_preserving, strip_report_suffix
from app.storage import Store
from app.workflow import Dependencies
from test_structured_template import build_structured_template, docx, semantic_analyst

DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
FIRST_NAME = '（文成县委）【当日热点】10月舆情综述.docx'
SECOND_NAME = '（文成县委）【当日热点】9月舆情综述.docx'
RULES = {'event_threshold': 0.65, 'first_warning_scope': 'warning',
         'ranking': 'negative_warning_member_count'}


def docx_bytes(text):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        archive.writestr('word/document.xml',
                         '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                         '<w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')
    return out.getvalue()


def _store(tmp_path, monkeypatch):
    store = Store(tmp_path / 'store')
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    monkeypatch.setattr(main, 'store', store)
    monkeypatch.setattr(main, 'UPLOADS', uploads)
    monkeypatch.setattr(main, 'deps', Dependencies(store, semantic_analyst))
    return store, uploads


def _upload_pair(client):
    ids = []
    for text, name in [('共计100条，重点关注农业。', FIRST_NAME), ('共计200条，重点关注教育。', SECOND_NAME)]:
        uploaded = client.post('/api/files', files={'file': (name, docx_bytes(text), DOCX_MIME)})
        assert uploaded.status_code == 200, uploaded.text
        ids.append(uploaded.json()['id'])
    return ids


def _create_task(client, store, template_name=None):
    body = {'file_ids': _upload_pair(client)}
    if template_name is not None:
        body['template_name'] = template_name
    created = client.post('/api/template-tasks', json=body)
    assert created.status_code == 200, created.text
    task_id = created.json()['id']
    return task_id, store.get_task(task_id)


def _display_name(client, task_id):
    return next(item for item in client.get('/api/tasks').json() if item['id'] == task_id)['display_name']


def _fields(client, task_id):
    return client.get(f'/api/templates/{task_id}/definition').json()['definition']['fields']


def test_strip_report_suffix_keeps_region_prefix():
    assert strip_report_suffix('（文成县委）【当日热点】10月舆情综述.docx') == '（文成县委）【当日热点】10月舆情综述'
    assert strip_report_suffix('  安顺月报.DOC  ') == '安顺月报'
    assert strip_report_suffix('报告.v1.docx') == '报告.v1'
    assert strip_report_suffix('') == ''


def test_default_template_name_comes_from_first_uploaded_file(tmp_path, monkeypatch):
    store, _ = _store(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        task_id, state = _create_task(client, store)
        assert state.metadata['template_name'] == '（文成县委）【当日热点】10月舆情综述'
        assert _display_name(client, task_id) == '（文成县委）【当日热点】10月舆情综述'


def test_edited_template_name_wins_over_default(tmp_path, monkeypatch):
    store, _ = _store(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        task_id, state = _create_task(client, store, template_name=' 文成县委·10月模板 ')
        assert state.metadata['template_name'] == '文成县委·10月模板'
        assert _display_name(client, task_id) == '文成县委·10月模板'


def test_confirmed_template_version_carries_the_edited_name(tmp_path, monkeypatch):
    store, _ = _store(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        task_id, state = _create_task(client, store, template_name='文成县委·10月模板')
        definition = client.get(f'/api/templates/{task_id}/definition').json()
        confirmed = client.post(f'/api/templates/{task_id}/confirm',
                                json={'expected_revision': state.revision,
                                      'candidate_ref': definition['artifact_ref'],
                                      'reason': 'test', 'rules': RULES, 'resolutions': {}})
        assert confirmed.status_code == 200, confirmed.text
        ref = confirmed.json()['metadata']['confirmed_template_ref']
        assert store.get_artifact(ref)['name'] == '文成县委·10月模板'
        library = next(item for item in client.get('/api/templates').json() if item['id'] == ref)
        assert library['name'] == '文成县委·10月模板'


def test_field_edit_persists_after_reload(tmp_path, monkeypatch):
    store, _ = _store(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        task_id, state = _create_task(client, store)
        target = next(field for field in _fields(client, task_id) if not field.get('binding'))
        saved = client.put(f'/api/templates/{task_id}/fields/{target["id"]}',
                           json={'expected_revision': state.revision, 'display_name': '人工改过的名字',
                                 'semantic': '人工改过的语义'})
        assert saved.status_code == 200, saved.text
        assert saved.json()['field']['display_name'] == '人工改过的名字'
        # 重读 = 刷新页面后再取一次；仍是新值，且人工标记留存（TOP10 规则不会覆盖它）
        reloaded = next(field for field in _fields(client, task_id) if field['id'] == target['id'])
        assert reloaded['display_name'] == '人工改过的名字'
        assert reloaded['semantic'] == '人工改过的语义'
        assert reloaded['human_edited'] == ['display_name', 'semantic']
        # 归属也可改，并同步重算 writer schema
        other_owner = 'writer' if target['owner'] == 'data' else 'data'
        flipped = client.put(f'/api/templates/{task_id}/fields/{target["id"]}',
                             json={'expected_revision': saved.json()['revision'], 'owner': other_owner})
        assert flipped.status_code == 200, flipped.text
        flipped_field = next(field for field in _fields(client, task_id) if field['id'] == target['id'])
        assert flipped_field['owner'] == other_owner and 'owner' in flipped_field['human_edited']
        stale = client.put(f'/api/templates/{task_id}/fields/{target["id"]}',
                           json={'expected_revision': saved.json()['revision'], 'display_name': '过期的写入'})
        assert stale.status_code == 409 and stale.json()['detail'] == 'stale_template_revision'


def test_revision_candidate_allows_field_edit(tmp_path, monkeypatch):
    store, _ = _store(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        task_id, state = _create_task(client, store)
        candidate = store.get_artifact(state.metadata['structured_template_ref'])
        candidate['status'] = 'candidate'
        state.metadata['structured_template_ref'] = store.put_artifact(task_id, 'structured_template_candidate', candidate)
        store.put_task(state, state.revision)
        target = next(field for field in _fields(client, task_id) if not field.get('binding'))
        saved = client.put(f'/api/templates/{task_id}/fields/{target["id"]}',
                           json={'expected_revision': state.revision, 'semantic': 'V3候选人工编辑'})
        assert saved.status_code == 200, saved.text
        assert saved.json()['field']['semantic'] == 'V3候选人工编辑'


def test_confirmed_version_and_bad_patches_are_rejected_explicitly(tmp_path, monkeypatch):
    store, _ = _store(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        task_id, state = _create_task(client, store)
        target = next(field for field in _fields(client, task_id) if not field.get('binding'))
        bound = _fields(client, task_id)[0]
        bound_id = bound['id']
        candidate = store.get_artifact(state.metadata['structured_template_ref'])
        next(field for field in candidate['fields'] if field['id'] == bound_id)['binding'] = {
            'tool': 'calculate_metrics', 'path': ['record_count']}
        state.metadata['structured_template_ref'] = store.put_artifact(task_id, 'structured_template_candidate', candidate)
        store.put_task(state, state.revision)
        revision = store.get_task(task_id).revision

        other_owner = 'writer' if bound['owner'] == 'data' else 'data'
        locked_owner = client.put(f'/api/templates/{task_id}/fields/{bound_id}',
                                  json={'expected_revision': revision, 'owner': other_owner})
        assert locked_owner.status_code == 422 and locked_owner.json()['detail'] == 'field_binding_locked'
        bad_owner = client.put(f'/api/templates/{task_id}/fields/{target["id"]}',
                               json={'expected_revision': revision, 'owner': 'nobody'})
        assert bad_owner.status_code == 422 and bad_owner.json()['detail'] == 'invalid_field_owner'
        missing = client.put(f'/api/templates/{task_id}/fields/no-such-field',
                             json={'expected_revision': revision, 'display_name': 'x'})
        assert missing.status_code == 404 and missing.json()['detail'] == 'template_field_not_found'
        empty = client.put(f'/api/templates/{task_id}/fields/{target["id"]}',
                           json={'expected_revision': revision, 'display_name': '   '})
        assert empty.status_code == 422 and empty.json()['detail'] == 'display_name_required'


def test_confirmed_version_rejects_field_edits(tmp_path, monkeypatch):
    store, _ = _store(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        task_id, state = _create_task(client, store)
        target = next(field for field in _fields(client, task_id) if not field.get('binding'))
        definition = client.get(f'/api/templates/{task_id}/definition').json()
        revision = store.get_task(task_id).revision
        confirmed = client.post(f'/api/templates/{task_id}/confirm',
                                json={'expected_revision': revision,
                                      'candidate_ref': definition['artifact_ref'],
                                      'reason': 'test', 'rules': RULES, 'resolutions': {}})
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()['metadata']['confirmed_template_ref']
        frozen = client.put(f'/api/templates/{task_id}/fields/{target["id"]}',
                            json={'expected_revision': revision, 'display_name': '确认之后的改动'})
        assert frozen.status_code == 409 and frozen.json()['detail'] == 'immutable_confirmed_template'


def test_top10_rule_does_not_override_human_edited_names():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        documents = [docx(root / 'a.docx', '共计100条，重点关注农业。'), docx(root / 'b.docx', '共计200条，重点关注教育。')]
        definition = build_structured_template(documents, 'comparison')
    definition['blocks'].append({'index': 99, 'kind': 'table', 'headers': ['排名', '事件', '条数'],
                                 'parts': [{'field': 'b99_rows'}]})
    definition['fields'].append({'id': 'b99_rows', 'owner': 'data', 'kind': 'table_rows',
                                 'semantic': '本地初稿语义', 'value_schema': {'type': 'array'}, 'block': 99,
                                 'binding': {'tool': 'top10_events', 'path': []}, 'sources': []})

    plain = apply_top10_rule_preserving(definition)
    field = next(item for item in plain['fields'] if item['id'] == 'b99_rows')
    assert field['display_name'] == '负面预警事件 TOP10' and '去重' in field['semantic']

    edited = copy.deepcopy(definition)
    victim = next(item for item in edited['fields'] if item['id'] == 'b99_rows')
    victim.update(display_name='人工 TOP10 视图', semantic='人工改过的语义', human_edited=['display_name', 'semantic'])
    kept = apply_top10_rule_preserving(edited)
    field = next(item for item in kept['fields'] if item['id'] == 'b99_rows')
    assert field['display_name'] == '人工 TOP10 视图' and field['semantic'] == '人工改过的语义'
    assert field['binding'] == {'tool': 'top10_events', 'path': []}


def test_field_descriptions_persist_and_freeze_on_confirmation(tmp_path, monkeypatch):
    store, _ = _store(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        task_id, state = _create_task(client, store)
        target = _fields(client, task_id)[0]
        descriptions = {'rule': '按本期口径计算\n不沿用历史数字',
                        'reason': '用户审阅后的字段说明', 'format': '整数，不带单位'}
        saved = client.put(f'/api/templates/{task_id}/fields/{target["id"]}',
                           json={'expected_revision': state.revision, **descriptions})
        assert saved.status_code == 200, saved.text
        field = next(f for f in _fields(client, task_id) if f['id'] == target['id'])
        for key, value in descriptions.items():
            assert field.get(key) == value
            assert key in field['human_edited']
        definition = client.get(f'/api/templates/{task_id}/definition').json()
        confirmed = client.post(f'/api/templates/{task_id}/confirm', json={
            'expected_revision': saved.json()['revision'], 'candidate_ref': definition['artifact_ref'],
            'reason': 'test', 'rules': RULES, 'resolutions': {}})
        assert confirmed.status_code == 200, confirmed.text
        frozen = store.get_artifact(confirmed.json()['metadata']['confirmed_template_ref'])
        assert all(next(f for f in frozen['fields'] if f['id'] == target['id'])[k] == v
                   for k, v in descriptions.items())
        rejected = client.put(f'/api/templates/{task_id}/fields/{target["id"]}',
                              json={'expected_revision': confirmed.json()['revision'], 'rule': '不能改'})
        assert rejected.status_code == 409
        assert rejected.json()['detail'] == 'immutable_confirmed_template'


def test_field_description_edits_preserve_unrelated_template_content():
    from app.api_views.template_field import edit_template_field
    original = {'status': 'candidate_requires_review', 'fields': [
        {'id': 'f', 'owner': 'data', 'kind': 'number', 'semantic': '数量',
         'rule': '旧口径', 'reason': '旧说明', 'binding': {'metric': 'count'},
         'value_schema': {'type': 'string'}, 'sources': [{'text': '历史数字'}]}],
        'blocks': [{'index': 22, 'parts': [{'text': '共'}, {'field': 'f'}]}]}
    before = copy.deepcopy(original)
    error, edited, field = edit_template_field(original, 'f', {'rule': '', 'reason': '新说明'})
    assert error is None
    assert field['rule'] == '' and field['reason'] == '新说明'
    assert original == before
    assert edited['blocks'] == original['blocks']
    assert field['binding'] == original['fields'][0]['binding']
    assert field['sources'] == original['fields'][0]['sources']


@pytest.mark.parametrize('features', [
    dict(dedup=False, classification=False, first_warning=False, top10=False),
    dict(dedup=False, classification=True, first_warning=False, top10=True),
    dict(dedup=True, classification=True, first_warning=True, top10=True),
])
def test_field_descriptions_survive_saving_template_rules_with_manual_draft(tmp_path, monkeypatch, features):
    store, _ = _store(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        task_id, state = _create_task(client, store)
        definition = client.get(f'/api/templates/{task_id}/definition').json()['definition']
        block = next(b for b in definition['blocks'] if b['kind'] == 'paragraph')
        added = client.post(f'/api/templates/{task_id}/draft/selection', json={
            'expected_revision': state.revision, 'block': block['index'], 'selected_text': '',
            'start': 0, 'choice': 'paragraph'})
        assert added.status_code == 200, added.text
        field_id = added.json()['field']['id']
        saved = client.put(f'/api/templates/{task_id}/fields/{field_id}', json={
            'expected_revision': added.json()['revision'], 'rule': '新规则', 'reason': '新说明'})
        assert saved.status_code == 200, saved.text
        changed = client.put(f'/api/templates/{task_id}/definition', json={
            'expected_revision': saved.json()['revision'], 'fields': {}, 'rules': {**RULES, 'features': features}})
        assert changed.status_code == 200, changed.text
        effective = client.get(f'/api/templates/{task_id}/draft').json()
        assert effective['draft']['base_ref'] == store.get_task(task_id).metadata['structured_template_ref']
        assert len(effective['draft']['selection_log']) == 1
        reloaded = client.get(f'/api/templates/{task_id}/definition').json()
        assert reloaded['definition']['rules']['features'] == features
        assert effective['definition']['rules']['features'] == features
        assert not store.get_task(task_id).metadata.get('confirmed_template_ref')
        assert store.get_task(task_id).phase == 'awaiting_template_confirmation'
        assert next(f for f in effective['definition']['fields'] if f['id'] == field_id)['reason'] == '新说明'
