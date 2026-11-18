"""模板候选字段编辑的 HTTP 入口（藏在 OpenAPI 之外）。

为什么单独成文件、而不是写进 `app/main.py`：
- `tests/test_s6_api_parity.py` 钉住 main.py 的 **52 个 `@app.<method>` 装饰器**与 620 行预算；
- `app/api_views/*.py` 被要求**框架无关**，不能 import fastapi/HTTPException；
- 于是路由放这里（`include_in_schema=False` 的 APIRouter），main.py 只留一行注册。
理由与 `app/template_draft_api.py` 完全一致；`G-OPENAPI` 摘要因此逐字符不变。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .api_views.template_field import EDITABLE_KEYS, edit_template_field
from .template_review import digest

router = APIRouter(include_in_schema=False)


class TemplateFieldEdit(BaseModel):
    expected_revision: int
    display_name: str | None = None
    semantic: str | None = None
    owner: str | None = None
    rule: str | None = None
    reason: str | None = None
    format: str | None = None


@router.put('/api/templates/{task_id}/fields/{field_id}')
def edit_template_candidate_field(task_id: str, field_id: str, req: TemplateFieldEdit):
    """改一个候选字段并立即落盘；刷新后仍是新值。"""
    from . import main
    store = main.store
    state = main.get_task(task_id)
    if state.kind != 'template':
        raise HTTPException(422, 'not_template_task')
    if state.metadata.get('confirmed_template_ref'):
        raise HTTPException(409, 'immutable_confirmed_template')
    ref = state.metadata.get('structured_template_ref')
    if not ref:
        raise HTTPException(409, 'structured_template_missing')
    if state.revision != req.expected_revision:
        raise HTTPException(409, 'stale_template_revision')
    patch = {key: getattr(req, key) for key in EDITABLE_KEYS if getattr(req, key) is not None}
    from .template_draft import current_draft, definition_view, rebuild, _log_entries, DRAFT_KIND, DraftError
    draft = current_draft(store, state)
    if draft:
        if draft.get('base_ref') != ref:
            raise HTTPException(409, 'stale_template_candidate')
        base = store.get_artifact(ref)
        error, _, field = edit_template_field(definition_view(base, draft), field_id, patch)
        if error:
            raise HTTPException(*error)
        edits = dict(draft.get('field_edits') or {})
        edits[field_id] = {**edits.get(field_id, {}), **patch}
        try:
            updated = rebuild(base, _log_entries(draft), ref, edits)
        except DraftError as exc:
            raise HTTPException(exc.status, exc.code)
        state.metadata['manual_template_draft_ref'] = store.put_artifact(task_id, DRAFT_KIND, updated)
        store.put_task(state, state.revision)
        store.append_event(task_id, {'type': 'template_field_edited', 'field': field_id,
                                    'changed': sorted(patch), 'draft_ref': state.metadata['manual_template_draft_ref']})
        return {'revision': state.revision, 'artifact_ref': ref, 'field': field, 'changed': sorted(patch)}
    error, template, field = edit_template_field(store.get_artifact(ref), field_id, patch)
    if error:
        raise HTTPException(*error)
    new_ref = store.put_artifact(task_id, 'structured_template_candidate', template)
    state.metadata['structured_template_ref'] = new_ref
    validation_ref = state.metadata.get('template_validation_ref')
    if validation_ref:
        # 与 PUT /definition 的 display_name 路径同一条约定：字段文本/归属变了，
        # 候选引用与哈希随之重算，否则确认时会被判成 stale 候选。
        validation = store.get_artifact(validation_ref)
        validation.update(candidate_ref=new_ref, candidate_hash=digest(template))
        state.metadata['template_validation_ref'] = store.put_artifact(task_id, 'template_validation', validation)
    store.put_task(state, state.revision)
    store.append_event(task_id, {'type': 'template_field_edited', 'field': field_id,
                                 'changed': sorted(patch), 'template_ref': new_ref})
    return {'revision': state.revision, 'artifact_ref': new_ref, 'field': field, 'changed': sorted(patch)}
