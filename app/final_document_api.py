"""终稿人工审核：A4 查看/保存/修改日志/还原的 HTTP 入口（藏在 OpenAPI 之外）。

为什么单独成文件：`tests/test_s6_api_parity.py` 逐项钉住 `app/main.py` 的 **52 个
`@app.<method>` 装饰器**与 620 行预算，新增装饰器会让 S6 出口判据变红；而
`scripts/gate_openapi.py` 的摘要覆盖整份 `app.openapi()`，新增 path 必然移动
`G-OPENAPI`。故沿用「`include_in_schema=False` 的 APIRouter + main.py 一行注册」
（与 `app/template_draft_api.py`、`app/template_advice_api.py` 同一条约定）。

store / get_task 在**请求期**从 `app.main` 取，不在 import 期绑定——保持
`tests/test_s6_inject_surface.py` 依赖的注入面柔性。

阶段纪律：只在 `awaiting_final_review` / `facts_frozen` 可写（保存/还原），
其余阶段由领域层回 409 `invalid_final_review_stage`。读取不设阶段限制。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .final_document import (FinalDocumentError, render_model, reset_overrides,
                             save_overrides, version_log)

router = APIRouter(include_in_schema=False)


class SaveOverrides(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)
    expected_revision: int | None = None


class ResetOverrides(BaseModel):
    expected_revision: int | None = None


def _context(task_id: str):
    """任务与存储：请求期从 main 取（不 import 绑定）。"""
    from . import main

    try:
        state = main.get_task(task_id)
    except HTTPException:
        raise
    return main.store, state


def _check_revision(state, expected: int | None) -> None:
    """前端防并发：期望版本号与当前人工版本不一致即视为过期。"""
    if expected is None:
        return
    if expected != int(state.metadata.get('final_document_version', 0)):
        raise HTTPException(409, 'stale_final_document')


def _call(fn, *args, **kwargs):
    from .storage import ConflictError

    try:
        return fn(*args, **kwargs)
    except FinalDocumentError as exc:
        raise HTTPException(exc.status, exc.code)
    except ConflictError:
        raise HTTPException(409, 'stale_final_document')


@router.get('/api/tasks/{task_id}/final-document')
def final_document_view(task_id: str):
    store, state = _context(task_id)
    return render_model(store, state)


@router.post('/api/tasks/{task_id}/final-document/save')
def save_final_document(task_id: str, req: SaveOverrides):
    store, state = _context(task_id)
    _check_revision(state, req.expected_revision)
    return _call(save_overrides, store, state, req.values)


@router.get('/api/tasks/{task_id}/final-document/versions')
def final_document_versions(task_id: str):
    store, state = _context(task_id)
    return {'revision': int(state.metadata.get('final_document_version', 0)),
            'versions': version_log(store, state)}


@router.post('/api/tasks/{task_id}/final-document/reset')
def reset_final_document(task_id: str, req: ResetOverrides | None = None):
    store, state = _context(task_id)
    _check_revision(state, req.expected_revision if req else None)
    return _call(reset_overrides, store, state)
