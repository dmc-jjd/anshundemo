"""字段分类弹窗的「自定义字段」：定性措辞（如「较稳定」「波浪型」）用户自定义。

判据：
1. 选中文字 → choice=custom_text + 小表单 → 生成 custom_field_N，owner/语义/显示名来自表单；
   writer 型进 writer 待填清单、data 型进待配数据来源清单（不崩）；
2. 缺显示名 / 缺语义 / owner 非法 → 422 明确错误码（人话由前端映射），不是 500；
3. 与预设字段一样可撤销，且草稿 = 基线 + 日志重放（含 custom 定义）；
4. 确认后 Writer 能读到该字段语义（桩验证：写作载荷字段面 = compact_field）。
"""
from __future__ import annotations

import zipfile

from fastapi.testclient import TestClient

import app.main as main
from app.schemas import TaskState
from app.storage import Store
from app.structured_template import build_structured_template, load_confirmed_template
from app.structured_writer import compact_field, data_values
from app.template_compare import parse_report_document
from app.template_draft import rebuild
from app.workflow import Dependencies

RULES = {'event_threshold': .65, 'first_warning_scope': 'negative_or_warning',
         'ranking': 'negative_warning_member_count'}
WRITER_CUSTOM = {'display_name': '整体态势措辞',
                 'semantic': '用一个词描述本期整体态势（如较稳定、波浪型），按本期证据写',
                 'owner': 'writer'}


