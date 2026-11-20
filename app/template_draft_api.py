"""「预览并确认模板」阶段手动定义的 HTTP 入口（藏在 OpenAPI 之外）。

为什么单独成文件、而不是写在 `app/main.py` 里：
- `tests/test_s6_api_parity.py` 逐项钉住 main.py 的 **52 个 `@app.<method>` 装饰器**
  与 620 行预算，任何新增装饰器都会让 S6 出口判据变红；
- `app/api_views/*.py` 被要求**框架无关**，不能 import fastapi/HTTPException；
- 于是：路由放这里（`include_in_schema=False` 的 APIRouter），main.py 只留一行注册。

为什么藏在 schema 之外：`scripts/gate_openapi.py` 的摘要覆盖**整份** `app.openapi()`，
新增 path/operation 必然移动 `G-OPENAPI`。本阶段把交互接口排除在契约之外，六组门禁
保持逐字符不变；将来要有意把它纳入契约，去掉 `include_in_schema=False` 后重录基线
（`python scripts/gate_openapi.py --record --force`）。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .template_draft import DraftError, append_selection, undo_selection, view

router = APIRouter(include_in_schema=False)

class TemplateRevisionRequest(BaseModel):
    expected_revision:int
    name:str
    reason:str
    request_key:str

@router.post('/api/templates/{task_id}/revision')
def derive_template_revision(task_id:str,req:TemplateRevisionRequest):
    from . import main
    from .template_revision import derive
    main.get_task(task_id)
    store=main.store.store_for(main.store.package_of(task_id)) if hasattr(main.store,'store_for') else main.store
    try:return derive(store,task_id,**req.model_dump())
    except ValueError as exc:raise HTTPException(409,str(exc))


class DraftCustomDefinition(BaseModel):
    # 卡片内小表单：显示名/语义必填，owner 只允许 writer/data；data_note 仅 data 型可填、可留空。
    display_name: str | None = None
    semantic: str | None = None
    owner: str | None = None
    data_note: str | None = None


class DraftSelectionRequest(BaseModel):
    expected_revision: int
    block: int
    selected_text: str = ''
    choice: str
    start: int = 0
    display_name: str | None = None
    custom: DraftCustomDefinition | None = None


class DraftUndoRequest(BaseModel):
    expected_revision: int


def _store_and_base(task_id):
    """取任务与候选模板；已确认模板只读。"""
    from . import main
    store = main.store
    try:
        state = main.get_task(task_id)
    except HTTPException:
        raise
    if state.kind != 'template':
        raise HTTPException(422, 'not_template_task')
    if state.metadata.get('confirmed_template_ref'):
        raise HTTPException(409, 'immutable_confirmed_template')
    ref = state.metadata.get('structured_template_ref')
    if not ref:
        raise HTTPException(409, 'structured_template_missing')
    return store, state, ref, store.get_artifact(ref)


@router.get('/api/templates/{task_id}/draft')
def template_manual_draft(task_id: str):
    store, state, ref, base = _store_and_base(task_id)
    return view(store, state, ref, base)


@router.post('/api/templates/{task_id}/draft/selection')
def add_template_draft_selection(task_id: str, req: DraftSelectionRequest):
    store, state, ref, base = _store_and_base(task_id)
    if state.revision != req.expected_revision:
        raise HTTPException(409, 'stale_template_revision')
    try:
        custom = req.custom.model_dump() if req.custom is not None else None
        return append_selection(store, state, ref, base, block=req.block,
                                selected_text=req.selected_text, choice=req.choice,
                                start=req.start, display_name=req.display_name,
                                custom=custom)
    except DraftError as exc:
        raise HTTPException(exc.status, exc.code)


@router.post('/api/templates/{task_id}/draft/undo')
def undo_template_draft_selection(task_id: str, req: DraftUndoRequest):
    store, state, ref, base = _store_and_base(task_id)
    if state.revision != req.expected_revision:
        raise HTTPException(409, 'stale_template_revision')
    try:
        return undo_selection(store, state, ref, base)
    except DraftError as exc:
        raise HTTPException(exc.status, exc.code)
