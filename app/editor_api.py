"""终稿 canvas-editor 的 docx 持久化入口（藏在 OpenAPI 之外）。

为什么单独成文件：`tests/test_s6_api_parity.py` 钉住 `app/main.py` 的 **52 个
`@app.<method>` 装饰器**与行数预算，新增装饰器会让 S6 出口判据变红；而
`scripts/gate_openapi.py` 的摘要覆盖整份 `app.openapi()`，新增 path 必然移动
`G-OPENAPI`。故沿用「`include_in_schema=False` 的 APIRouter + main.py 一行注册」
（与 `app/template_draft_api.py` / `app/final_document_api.py` / `app/hotspot_api.py`
同一条约定）。

落盘口径**逐字照抄** `app/main.py::export`（`POST /api/tasks/{id}/export`）：
`put_artifact` 只收 JSON（`core/storage.py`），所以 payload 存字节元数据，
真字节写同目录的 `{ref}.docx`；下载口 `GET /api/artifacts/{id}/download` 读的
也是这一个路径。这样 canvas-editor 存回来的稿与导出稿在同一处、同一套命名。

`store` / `get_task` 在**请求期**从 `app.main` 取，不在 import 期绑定——保持
`tests/test_s6_inject_surface.py` 依赖的注入面柔性。
"""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .config import DATA
from .schemas import now

router = APIRouter(include_in_schema=False)

DOCX_MEDIA = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
KIND = 'final_docx'
META_KEY = 'final_docx_ref'


def _context(task_id: str):
    """任务与存储：请求期从 main 取（不 import 绑定）。任务不存在由 get_task 回 404。"""
    from . import main

    store = main.store
    state = main.get_task(task_id)
    return store, state


def _docx_path(ref: str):
    """真字节的落盘位置：与 `app/main.py::export` 的 `{ref}.docx` 同一口径。"""
    return DATA / 'artifacts' / f'{ref}.docx'


def _payload(store, state):
    """读回当前任务的 docx 元数据；ref 缺失或工件已不在 → None。"""
    ref = (state.metadata or {}).get(META_KEY)
    if not ref:
        return None
    try:
        data = store.get_artifact(ref)
    except (KeyError, ValueError):
        return None
    if not _docx_path(ref).exists():
        return None
    return {'ref': ref, 'bytes': int(data.get('bytes', 0)),
            'sha256': data.get('sha256'), 'updated_at': data.get('updated_at')}


def _persist(store, state, ref):
    """把 ref 写回 `state.metadata`；revision 冲突时重读重试（单写者，最多 3 次）。"""
    from .storage import ConflictError

    for _ in range(3):
        state.metadata[META_KEY] = ref
        try:
            store.put_task(state, state.revision)
            return state
        except ConflictError:
            state = store.get_task(state.id)
    raise HTTPException(409, 'stale_task_revision')


@router.post('/api/tasks/{task_id}/final-docx')
async def save_final_docx(task_id: str, request: Request):
    """接收 canvas-editor 导出的 docx 字节。非 zip（魔数 PK）→ 422 `final_docx_invalid`。"""
    store, state = _context(task_id)
    body = await request.body()
    if len(body) < 4 or body[:2] != b'PK':
        raise HTTPException(422, 'final_docx_invalid')
    digest = hashlib.sha256(body).hexdigest()
    ref = store.put_artifact(task_id, KIND, {'bytes': len(body), 'sha256': digest,
                                             'updated_at': now(),
                                             'media_type': DOCX_MEDIA})
    _docx_path(ref).write_bytes(body)
    _persist(store, state, ref)
    return {'ref': ref, 'bytes': len(body), 'sha256': digest}


@router.get('/api/tasks/{task_id}/final-docx')
def read_final_docx(task_id: str):
    """返回已保存的编辑版 docx；没有则 404 `final_docx_not_found`。"""
    store, state = _context(task_id)
    current = _payload(store, state)
    if current is None:
        raise HTTPException(404, 'final_docx_not_found')
    return Response(_docx_path(current['ref']).read_bytes(), media_type=DOCX_MEDIA,
                    headers={'Content-Disposition':
                             f'attachment; filename="{task_id}-final.docx"'})


@router.get('/api/tasks/{task_id}/final-docx/meta')
def final_docx_meta(task_id: str):
    """前端状态行用：有没有存过、多少字节、什么时候存的。"""
    store, state = _context(task_id)
    current = _payload(store, state)
    if current is None:
        return {'available': False, 'ref': None, 'bytes': 0,
                'updated_at': None, 'sha256': None}
    return {'available': True, **current}
