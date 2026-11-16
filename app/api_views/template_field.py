"""模板候选字段的人工编辑：显示名称 / 字段语义 / 归属。

只有**可编辑产物**能改：`status=candidate_requires_review` 的候选模板（「模型研判后模板」
与「本地比对初稿」都是这个 status）。已确认版本（`status=confirmed_by_human`）一律拒绝并给
明确错误码——用户「改了没反应」正是本次要消灭的缺陷，所以这里绝不静默忽略。

为什么改完要重算 `output_schema` / `writer_schema` / `id`：归属决定字段由数据工具还是 Writer
填写，两份 schema 都是从 `fields` 派生的，改归属必须同步重算，否则确认后的模板与 schema 不一致。
"""
from __future__ import annotations

import copy
import hashlib
import json

EDITABLE_KEYS = ('display_name', 'semantic', 'owner')
OWNERS = ('data', 'writer')
EDITABLE_STATUSES = ('candidate_requires_review',)


def _digest(template):
    return hashlib.sha256(json.dumps(template, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def edit_template_field(template, field_id, patch):
    """返回 `(error, template, field)`；`error=(status, detail)` 由路由函数转成 HTTP 错误。

    错误码一律显式：已确认版本 `immutable_confirmed_template`、字段不存在
    `template_field_not_found`、非法键/空值 `invalid_template_field_patch`、
    工具绑定字段的归属不放行 `field_binding_locked`（归属由绑定决定，人工改会让取数规则失真）。
    """
    status = str(template.get('status') or '')
    if status == 'confirmed_by_human':
        return (409, 'immutable_confirmed_template'), None, None
    if status not in EDITABLE_STATUSES:
        return (409, 'template_not_editable'), None, None
    keys = set(patch or {})
    if not keys or keys - set(EDITABLE_KEYS):
        return (422, 'invalid_template_field_patch'), None, None
    result = copy.deepcopy(template)
    field = next((item for item in result.get('fields') or [] if item.get('id') == field_id), None)
    if field is None:
        return (404, 'template_field_not_found'), None, None
    changed = []
    if 'display_name' in keys:
        text = str(patch['display_name'] or '').strip()
        if not text:
            return (422, 'display_name_required'), None, None
        if text != field.get('display_name'):
            field['display_name'] = text
            changed.append('display_name')
    if 'semantic' in keys:
        text = str(patch['semantic'] or '').strip()
        if not text:
            return (422, 'semantic_required'), None, None
        if text != field.get('semantic'):
            field['semantic'] = text
            changed.append('semantic')
    if 'owner' in keys:
        owner = str(patch['owner'] or '').strip()
        if owner not in OWNERS:
            return (422, 'invalid_field_owner'), None, None
        if owner != field.get('owner'):
            # 归属由绑定决定：有取数工具的字段改成 Writer 会让取数规则与 schema 打架，显式拒绝。
            if field.get('binding'):
                return (422, 'field_binding_locked'), None, None
            field['owner'] = owner
            changed.append('owner')
    if not changed:
        return None, result, field
    field['human_edited'] = sorted(set(field.get('human_edited') or []) | set(changed))
    from ..structured_template import _schema
    result['output_schema'] = _schema(result['fields'])
    result['writer_schema'] = _schema(result['fields'], True)
    result['id'] = 'structured-' + _digest(result)[:20]
    return None, result, field
