"""终稿人工审核：A4 渲染模型 + 人工覆盖 + 修改日志。

用户选定的方案 3（自研 A4 页 + contenteditable）的领域层：
- **全部占位符可编辑**：99 个占位符（`templates/anshun-colored/report.template.json`）默认值来自
  `app.export.template_values()`（与导出 Word 同一批计算值，不许有第二套算法）；
- **以提交的终稿为准**：人工覆盖存在 `TaskState.metadata['final_overrides']`，导出时经
  `export_docx(..., overrides=...)` 优先于计算结果；
- **必须有修改日志**：每次真正生效的保存落一个 `final_document_edit` 工件（before/after 逐槽留痕），
  无实际变化不建版本。

模板结构口径（`tests/test_core.py:test_template_has_definitions_before_source_body` 钉死）：
- 130 块里 99 块含「类型：…语义：…」，是**占位符定义与核验口径**，契约要求它在正文之前，不许删；
- 其余 31 块是正文。其中 blocks[0:2] 是定义区的两条导语（不含类型/语义判据），
  为保证正文以报告标题开头，它们带 `kind='preamble'` 排在 body 末尾，前端折回「核验口径」折叠区顶部渲染。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from core import paths
from core.schemas import now

from .export import template_values
from .ooxml import read_docx

EDIT_KIND = 'final_document_edit'
WRITABLE_STAGES = ('awaiting_final_review', 'facts_frozen')
CHART_SLOTS = {'CHART_1': 'sentiment', 'CHART_2': 'daily', 'CHART_3': 'platform',
               'CHART_4': 'theme', 'CHART_5': 'locality'}
SLOT_RE = re.compile(r'\{\{([A-Za-z0-9_]+)\}\}')
DEFINITION_MARKS = ('类型：', '语义：')


class FinalDocumentError(Exception):
    """带 HTTP 语义的拒绝：(status, code) 由路由层转成 HTTPException。"""

    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


# ---------------------------------------------------------------- 模板与清单

def template_path() -> Path:
    return paths.template_dir() / 'template-with-placeholders.docx'


def manifest() -> dict:
    return json.loads((paths.template_dir() / 'report.template.json').read_text(encoding='utf-8'))


def placeholders() -> list[dict]:
    return manifest()['placeholders']


def placeholder_ids() -> set[str]:
    return {item['id'] for item in placeholders()}


def _slot_codes() -> dict[str, str]:
    return {item['id']: item.get('slot_type', 'text') for item in placeholders()}


def _is_definition(block: dict) -> bool:
    return all(mark in block['text'] for mark in DEFINITION_MARKS)


# ---------------------------------------------------------------- 值解析

def _artifact(store, ref):
    if not ref:
        return {}
    try:
        return store.get_artifact(ref)
    except KeyError:
        return {}


def _computed_values(store, state) -> dict:
    facts = _artifact(store, state.fact_ref)
    draft = _artifact(store, state.draft_ref)
    return template_values(draft, facts, None, store=store)


def _display_value(values: dict, slot_id: str) -> str:
    value = values.get(slot_id)
    return f'{{{{{slot_id}}}}}' if value is None else str(value)


def _parts(text: str, values: dict, codes: dict[str, str], overrides: dict) -> list[dict]:
    parts, position = [], 0
    for match in SLOT_RE.finditer(text):
        if match.start() > position:
            parts.append({'type': 'text', 'text': text[position:match.start()]})
        slot_id = match.group(1)
        parts.append({
            'type': 'slot',
            'id': slot_id,
            'value': _display_value(values, slot_id),
            'code': codes.get(slot_id, 'text'),
            # 图表槽（CHART_n）不可编辑：覆盖它会让导出端找不到 {{CHART_n}} 而丢掉整张图。
            'editable': slot_id not in CHART_SLOTS,
            'edited': slot_id in overrides,
        })
        position = match.end()
    if position < len(text):
        parts.append({'type': 'text', 'text': text[position:]})
    return parts or [{'type': 'text', 'text': text}]


def _chart_block(store, facts: dict, block: dict, slot_id: str) -> dict:
    name = CHART_SLOTS[slot_id]
    png = None
    ref = (facts.get('result_refs') or {}).get('render_chart:' + name)
    if ref:
        try:
            png = store.get_artifact(ref).get('png_base64')
        except KeyError:
            png = None
    return {'index': block['index'], 'kind': 'chart', 'editable': False,
            'slot': slot_id, 'name': name,
            'png_data_url': f'data:image/png;base64,{png}' if png else None}


def _table_block(block: dict, values: dict, codes: dict[str, str], overrides: dict) -> dict:
    rows = []
    for row in block.get('rows', []):
        cells = []
        for cell in row:
            parts = _parts(cell, values, codes, overrides)
            if len(parts) == 1:
                cells.append(parts[0])
            else:
                cells.append({'type': 'mixed', 'text': cell, 'parts': parts})
        rows.append(cells)
    return {'index': block['index'], 'kind': 'table', 'editable': True,
            'text': block.get('text', ''), 'rows': rows}


# ---------------------------------------------------------------- 渲染模型

def render_model(store, state) -> dict:
    """终稿 A4 页的完整渲染模型（definition 99 块 / body 31 块）。"""
    computed = _computed_values(store, state)
    overrides = dict(state.metadata.get('final_overrides') or {})
    values = {**computed, **overrides}
    codes = _slot_codes()
    facts = _artifact(store, state.fact_ref)

    doc = read_docx(template_path())
    definition, report, preamble = [], [], []
    first_definition = next((i for i, block in enumerate(doc['blocks']) if _is_definition(block)), 0)
    for index, block in enumerate(doc['blocks']):
        bare = SLOT_RE.sub('', block['text']).strip()
        chart_slot = next((slot for slot in CHART_SLOTS
                           if bare == '' and f'{{{{{slot}}}}}' in block['text']), None)
        if _is_definition(block):
            parsed = ({'parts': _parts(block['text'], values, codes, overrides)}
                      if block['kind'] == 'paragraph'
                      else {'rows': _table_block(block, values, codes, overrides)['rows']})
            parts = parsed.get('parts') or []
            definition.append({'index': block['index'], 'kind': block['kind'],
                               'editable': any(p.get('editable') for p in parts if p['type'] == 'slot'),
                               'text': block['text'], **parsed})
        elif index < first_definition:
            preamble.append({'index': block['index'], 'kind': 'preamble', 'editable': False,
                             'text': block['text'], 'parts': [{'type': 'text', 'text': block['text']}]})
        elif block['kind'] == 'table':
            report.append(_table_block(block, values, codes, overrides))
        elif chart_slot:
            report.append(_chart_block(store, facts, block, chart_slot))
        else:
            parts = _parts(block['text'], values, codes, overrides)
            report.append({'index': block['index'], 'kind': 'paragraph',
                           'editable': any(p.get('editable') for p in parts if p['type'] == 'slot'),
                           'text': block['text'], 'parts': parts})

    return {
        'revision': int(state.metadata.get('final_document_version', 0)),
        'phase': state.phase,
        'sections': [
            {'name': 'definition', 'title': '核验口径', 'count': len(definition), 'blocks': definition},
            {'name': 'body', 'title': '', 'count': len(report) + len(preamble),
             'blocks': report + preamble},
        ],
        'overrides': overrides,
        'edited_count': len(overrides),
        'placeholder_count': len(placeholders()),
    }


# ---------------------------------------------------------------- 保存与日志

def _require_stage(state) -> None:
    if state.phase not in WRITABLE_STAGES:
        raise FinalDocumentError(409, 'invalid_final_review_stage')


def _edit_payload(version_no: int, revision: int, changes: list[dict], actor: str, kind: str) -> dict:
    return {'version_no': version_no, 'revision': revision, 'changes': changes,
            'changed_count': len(changes), 'saved_at': now(), 'actor': actor, 'kind': kind}


def _save_edit(store, state, version_no: int, changes: list[dict], actor: str, kind: str) -> dict:
    payload = _edit_payload(version_no, state.revision + 1, changes, actor, kind)
    ref = store.put_artifact(state.id, EDIT_KIND, payload)
    edits = list(state.metadata.get('final_document_edits') or [])
    edits.append(ref)
    state.metadata['final_document_edits'] = edits
    state.metadata['final_document_version'] = version_no
    store.put_task(state, state.revision)
    store.append_event(state.id, {'type': 'final_document_' + kind, 'version_no': version_no,
                                  'changed_count': len(changes),
                                  'slots': [change['slot'] for change in changes],
                                  'actor': actor, 'edit_ref': ref})
    return {'changed': True, 'version_no': version_no, 'revision': state.revision,
            'ref': ref, **payload}


def save_overrides(store, state, values: dict, actor: str = 'human') -> dict:
    """保存人工覆盖（只记真正变化的槽；无变化不建版本）。"""
    _require_stage(state)
    if not isinstance(values, dict):
        raise FinalDocumentError(422, 'invalid_values')
    unknown = sorted(set(values) - placeholder_ids())
    if unknown:
        raise FinalDocumentError(422, 'unknown_slot')
    computed = _computed_values(store, state)
    overrides = dict(state.metadata.get('final_overrides') or {})
    effective = {**computed, **overrides}
    changes, merged = [], dict(overrides)
    for slot_id, raw in values.items():
        after = str(raw)
        before = _display_value(effective, slot_id)
        if after == before:
            continue
        changes.append({'slot': slot_id, 'before': before, 'after': after})
        merged[slot_id] = after
    current = int(state.metadata.get('final_document_version', 0))
    if not changes:
        return {'changed': False, 'version_no': current, 'revision': state.revision,
                'changes': [], 'changed_count': 0}
    version_no = current + 1
    state.metadata['final_overrides'] = merged
    return _save_edit(store, state, version_no, changes, actor, 'save')


def reset_overrides(store, state, actor: str = 'human') -> dict:
    """清空人工覆盖，回到计算值；有覆盖时把「改回」逐槽记入版本日志。"""
    _require_stage(state)
    computed = _computed_values(store, state)
    overrides = dict(state.metadata.get('final_overrides') or {})
    current = int(state.metadata.get('final_document_version', 0))
    if not overrides:
        return {'changed': False, 'version_no': current, 'revision': state.revision,
                'changes': [], 'changed_count': 0}
    changes = [{'slot': slot_id, 'before': str(value), 'after': _display_value(computed, slot_id)}
               for slot_id, value in overrides.items()]
    version_no = current + 1
    state.metadata['final_overrides'] = {}
    return _save_edit(store, state, version_no, changes, actor, 'reset')


def version_log(store, state) -> list[dict]:
    """全部修改版本，倒序（最新在前）。"""
    versions = []
    for ref in state.metadata.get('final_document_edits') or []:
        try:
            payload = store.get_artifact(ref)
        except KeyError:
            continue
        versions.append({'ref': ref, **{key: payload.get(key) for key in
                                       ('version_no', 'revision', 'changes', 'changed_count',
                                        'saved_at', 'actor', 'kind')}})
    return sorted(versions, key=lambda item: (item.get('version_no') or 0, item.get('saved_at') or ''),
                  reverse=True)
