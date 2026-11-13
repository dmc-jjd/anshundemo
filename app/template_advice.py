"""确认后的**只读** LLM 审核：模型只返回修改意见，绝不写回模板与字段。

为什么不并进 `app/template_review.py`：那条链路产出 `template_version`（可写、会被 Writer
读取、决定报告长什么样）。本模块的产物 `template_advice` 只有意见列表，代码里**没有任何**
写回 `confirmed_template_ref` / `blocks` / `fields` 的路径——这是用户要求的「草稿确认后再走
一遍模型研判，但这次只返回修改意见」。

三条口径：
1. 输入只有两样：已确认模板（blocks/fields 的**只读**视图）+ 原始报告正文；不给模型任何可写通道。
2. 输出只认两级 `建议` / `重要`（`AdviceItem.severity` 是 `Literal`，自创第三级直接被拒）。
3. 结果落 `template_advice` 工件 + 一条 `template_advice_ready` 事件；读回走事件指针，
   **不推进 task revision**（只读审核不改任务状态）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ADVICE_KIND = 'template_advice'
SEVERITIES = ('重要', '建议')
MAX_BLOCK_CHARS = 600
MAX_SOURCE_CHARS = 24000
MAX_ITEMS = 40


class AdviceError(Exception):
    """带 HTTP 语义的拒绝：(status, code) 由路由层转成 HTTPException。"""

    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


class AdviceItem(BaseModel):
    """一条修改意见：只有级别、字段、意见、原文证据——没有字段定义。"""

    severity: Literal['建议', '重要']
    field_id: str = ''
    message: str = ''
    evidence: str = ''


class AdviceResult(BaseModel):
    """模型返回的唯一形状：意见列表。空列表是合法结果（没有意见）。"""

    items: list[AdviceItem] = Field(default_factory=list, max_length=MAX_ITEMS)


def advice_schema() -> dict:
    """发给模型的结构化输出约束（与 `AdviceResult` 同口径，enum 钉死两级）。"""
    return {
        'type': 'object',
        'properties': {
            'items': {
                'type': 'array', 'maxItems': MAX_ITEMS,
                'items': {
                    'type': 'object',
                    'properties': {
                        'severity': {'type': 'string', 'enum': list(SEVERITIES)},
                        'field_id': {'type': 'string'},
                        'message': {'type': 'string'},
                        'evidence': {'type': 'string'},
                    },
                    'required': ['severity', 'field_id', 'message', 'evidence'],
                    'additionalProperties': False,
                },
            },
        },
        'required': ['items'],
        'additionalProperties': False,
    }


def block_text(block: dict) -> str:
    """块的标准文本：字段占位符按 `{{字段id}}` 展开（与草稿/渲染器同一口径）。"""
    return ''.join(part['text'] if 'text' in part else '{{' + part['field'] + '}}'
                   for part in block.get('parts') or [])


def _clip(text: str, limit: int = MAX_BLOCK_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + '…（截断）'


def _source_reports(store, state) -> list[dict]:
    """原始报告正文：取自模板研判输入包（`template_input_ref`），按总量上限截断。"""
    ref = state.metadata.get('template_input_ref')
    packet = store.get_artifact(ref) if ref else {}
    reports, used = [], 0
    for index, document in enumerate((packet or {}).get('source_reports') or []):
        blocks = []
        for block in document.get('blocks') or []:
            text = _clip(block.get('text') or '')
            if not text:
                continue
            if used + len(text) > MAX_SOURCE_CHARS:
                break
            used += len(text)
            blocks.append({'index': block.get('index'),
                           'kind': block.get('kind', 'paragraph'), 'text': text})
        if blocks:
            reports.append({'id': document.get('id') or f'r{index + 1}',
                            'file': Path(document.get('path') or '').name,
                            'blocks': blocks})
        if used >= MAX_SOURCE_CHARS:
            break
    return reports


def make_payload(store, state) -> dict:
    """组装修审输入：已确认模板的只读视图 + 原始报告正文 + 本阶段提示词。"""
    from .agent import get_prompt
    ref = state.metadata.get('confirmed_template_ref')
    if not ref:
        raise AdviceError(409, 'confirmed_template_required')
    template = store.get_artifact(ref)
    fields = template.get('fields') or []
    blocks = template.get('blocks') or []
    return {
        'task': {'template_ref': ref, 'template_id': template.get('id'),
                 'template_version': template.get('version'),
                 'field_count': len(fields), 'block_count': len(blocks),
                 'review_mode': 'read_only_advice'},
        'instruction': get_prompt('template_analyst.advice'),
        'confirmed_template': {
            'blocks': [{'index': block.get('index'), 'kind': block.get('kind'),
                        'text': block_text(block), 'headers': block.get('headers')}
                       for block in blocks],
            'fields': [{'id': field.get('id'),
                        'display_name': field.get('display_name') or field.get('id'),
                        'kind': field.get('kind'), 'owner': field.get('owner'),
                        'semantic': field.get('semantic'), 'block': field.get('block'),
                        'binding': field.get('binding')}
                       for field in fields],
        },
        'source_reports': _source_reports(store, state),
    }


async def run_advice(store, state, ctx=None) -> dict:
    """调模型拿意见并落产物。**只写 `template_advice`**，不碰模板/字段/任务状态。"""
    from .model_client import invoke_agent
    if ctx is None:
        from .tool_executor import RunContext
        ctx = RunContext(store, state.id)
    payload = make_payload(store, state)
    answer = await invoke_agent('template_analyst', payload, AdviceResult, ctx,
                                response_schema=advice_schema())
    items = [item.model_dump() for item in answer.items if (item.message or '').strip()]
    result = {
        'items': items,
        'reviewed_template_ref': state.metadata.get('confirmed_template_ref'),
        'created_at': datetime.now(timezone.utc).isoformat(),
        'review_mode': 'read_only_advice',
    }
    ref = store.put_artifact(state.id, ADVICE_KIND, result)
    store.append_event(state.id, {'type': 'template_advice_ready', 'advice_ref': ref,
                                  'reviewed_template_ref': result['reviewed_template_ref'],
                                  'items': len(items),
                                  'important': sum(1 for item in items if item['severity'] == '重要')})
    return {**result, 'available': True, 'advice_ref': ref}


def latest_advice(store, state) -> dict:
    """读上次审核结果（事件指针 → 工件）；没有就 `available: false`。"""
    ref = None
    for event in reversed(store.events(state.id)):
        if event.get('type') == 'template_advice_ready' and event.get('advice_ref'):
            ref = event['advice_ref']
            break
    if not ref:
        return {'available': False, 'items': []}
    try:
        data = store.get_artifact(ref)
    except KeyError:
        return {'available': False, 'items': []}
    return {'available': True, 'advice_ref': ref,
            'items': data.get('items') or [],
            'reviewed_template_ref': data.get('reviewed_template_ref'),
            'created_at': data.get('created_at'),
            'review_mode': 'read_only_advice'}
