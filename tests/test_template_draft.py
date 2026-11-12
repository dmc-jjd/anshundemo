"""手动定义草稿：选区 → 选择题 → 占位符 / 字段 JSON，以及刷新后不丢。

判据（对应 docs/模板字段手动定义设计.md 的三条不变量）：
1. 选区生成正确的 parts 切分与字段 JSON；
2. 多段累积 + 从磁盘重读（等价于刷新页面）后仍在；
3. 草稿 = 基线 + 重放日志（幂等），且拒绝非法选区。
"""
from __future__ import annotations

import zipfile

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.schemas import TaskState
from app.storage import Store
from app.structured_template import build_structured_template
from app.template_compare import parse_report_document
from app.template_draft import DraftError, apply_selection, rebuild

BASE_TEXT = '共计100条，重点关注农业。'


def docx(path, text):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('word/document.xml',
                         '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                         '<w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')
    return parse_report_document(str(path))


def _fixture(tmp_path, monkeypatch):
    """建一个「预览并确认模板」阶段的模板任务：有候选模板、没有已确认模板。"""
    documents = [docx(tmp_path / 'a.docx', BASE_TEXT), docx(tmp_path / 'b.docx', '共计200条，重点关注教育。')]
    definition = build_structured_template(documents, 'comparison')
    store = Store(tmp_path / 'data')
    task = TaskState(id='task-template', kind='template', phase='awaiting_template_confirmation')
    ref = store.put_artifact(task.id, 'structured_template_candidate', definition)
    task.metadata['structured_template_ref'] = ref
    store.put_task(task)
    monkeypatch.setattr(main, 'store', store)
    return store, task.id, definition, ref


def _select(client, task_id, revision, *, block, text, choice, start=0):
    return client.post(f'/api/templates/{task_id}/draft/selection',
                       json={'expected_revision': revision, 'block': block, 'selected_text': text,
                             'choice': choice, 'start': start})


def test_draft_view_offers_choices_and_starts_empty(tmp_path, monkeypatch):
    _, task_id, _, _ = _fixture(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        view = client.get(f'/api/templates/{task_id}/draft')
        assert view.status_code == 200
        body = view.json()
        assert body['has_draft'] is False and body['draft'] is None
        assert [c['id'] for c in body['choices']][:3] == ['fixed', 'text', 'number']
        assert {c['scope'] for c in body['choices']} == {'selection', 'block'}
        assert body['definition']['blocks'], '预览需要能渲染的 blocks'


def test_selection_generates_placeholder_and_field_json(tmp_path, monkeypatch):
    store, task_id, definition, _ = _fixture(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        view = client.get(f'/api/templates/{task_id}/draft').json()
        response = _select(client, task_id, view['revision'], block=0, text='重点关注', choice='text')
        assert response.status_code == 200, response.text
        body = response.json()

        field = body['field']
        assert body['placeholder'] == f'{{{{{field["id"]}}}}}'
        assert body['preview_chip'] == '〔动态文字〕'
        assert field['id'].startswith('block_0_field_')
        assert field['owner'] == 'writer' and field['kind'] == 'text'
        assert field['block'] == 0
        assert field['sources'] == [{'file': definition['source_reports'][0]['path'],
                                     'sha256': definition['source_reports'][0]['sha256'],
                                     'block': 0, 'text': '重点关注'}]
        canonical = ''.join(p['text'] if 'text' in p else '{{' + p['field'] + '}}'
                            for p in definition['blocks'][0]['parts'])
        expected_start = canonical.find('重点关注')
        assert expected_start > 0
        assert field['origin'] == {'method': 'manual_selection', 'choice': 'text',
                                   'start': expected_start, 'end': expected_start + 4,
                                   'selected_text': '重点关注'}
        assert field['value_schema'] == {'type': 'string', 'minLength': 1}

        # 块内 parts 变成 固定文字 / 占位符 / 固定文字 的切分，且边缘空文字被丢掉
        block = body['block']
        assert block['parts'] == [{'text': '共计'}, {'field': 'block_0_field_1'}, {'text': '条，'},
                                  {'field': field['id']}, {'field': 'block_0_field_2'}, {'text': '。'}]

        # 发给模型的 JSON：schema 含新字段并要求必填
        draft = body['draft']
        assert field['id'] in draft['output_schema']['properties']
        assert field['id'] in draft['output_schema']['required']
        assert field['id'] not in draft['writer_schema'].get('required', []), 'writer_schema 只要求 writer 字段'
        assert field['id'] in draft['writer_schema']['properties']
        assert field['id'] in draft['pending']['writer_fields'], '新字段是 Writer 型，应进待填清单'
        assert draft['selection_log'][0]['choice'] == 'text'

        # 草稿落库：artifact 可取回，事件留痕
        stored = store.get_artifact(body['draft_ref'])
        assert stored['selection_log'] == draft['selection_log']
        assert any(e['type'] == 'template_manual_field_defined' and e['field_id'] == field['id']
                   for e in store.events(task_id))


def test_multiple_selections_accumulate_and_survive_refresh(tmp_path, monkeypatch):
    _, task_id, _, _ = _fixture(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        first = client.get(f'/api/templates/{task_id}/draft').json()
        one = _select(client, task_id, first['revision'], block=0, text='重点关注', choice='text').json()
        two = _select(client, task_id, one['revision'], block=0, text='共计', choice='fixed').json()
        assert [f['id'] for f in two['draft']['fields']] == ['block_0_field_1', 'block_0_field_2', one['field']['id']]
        assert len(two['draft']['selection_log']) == 2

    # 新进程内的新客户端 = 刷新页面；草稿从 Store 重读，不依赖内存
    with TestClient(main.app) as client:
        reloaded = client.get(f'/api/templates/{task_id}/draft').json()
    assert reloaded['has_draft'] is True
    assert reloaded['draft']['fields'] == two['draft']['fields']
    assert reloaded['draft']['blocks'] == two['draft']['blocks']
    assert reloaded['draft_ref'] == two['draft_ref']
    assert [entry['choice'] for entry in reloaded['draft']['selection_log']] == ['text', 'fixed']


def test_fixed_choice_restores_text_and_drops_covered_field(tmp_path, monkeypatch):
    _, task_id, _, _ = _fixture(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        revision = client.get(f'/api/templates/{task_id}/draft').json()['revision']
        # 预览里 '100' 显示为占位符芯片；浏览器把选区折算成标准文本 {{block_0_field_1}} 提交。
        # 声明为固定文字 → 字段定义消失，正文按历史原文还原成 '100'。
        body = _select(client, task_id, revision, block=0, text='{{block_0_field_1}}', choice='fixed').json()
        assert body['field'] is None and body['placeholder'] is None
        assert 'block_0_field_1' not in [f['id'] for f in body['draft']['fields']]
        restored = ''.join(p.get('text', '{{' + p.get('field', '') + '}}') for p in body['block']['parts'])
        # '100' 回到固定文字；同段另一个字段（'农业'）仍是占位符，不受影响
        assert restored == '共计100条，重点关注{{block_0_field_2}}。'
        assert body['selection']['removed_fields'] == ['block_0_field_1']
        assert body['selection']['display_text'] == '100'


def test_block_choices_for_paragraph_and_table(tmp_path, monkeypatch):
    _, task_id, _, _ = _fixture(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        revision = client.get(f'/api/templates/{task_id}/draft').json()['revision']
        paragraph = _select(client, task_id, revision, block=0, text='', choice='paragraph')
        assert paragraph.status_code == 200, paragraph.text
        body = paragraph.json()
        assert body['field']['kind'] == 'analysis' and body['field']['owner'] == 'writer'
        assert body['block']['parts'] == [{'field': body['field']['id']}]
        # 段落块不能选「表格」
        wrong = _select(client, task_id, body['revision'], block=0, text='', choice='table')
        assert wrong.status_code == 422 and wrong.json()['detail'] == 'choice_requires_table_block'


def test_chart_slot_is_recorded(tmp_path, monkeypatch):
    _, task_id, _, _ = _fixture(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        revision = client.get(f'/api/templates/{task_id}/draft').json()['revision']
        body = _select(client, task_id, revision, block=0, text='', choice='chart').json()
        assert body['field']['kind'] == 'chart'
        assert body['block']['slot_kind'] == 'chart'
        assert body['draft']['pending']['chart_slots'] == [0]


def test_undo_removes_last_selection_and_can_empty_the_draft(tmp_path, monkeypatch):
    _, task_id, _, _ = _fixture(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        revision = client.get(f'/api/templates/{task_id}/draft').json()['revision']
        first = _select(client, task_id, revision, block=0, text='重点关注', choice='text').json()
        second = _select(client, task_id, first['revision'], block=0, text='共计', choice='fixed').json()
        undone = client.post(f'/api/templates/{task_id}/draft/undo',
                             json={'expected_revision': second['revision']})
        assert undone.status_code == 200
        assert len(undone.json()['draft']['selection_log']) == 1
        again = client.post(f'/api/templates/{task_id}/draft/undo',
                            json={'expected_revision': undone.json()['revision']})
        assert again.status_code == 200 and again.json()['draft'] is None
        empty = client.post(f'/api/templates/{task_id}/draft/undo',
                            json={'expected_revision': again.json()['revision']})
        assert empty.status_code == 409 and empty.json()['detail'] == 'draft_empty'


def test_rejections(tmp_path, monkeypatch):
    store, task_id, _, _ = _fixture(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        revision = client.get(f'/api/templates/{task_id}/draft').json()['revision']
        not_found = _select(client, task_id, revision, block=0, text='这段原文里没有', choice='text')
        assert not_found.status_code == 422 and not_found.json()['detail'] == 'selection_not_found'
        unknown = _select(client, task_id, revision, block=0, text='共计', choice='nonsense')
        assert unknown.status_code == 422 and unknown.json()['detail'] == 'unknown_choice'
        stale = _select(client, task_id, revision - 1, block=0, text='共计', choice='text')
        assert stale.status_code == 409 and stale.json()['detail'] == 'stale_template_revision'
        bad_block = _select(client, task_id, revision, block=99, text='共计', choice='text')
        assert bad_block.status_code == 422 and bad_block.json()['detail'] == 'unknown_block'
        # 跨占位符的选区：'条，' + '{{block_0_field_2}}' 的一部分 → 显式拒绝而不是猜
        crossing = _select(client, task_id, revision, block=0, text='条，重点关注农业', choice='text')
        assert crossing.status_code == 422
        assert crossing.json()['detail'] in ('selection_not_found', 'selection_crosses_field')

        # 已确认模板不再接受手动定义
        state = store.get_task(task_id)
        state.metadata['confirmed_template_ref'] = 'template_version-x'
        store.put_task(state, state.revision)
        locked = client.get(f'/api/templates/{task_id}/draft')
        assert locked.status_code == 409 and locked.json()['detail'] == 'immutable_confirmed_template'

    # 没有候选模板 → 409
    orphan = TaskState(id='no-candidate', kind='template', phase='template_parsing')
    store.put_task(orphan)
    with TestClient(main.app) as client:
        missing = client.get('/api/templates/no-candidate/draft')
        assert missing.status_code == 409 and missing.json()['detail'] == 'structured_template_missing'


def test_draft_equals_replay_of_base_and_log(tmp_path, monkeypatch):
    _, task_id, definition, ref = _fixture(tmp_path, monkeypatch)
    with TestClient(main.app) as client:
        revision = client.get(f'/api/templates/{task_id}/draft').json()['revision']
        first = _select(client, task_id, revision, block=0, text='重点关注', choice='text').json()
        second = _select(client, task_id, first['revision'], block=0, text='共计', choice='percent').json()

        log = [{key: entry[key] for key in ('block', 'start', 'end', 'selected_text', 'choice')}
               for entry in second['draft']['selection_log']]
        replay = rebuild(definition, log, ref)
        assert replay['blocks'] == second['draft']['blocks']
        assert replay['fields'] == second['draft']['fields']
        assert replay['draft_digest'] == second['draft']['draft_digest']
        # 百分比字段是 data 型，需要另配数据来源
        percent = next(f for f in replay['fields'] if f['id'] == second['selection']['field_id'])
        assert percent['owner'] == 'data' and percent['needs_binding'] is True
        assert percent['value_schema']['pattern'].endswith('%$')
        assert second['draft']['pending']['needs_binding']


def test_apply_selection_rejects_partial_field_overlap(tmp_path):
    """单元级：选区只切到占位符一半时给出明确错误码，而不是产生错位定义。"""
    documents = [docx(tmp_path / 'a.docx', BASE_TEXT), docx(tmp_path / 'b.docx', '共计200条，重点关注教育。')]
    template = build_structured_template(documents, 'comparison')
    canonical = template['blocks'][0]['parts']
    marker = '{{' + canonical[3]['field'] + '}}'
    # 选区落在占位符文本里但少一个右花括号 → 部分覆盖，必须拒绝
    with pytest.raises(DraftError) as error:
        apply_selection(template, {'block': 0, 'selected_text': marker[:-1], 'choice': 'text', 'start': 0})
    assert error.value.code == 'selection_crosses_field'
