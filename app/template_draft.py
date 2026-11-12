"""「预览并确认模板」阶段的手动定义草稿：选区 → 选择题 → 占位符 + 字段 JSON。

设计文档：`docs/模板字段手动定义设计.md`

三条不变量（也是测试的判据）：
1. **可重放**：草稿 = `重建(base, selection_log)`。每次增删都从基线定义把日志重放一遍，
   因此 id 生成、parts 切分、字段删除都只由「基线 + 日志」决定，不存在增量不一致。
2. **可对齐**：草稿的 `blocks/fields` 与 `template.json`（候选模板）同构——只认
   `parts[{text|field}]` 与 `fields[{id,owner,kind,semantic,value_schema,binding,sources}]`，
   多的键（`origin`/`needs_binding`）只作溯源，不被渲染器读取。
3. **可校验**：选区的字符区间必须落在块的标准文本上（`{{字段id}}` 为字段占位符的
   文本形态），跨占位符的选区显式拒绝，不猜测。
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone

from .structured_template import _schema

DRAFT_KIND = 'manual_definition_draft'


class DraftError(Exception):
    """带 HTTP 语义的拒绝：(status, code) 由路由层转成 HTTPException。"""

    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


# ---------------------------------------------------------------- 选择题分类

# scope: selection = 需选中一段文字；block = 整块生效
# owner: writer = Writer 按本期证据填写；data = 由程序按数据绑定计算
CHOICES = [
    {
        'id': 'fixed', 'label': '固定文字（每月都一样）', 'group': '不动', 'scope': 'selection',
        'description': '这段是固定表述，不生成占位符；若它原本是字段，会还原成原文字。',
        'owner': None, 'kind': None,
    },
    {
        'id': 'text', 'label': '动态文字：人名 / 地名 / 机构 / 标题', 'group': '动态字段', 'scope': 'selection',
        'description': '每月都变，但不能算：交给 Writer 按本期证据填写。',
        'owner': 'writer', 'kind': 'text',
        'display_name': '动态文字',
        'semantic': '动态文字：人名、地名、机构或标题，随月份变化',
        'value_schema': {'type': 'string', 'minLength': 1},
    },
    {
        'id': 'number', 'label': '数字：条数 / 数量', 'group': '动态字段', 'scope': 'selection',
        'description': '本期统计值；需另行配置数据来源（未配置则保留待填）。',
        'owner': 'data', 'kind': 'number',
        'display_name': '数量',
        'semantic': '本期数量或条数，由程序按数据来源计算',
        'value_schema': {'type': 'string', 'pattern': r'^\d+$'},
    },
    {
        'id': 'amount', 'label': '金额：元 / 万元 / 亿元', 'group': '动态字段', 'scope': 'selection',
        'description': '本期金额；需另行配置数据来源。',
        'owner': 'data', 'kind': 'number',
        'display_name': '金额',
        'semantic': '本期金额',
        'value_schema': {'type': 'string', 'pattern': r'^\d+(?:\.\d+)?(?:万元|亿元|元)?$'},
    },
    {
        'id': 'percent', 'label': '占比：百分比', 'group': '动态字段', 'scope': 'selection',
        'description': '本期占比；需另行配置数据来源。',
        'owner': 'data', 'kind': 'number',
        'display_name': '占比',
        'semantic': '本期占比（百分比）',
        'value_schema': {'type': 'string', 'pattern': r'^\d+(?:\.\d+)?%$'},
    },
    {
        'id': 'date', 'label': '日期', 'group': '动态字段', 'scope': 'selection',
        'description': '本期日期；需另行配置数据来源。',
        'owner': 'data', 'kind': 'text',
        'display_name': '日期',
        'semantic': '本期日期',
        'value_schema': {'type': 'string', 'pattern': r'^\d{1,2}月\d{1,2}日$'},
    },
    {
        'id': 'period', 'label': '报告期号 / 月份', 'group': '动态字段', 'scope': 'selection',
        'description': '本期期号（整数）；需另行配置数据来源。',
        'owner': 'data', 'kind': 'number',
        'display_name': '报告期号',
        'semantic': '本期报告期号（整数）',
        'value_schema': {'type': 'string', 'pattern': r'^\d+$'},
    },
    {
        'id': 'paragraph', 'label': '整段由模型生成', 'group': '整块', 'scope': 'block',
        'description': '整段交给 Writer 按本期证据生成，不再保留固定文字。',
        'owner': 'writer', 'kind': 'analysis',
        'display_name': '模型生成段落',
        'semantic': '整段由 Writer 依据本期证据生成',
        'value_schema': {'type': 'string', 'minLength': 1},
    },
    {
        'id': 'table', 'label': '表格（整张表）', 'group': '整块', 'scope': 'block',
        'description': '整张表作为一个表格字段，列定义取表头；需配置数据来源或人工补填。',
        'owner': 'data', 'kind': 'table_rows',
        'display_name': '表格',
        'semantic': '表格数据行，列定义由表头固定',
        'value_schema': None,
    },
    {
        'id': 'chart', 'label': '图表位', 'group': '整块', 'scope': 'block',
        'description': '该块标成图表位，由本期数据绘制（尚未接入 docx 渲染，见设计文档遗留项）。',
        'owner': 'data', 'kind': 'chart',
        'display_name': '图表位',
        'semantic': '图表位置，由本期数据绘制',
        'value_schema': {'type': 'string'},
    },
]
CHOICE_BY_ID = {choice['id']: choice for choice in CHOICES}

FIELD_ID_TAIL = __import__('re').compile(r'_field_(\d+)$')


# ---------------------------------------------------------------- 文本与定位

def block_text(block: dict) -> str | None:
    """块的标准文本：字段占位符的文本形态是 `{{字段id}}`。

    只有普通段落块可编辑；表格块返回 None（整块生效，不做区间定位）。
    """
    if block.get('kind') != 'paragraph' or block.get('unmatched'):
        return None
    return ''.join(part['text'] if 'text' in part else '{{' + part['field'] + '}}'
                   for part in block['parts'])


def _part_length(part: dict) -> int:
    return len(part['text']) if 'text' in part else len('{{' + part['field'] + '}}')


def _locate(text: str, selected: str, hint: int = 0) -> tuple[int, int, int]:
    """在标准文本里定位选区，返回 (start, end, 出现次数)。

    hint 只在多重出现时用于挑最近的一处；找不到就显式拒绝，不做模糊匹配。
    """
    if not selected:
        raise DraftError(422, 'selection_required')
    if len(selected) > 500:
        raise DraftError(422, 'selection_too_long')
    positions, cursor = [], 0
    while True:
        index = text.find(selected, cursor)
        if index < 0:
            break
        positions.append(index)
        cursor = index + 1
    if not positions:
        raise DraftError(422, 'selection_not_found')
    start = min(positions, key=lambda index: abs(index - hint)) if hint else positions[0]
    return start, start + len(selected), len(positions)


# ---------------------------------------------------------------- 字段构造

def _next_field_id(definition: dict, block_index: int) -> str:
    """`block_<索引>_field_<全表递增序号>`：只由基线定义决定，可重放。"""
    highest = 0
    for field in definition['fields']:
        found = FIELD_ID_TAIL.search(field['id'])
        if found:
            highest = max(highest, int(found.group(1)))
    return f'block_{block_index}_field_{highest + 1}'


def _source(definition: dict, block_index: int, text: str) -> dict:
    reports = definition.get('source_reports') or [{'path': '', 'sha256': ''}]
    return {'file': reports[0]['path'], 'sha256': reports[0]['sha256'],
            'block': block_index, 'text': text}


def _make_field(definition: dict, block: dict, spec: dict, field_id: str,
                selected_text: str, origin: dict, display_name: str | None = None) -> dict:
    schema = spec['value_schema']
    if spec['id'] == 'table':
        headers = block.get('headers') or []
        schema = {'type': 'array', 'items': {'type': 'array', 'items': {'type': 'string'},
                                             'minItems': len(headers), 'maxItems': len(headers)}}
    return {
        'id': field_id,
        'owner': spec['owner'],
        'kind': spec['kind'],
        'display_name': display_name or spec.get('display_name') or spec['label'],
        'semantic': spec.get('semantic') or spec['label'],
        'value_schema': copy.deepcopy(schema),
        'block': block['index'],
        'binding': None,
        # 数据型字段没有数据来源就成了永远待填；标出来给后续配绑定的页面用。
        'needs_binding': spec['owner'] == 'data',
        'sources': [_source(definition, block['index'], selected_text)],
        'origin': origin,
    }


def _apply_range(definition: dict, block: dict, spec: dict, selected_text: str,
                 start_hint: int, display_name: str | None) -> tuple[dict, dict | None, dict]:
    text = block_text(block)
    if text is None:
        raise DraftError(422, 'block_not_editable')
    start, end, occurrences = _locate(text, selected_text, start_hint)

    spans, cursor = [], 0
    for part in block['parts']:
        length = _part_length(part)
        spans.append((cursor, cursor + length, part))
        cursor += length
    covered = [part for low, high, part in spans if 'field' in part and low < end and high > start]
    # 字段跨度必须被选区完整覆盖；部分覆盖会导致字段定义与占位符错位。
    field_spans = {part['field']: (low, high) for low, high, part in spans if 'field' in part}
    for field_id, (low, high) in field_spans.items():
        if low < end and high > start and not (low >= start and high <= end):
            raise DraftError(422, 'selection_crosses_field')
    covered_fields = [part['field'] for part in covered]
    # 选区的人类文本：占位符按它的历史原文还原（预览里显示的是芯片，见设计文档 §4）
    originals = {field['id']: (field.get('sources') or [{'text': ''}])[0].get('text', '')
                 for field in definition['fields']}
    human = ''.join(
        part['text'][max(low, start) - low:min(high, end) - low] if 'text' in part
        else originals.get(part['field'], '')
        for low, high, part in spans if low < end and high > start)

    if spec['id'] == 'fixed':
        # 固定文字：把选区还原成原文（含被覆盖字段的历史原文），删掉这些字段定义。
        parts, inserted = [], False
        for low, high, part in spans:
            if high <= start or low >= end:
                parts.append(copy.deepcopy(part))
                continue
            if 'text' in part and low < start:
                parts.append({'text': part['text'][:start - low]})
            if not inserted:
                parts.append({'text': human})
                inserted = True
            if 'text' in part and high > end:
                parts.append({'text': part['text'][end - low:]})
        result = copy.deepcopy(definition)
        result['fields'] = [field for field in result['fields'] if field['id'] not in covered_fields]
        target = next(item for item in result['blocks'] if item['index'] == block['index'])
        target['parts'] = [part for part in parts if part.get('text') != ''] or [{'text': human}]
        log = {'block': block['index'], 'start': start, 'end': end, 'choice': 'fixed',
               'selected_text': text[start:end], 'display_text': human, 'field_id': None,
               'removed_fields': covered_fields, 'occurrences': occurrences}
        return result, None, log

    field_id = _next_field_id(definition, block['index'])
    parts, inserted = [], False
    for low, high, part in spans:
        if high <= start or low >= end:
            parts.append(copy.deepcopy(part))
            continue
        if 'text' in part and low < start:
            parts.append({'text': part['text'][:start - low]})
        if not inserted:
            parts.append({'field': field_id})
            inserted = True
        if 'text' in part and high > end:
            parts.append({'text': part['text'][end - low:]})
        # 被完整覆盖的字段部件直接丢掉（由新字段接管这段）
    if not inserted:
        parts.append({'field': field_id})
    origin = {'method': 'manual_selection', 'choice': spec['id'],
              'start': start, 'end': end, 'selected_text': human}
    field = _make_field(definition, block, spec, field_id, human, origin, display_name)
    result = copy.deepcopy(definition)
    result['fields'] = [item for item in result['fields'] if item['id'] not in covered_fields] + [field]
    target = next(item for item in result['blocks'] if item['index'] == block['index'])
    target['parts'] = [part for part in parts if part.get('text') != '']
    log = {'block': block['index'], 'start': start, 'end': end, 'choice': spec['id'],
           'selected_text': text[start:end], 'display_text': human, 'field_id': field_id,
           'removed_fields': covered_fields, 'occurrences': occurrences}
    return result, field, log


def _apply_block(definition: dict, block: dict, spec: dict,
                 display_name: str | None) -> tuple[dict, dict, dict]:
    if spec['id'] == 'table' and block.get('kind') != 'table':
        raise DraftError(422, 'choice_requires_table_block')
    if spec['id'] in ('paragraph', 'chart') and block.get('kind') != 'paragraph':
        raise DraftError(422, 'choice_requires_paragraph_block')

    old_fields = [part['field'] for part in block.get('parts', []) if 'field' in part]
    text = block_text(block) or ' | '.join(block.get('headers') or []) or spec['label']
    field_id = _next_field_id(definition, block['index'])
    origin = {'method': 'manual_block_choice', 'choice': spec['id'], 'start': 0,
              'end': len(text), 'selected_text': text}
    field = _make_field(definition, block, spec, field_id, text, origin, display_name)
    result = copy.deepcopy(definition)
    result['fields'] = [item for item in result['fields'] if item['id'] not in old_fields] + [field]
    target = next(item for item in result['blocks'] if item['index'] == block['index'])
    target['parts'] = [{'field': field_id}]
    if spec['id'] == 'chart':
        target['slot_kind'] = 'chart'
    log = {'block': block['index'], 'start': 0, 'end': len(text), 'choice': spec['id'],
           'selected_text': text, 'field_id': field_id, 'removed_fields': old_fields,
           'occurrences': 1}
    return result, field, log


def apply_selection(definition: dict, entry: dict) -> tuple[dict, dict | None, dict]:
    """把一条选区/整块决定应用到定义上，返回 (新定义, 字段片段, 日志条目)。"""
    spec = CHOICE_BY_ID.get(entry.get('choice'))
    if spec is None:
        raise DraftError(422, 'unknown_choice')
    block = next((b for b in definition['blocks'] if b['index'] == entry.get('block')), None)
    if block is None:
        raise DraftError(422, 'unknown_block')
    if block.get('unmatched'):
        raise DraftError(422, 'block_requires_alignment_review')
    if spec['scope'] == 'block':
        return _apply_block(definition, block, spec, entry.get('display_name'))
    return _apply_range(definition, block, spec, entry.get('selected_text') or '',
                        int(entry.get('start') or 0), entry.get('display_name'))


# ---------------------------------------------------------------- 草稿重建

def rebuild(base_definition: dict, log: list[dict], base_ref: str = '') -> dict:
    """草稿 = 基线 + 重放日志。幂等：同日志必然得到同一份 blocks/fields。"""
    definition = copy.deepcopy(base_definition)
    entries = []
    for index, entry in enumerate(log):
        definition, field, applied = apply_selection(definition, entry)
        applied['seq'] = index + 1
        applied['choice_label'] = CHOICE_BY_ID[entry['choice']]['label']
        entries.append(applied)
    fields = definition['fields']
    draft = {
        'format_version': 1,
        'kind': DRAFT_KIND,
        'status': 'draft_manual_definition',
        'base_ref': base_ref,
        'base_template_id': base_definition.get('id'),
        'source_reports': base_definition.get('source_reports') or [],
        'blocks': definition['blocks'],
        'fields': fields,
        'output_schema': _schema(fields),
        'writer_schema': _schema(fields, True),
        'selection_log': entries,
        'pending': {
            'needs_binding': [f['id'] for f in fields if f.get('needs_binding')],
            'chart_slots': [b['index'] for b in definition['blocks'] if b.get('slot_kind') == 'chart'],
            'table_slots': [b['index'] for b in definition['blocks']
                            if b['kind'] == 'table' and any('field' in p for p in b['parts'])],
            'writer_fields': [f['id'] for f in fields if f['owner'] == 'writer'],
        },
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
    draft['draft_digest'] = hashlib.sha256(
        json.dumps({'blocks': draft['blocks'], 'fields': draft['fields'],
                    'log': [{k: v for k, v in e.items() if k != 'seq'} for e in entries]},
                   ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return draft


def definition_view(base_definition: dict, draft: dict | None) -> dict:
    """给前端 renderDocument 用的完整定义：草稿存在时用草稿的 blocks/fields。"""
    if not draft:
        return base_definition
    merged = copy.deepcopy(base_definition)
    merged['blocks'] = draft['blocks']
    merged['fields'] = draft['fields']
    merged['id'] = draft.get('base_template_id')
    return merged


def view(store, state, base_ref: str, base_definition: dict) -> dict:
    draft = current_draft(store, state)
    return {
        'revision': state.revision,
        'base_ref': base_ref,
        'draft_ref': state.metadata.get('manual_template_draft_ref'),
        'has_draft': bool(draft),
        'definition': definition_view(base_definition, draft),
        'draft': draft,
        'choices': CHOICES,
    }


def current_draft(store, state) -> dict | None:
    ref = state.metadata.get('manual_template_draft_ref')
    if not ref:
        return None
    try:
        return store.get_artifact(ref)
    except KeyError:
        return None


def _log_entries(draft: dict | None) -> list[dict]:
    if not draft:
        return []
    return [{key: entry[key] for key in ('block', 'start', 'end', 'selected_text', 'choice', 'display_name')
             if key in entry} for entry in draft.get('selection_log', [])]


def _save(store, state, base_ref: str, base_definition: dict, log: list[dict]) -> dict:
    """草稿落 Store：artifact + state.metadata 指针 + CAS 递增 revision。"""
    draft = rebuild(base_definition, log, base_ref)
    state.metadata['manual_template_draft_ref'] = store.put_artifact(state.id, DRAFT_KIND, draft)
    store.put_task(state, state.revision)
    return draft


def append_selection(store, state, base_ref: str, base_definition: dict, *, block: int,
                     selected_text: str, choice: str, start: int = 0,
                     display_name: str | None = None) -> dict:
    """追加一条选区决定。回显用的字段片段一律取自落盘后的草稿，避免与重放分叉。"""
    log = _log_entries(current_draft(store, state))
    log.append({'block': block, 'start': start, 'selected_text': selected_text,
                'choice': choice, 'display_name': display_name})
    draft = _save(store, state, base_ref, base_definition, log)
    ref = state.metadata['manual_template_draft_ref']
    applied = draft['selection_log'][-1]
    field = next((item for item in draft['fields'] if item['id'] == applied.get('field_id')), None)
    store.append_event(state.id, {
        'type': 'template_manual_field_defined',
        'choice': choice, 'block': block, 'field_id': applied.get('field_id'),
        'selected_text': applied.get('display_text') or applied.get('selected_text'),
        'draft_ref': ref, 'selection_count': len(draft['selection_log']),
    })
    return {
        'revision': state.revision,
        'draft_ref': ref,
        'has_draft': True,
        'selection': applied,
        'field': field,
        'placeholder': ('{{' + field['id'] + '}}') if field else None,
        'preview_chip': ('〔' + field['display_name'] + '〕') if field else None,
        'block': next(item for item in draft['blocks'] if item['index'] == block),
        'draft': draft,
        'definition': definition_view(base_definition, draft),
        'choices': CHOICES,
    }


def undo_selection(store, state, base_ref: str, base_definition: dict) -> dict:
    log = _log_entries(current_draft(store, state))
    if not log:
        raise DraftError(409, 'draft_empty')
    log.pop()
    draft = rebuild(base_definition, log, base_ref) if log else None
    if draft is None:
        state.metadata.pop('manual_template_draft_ref', None)
    else:
        ref = store.put_artifact(state.id, DRAFT_KIND, draft)
        state.metadata['manual_template_draft_ref'] = ref
    store.put_task(state, state.revision)
    store.append_event(state.id, {'type': 'template_manual_definition_undo',
                                  'selection_count': len(log)})
    return {
        'revision': state.revision,
        'draft_ref': state.metadata.get('manual_template_draft_ref'),
        'has_draft': bool(state.metadata.get('manual_template_draft_ref')),
        'draft': draft,
        'definition': definition_view(base_definition, draft),
        'choices': CHOICES,
    }