def docx(path, text):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('word/document.xml',
                         '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                         '<w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')
    return parse_report_document(str(path))


def _fixture(tmp_path, monkeypatch):
    documents = [docx(tmp_path / 'a.docx', '共计100条，重点关注农业。'),
                 docx(tmp_path / 'b.docx', '共计200条，重点关注教育。')]
    definition = build_structured_template(documents, 'comparison')
    store = Store(tmp_path / 'data')
    task = TaskState(id='task-custom', kind='template', phase='awaiting_template_confirmation')
    ref = store.put_artifact(task.id, 'structured_template_candidate', definition)
    packet = {'source_reports': [{'id': f'r{index + 1}', 'path': doc['path'], 'sha256': doc['sha256'],
                                  'blocks': doc['blocks']}
                                 for index, doc in enumerate(documents)]}
    task.metadata.update(structured_template_ref=ref, comparison_ref='comparison',
                         template_input_ref=store.put_artifact(task.id, 'template_model_input', packet))
    store.put_task(task)
    monkeypatch.setattr(main, 'store', store)
    monkeypatch.setattr(main, 'deps', Dependencies(store))
    return store, task.id, definition, ref


def _custom(client, task_id, revision, *, text, custom, start=0):
    return client.post(f'/api/templates/{task_id}/draft/selection',
                       json={'expected_revision': revision, 'block': 0, 'selected_text': text,
                             'start': start, 'choice': 'custom_text', 'custom': custom})


def test_choice_is_offered_above_preset_dynamic_fields(tmp_path, monkeypatch):
    _, task_id, _, _ = _fixture(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        body = client.get(f'/api/templates/{task_id}/draft').json()
    ids = [choice['id'] for choice in body['choices']]
    assert ids[0] == 'fixed'
    # 自定义项放在「动态字段」组最上面（紧随「不动」）。
    assert ids.index('custom_text') < ids.index('text')
    custom = next(choice for choice in body['choices'] if choice['id'] == 'custom_text')
    assert custom['scope'] == 'selection' and custom['owner'] is None


def test_custom_writer_field_is_generated_and_visible_to_writer(tmp_path, monkeypatch):
    store, task_id, definition, _ = _fixture(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        revision = client.get(f'/api/templates/{task_id}/draft').json()['revision']
        response = _custom(client, task_id, revision, text='重点关注', custom=WRITER_CUSTOM)
        assert response.status_code == 200, response.text
        body = response.json()
        field = body['field']
        assert field['id'] == 'custom_field_1'
        assert field['display_name'] == '整体态势措辞'
        assert field['owner'] == 'writer' and field['kind'] == 'text'
        assert field['semantic'] == WRITER_CUSTOM['semantic']
        assert field['needs_binding'] is False and field['binding'] is None
        assert 'data_note' not in field
        assert body['preview_chip'] == '〔整体态势措辞〕'
        draft = body['draft']
        assert field['id'] in draft['writer_schema']['properties']
        assert field['id'] in draft['pending']['writer_fields']
        assert field['id'] not in draft['pending']['needs_binding']
        assert draft['selection_log'][0]['custom']['owner'] == 'writer'

        # 预设字段序号与自定义序号互不挪用：同块再定义一个预设动态文字字段
        revision = body['revision']
        preset = client.post(f'/api/templates/{task_id}/draft/selection',
                             json={'expected_revision': revision, 'block': 0,
                                   'selected_text': '共计', 'choice': 'text'})
        assert preset.status_code == 200, preset.text
        preset_field = preset.json()['field']
        assert preset_field['id'] == 'block_0_field_3'
        second_custom = _custom(client, task_id, preset.json()['revision'],
                                text='。', custom={**WRITER_CUSTOM, 'display_name': '波浪型'})
        assert second_custom.status_code == 200, second_custom.text
        assert second_custom.json()['field']['id'] == 'custom_field_2'

    # 刷新（新进程）后自定义定义仍在，且等于日志重放（custom 定义随日志持久化）
    with TestClient(main.app) as client:
        reloaded = client.get(f'/api/templates/{task_id}/draft').json()
    ids = [field['id'] for field in reloaded['definition']['fields']]
    assert ids == ['block_0_field_1', 'block_0_field_2', 'custom_field_1',
                   'block_0_field_3', 'custom_field_2']
    replayed = rebuild(definition, reloaded['draft']['selection_log'], reloaded['base_ref'])
    assert replayed['fields'] == reloaded['draft']['fields']


def test_custom_data_field_needs_binding_and_keeps_optional_note(tmp_path, monkeypatch):
    store, task_id, _, _ = _fixture(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        revision = client.get(f'/api/templates/{task_id}/draft').json()['revision']
        body = _custom(client, task_id, revision, text='重点关注',
                       custom={'display_name': '态势定级', 'semantic': '程序按月度统计表算出的定级',
                               'owner': 'data', 'data_note': '来自月度统计表第 3 列'}).json()
        field = body['field']
        assert field['owner'] == 'data' and field['needs_binding'] is True
        assert field['data_note'] == '来自月度统计表第 3 列'
        assert field['id'] in body['draft']['pending']['needs_binding']
        # data_note 可留空：不落键（选区取另一段仍为固定文字的「共计」）
        revision = body['revision']
        empty_note = _custom(client, task_id, revision, text='共计',
                             custom={'display_name': '另一个程序字段', 'semantic': '程序算', 'owner': 'data'})
        assert empty_note.status_code == 200, empty_note.text
        next_field = empty_note.json()['field']
        assert next_field['id'] == 'custom_field_2' and 'data_note' not in next_field

    # data 型自定义字段没有绑定时进待填/问题清单，不能让写作阶段崩（calculation_for 抛「缺少计算定义」）。
    with TestClient(main.app) as client:
        reloaded = client.get(f'/api/templates/{task_id}/draft').json()
    data_field = next(field for field in reloaded['draft']['fields'] if field['id'] == 'custom_field_1')
    template = {'fields': reloaded['draft']['fields'], 'writer_schema': reloaded['draft']['writer_schema'],
                'output_schema': reloaded['draft']['output_schema']}
    values, issues = data_values(template, report=None, plans={})
    assert data_field['id'] not in values
    assert any(issue['field_id'] == 'custom_field_1' for issue in issues)


def test_custom_field_validation_returns_human_codes(tmp_path, monkeypatch):
    _, task_id, _, _ = _fixture(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        revision = client.get(f'/api/templates/{task_id}/draft').json()['revision']
        cases = [
            ({'display_name': '', 'semantic': 'x', 'owner': 'writer'}, 'custom_display_name_required'),
            ({'display_name': '   ', 'semantic': 'x', 'owner': 'writer'}, 'custom_display_name_required'),
            ({'display_name': '名称', 'semantic': '', 'owner': 'writer'}, 'custom_semantic_required'),
            ({'display_name': '名称', 'semantic': 'x', 'owner': 'nobody'}, 'custom_owner_invalid'),
            (None, 'custom_definition_required'),
        ]
        for custom, code in cases:
            response = _custom(client, task_id, revision, text='重点关注',
                               custom=custom if custom is not None else None)
            assert response.status_code == 422, response.text
            assert response.json()['detail'] == code
        long_name = {'display_name': '字' * 21, 'semantic': 'x', 'owner': 'writer'}
        response = _custom(client, task_id, revision, text='重点关注', custom=long_name)
        assert response.status_code == 422 and response.json()['detail'] == 'custom_display_name_too_long'
        long_semantic = {'display_name': '名称', 'semantic': '义' * 201, 'owner': 'writer'}
        response = _custom(client, task_id, revision, text='重点关注', custom=long_semantic)
        assert response.status_code == 422 and response.json()['detail'] == 'custom_semantic_too_long'


def test_writer_custom_drops_data_note(tmp_path, monkeypatch):
    """切回 Writer 后前端残留的数据来源说明必须被后端丢弃（data_note 只属于 data 型）。"""
    _, task_id, _, _ = _fixture(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        revision = client.get(f'/api/templates/{task_id}/draft').json()['revision']
        body = _custom(client, task_id, revision, text='重点关注',
                       custom={**WRITER_CUSTOM, 'data_note': '残留的数据来源说明'}).json()
        assert 'data_note' not in body['field']
        assert body['draft']['selection_log'][0]['custom']['data_note'] == ''


def test_custom_field_can_be_undone(tmp_path, monkeypatch):
    _, task_id, _, _ = _fixture(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        revision = client.get(f'/api/templates/{task_id}/draft').json()['revision']
        created = _custom(client, task_id, revision, text='重点关注', custom=WRITER_CUSTOM).json()
        undone = client.post(f'/api/templates/{task_id}/draft/undo',
                             json={'expected_revision': created['revision']})
        assert undone.status_code == 200
        # 草稿里只有这一条定义：撤销后回到空草稿（has_draft=false），自定义字段消失。
        assert undone.json()['has_draft'] is False
        assert 'custom_field_1' not in [field['id'] for field in undone.json()['definition']['fields']]


def test_confirmed_custom_writer_field_reaches_writer_payload(tmp_path, monkeypatch):
    """手工定义入口确认：custom writer 字段语义在确认版里，且写作载荷字段面（compact_field）带语义。"""
    from app.template_review import digest
    store, task_id, _definition, candidate_ref = _fixture(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        revision = client.get(f'/api/templates/{task_id}/draft').json()['revision']
        # 自定义字段接管固定文字「重点关注」；候选的两个预设字段（数字 + writer）显式还原为固定文字。
        created = _custom(client, task_id, revision, text='重点关注', custom=WRITER_CUSTOM)
        assert created.status_code == 200, created.text
        fixed_number = client.post(f'/api/templates/{task_id}/draft/selection',
                                   json={'expected_revision': created.json()['revision'], 'block': 0,
                                         'selected_text': '{{block_0_field_1}}', 'choice': 'fixed'})
        assert fixed_number.status_code == 200, fixed_number.text
        fixed = client.post(f'/api/templates/{task_id}/draft/selection',
                            json={'expected_revision': fixed_number.json()['revision'], 'block': 0,
                                  'selected_text': '{{block_0_field_2}}', 'choice': 'fixed'})
        assert fixed.status_code == 200, fixed.text
        confirmed = client.post(f'/api/templates/{task_id}/confirm',
                                json={'expected_revision': fixed.json()['revision'],
                                      'candidate_ref': candidate_ref,
                                      'reason': '自定义字段验收', 'rules': RULES})
        assert confirmed.status_code == 200, confirmed.text
        version_ref = confirmed.json()['metadata']['confirmed_template_ref']

    template = load_confirmed_template(store, version_ref)
    field = next(item for item in template['fields'] if item['id'] == 'custom_field_1')
    assert field['owner'] == 'writer' and field['semantic'] == WRITER_CUSTOM['semantic']
    assert 'custom_field_1' in template['writer_schema']['properties']
    # Writer 实际收到的字段面（structured_writer.compact_field）：语义随字段下发
    compact = compact_field(field)
    assert compact['semantic'] == WRITER_CUSTOM['semantic'] and compact['owner'] == 'writer'
    assert digest(template)  # 确认版哈希可算（MANUAL-1 validation 已通过即证明链路一致）
