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

左栏「历史生成报告」的三条路由（列表 / 软删除 / 恢复）也挂在本 router 上，
同样 `include_in_schema=False`：`G-OPENAPI` 一个字节不动，`app/main.py` 不加装饰器。
软删除只写 `metadata['report_deleted_at']`，artifact 与磁盘 docx 一字节不动。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .api_views.task_resume import display_name
from .packages_api import connect_for, files_for
from .schemas import now

router = APIRouter(include_in_schema=False)

DOCX_MEDIA = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
KIND = 'final_docx'
META_KEY = 'final_docx_ref'
DELETED_KEY = 'report_deleted_at'


def _context(task_id: str):
    """任务与存储：请求期从 main 取（不 import 绑定）。任务不存在由 get_task 回 404。"""
    from . import main

    store = main.store
    state = main.get_task(task_id)
    return store, state


def _docx_path(store, task_id: str, ref: str):
    """真字节的落盘位置：**该任务所属包**的 `artifacts/{ref}.docx`（与 `app/main.py::export` 同口径）。

    为什么必须按任务取根（M3）：`app/config.DATA` 是**默认包**的数据根，B 任务用它就会把
    docx 写进/读自 A 的目录——隔离看起来生效、实际没生效。
    """
    return files_for(store, task_id) / f'{ref}.docx'


def _payload(store, state):
    """读回当前任务的 docx 元数据；ref 缺失或工件已不在 → None。"""
    ref = (state.metadata or {}).get(META_KEY)
    if not ref:
        return None
    try:
        data = store.get_artifact(ref)
    except (KeyError, ValueError):
        return None
    if not _docx_path(store, state.id, ref).exists():
        return None
    return {'ref': ref, 'bytes': int(data.get('bytes', 0)),
            'sha256': data.get('sha256'), 'updated_at': data.get('updated_at')}


def _mark(store, state, key, value):
    """写一个 metadata 键（`value=None` = 清除）；revision 冲突时重读重试（最多 3 次）。"""
    from .storage import ConflictError

    for _ in range(3):
        if value is None:
            state.metadata.pop(key, None)
        else:
            state.metadata[key] = value
        try:
            store.put_task(state, state.revision)
            return state
        except ConflictError:
            state = store.get_task(state.id)
    raise HTTPException(409, 'stale_task_revision')


def _persist(store, state, ref):
    """把 ref 写回 `state.metadata`；revision 冲突时重读重试（单写者，最多 3 次）。"""
    return _mark(store, state, META_KEY, ref)


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
    _docx_path(store, task_id, ref).write_bytes(body)
    _persist(store, state, ref)
    return {'ref': ref, 'bytes': len(body), 'sha256': digest}


@router.get('/api/tasks/{task_id}/final-docx')
def read_final_docx(task_id: str):
    """返回已保存的编辑版 docx；没有则 404 `final_docx_not_found`。"""
    store, state = _context(task_id)
    current = _payload(store, state)
    if current is None:
        # 这是**正常状态**（任务只有生成稿、没在编辑页保存过），不是路由/路径错误：
        # detail 带上可读说明，前端据此回退到 `metadata.draft_ref` 的产物下载。
        raise HTTPException(404, 'final_docx_not_found: 该任务尚未保存编辑版报告，请先在编辑页保存，或改用草稿导出。')
    return Response(_docx_path(store, task_id, current['ref']).read_bytes(), media_type=DOCX_MEDIA,
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


# ── 左栏「历史生成报告」：列表 / 软删除 / 恢复 ──────────────────────────

def _stamp(value):
    """ISO8601 → 带时区的 datetime；解析不了返回 None（坏值不参与排序）。"""
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _updated_at(store, state):
    """任务更新时间：最后一次事件 / `metadata['updated_at']` / `created_at` 取最大。"""
    stamps = [_stamp(state.created_at), _stamp((state.metadata or {}).get('updated_at'))]
    latest = store.events(state.id, 0, 1)
    if latest:
        stamps.append(_stamp(latest[-1].get('at')))
    stamps = [value for value in stamps if value is not None]
    return max(stamps).isoformat() if stamps else now()


def _size(path):
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def _docx_refs(store, state):
    """该任务在磁盘上**真有 docx 字节**的工件 id（新→旧）。

    为什么查 artifacts 表而不只读 metadata：`app/main.py::export`
    （`POST /api/tasks/{id}/exports`）只把 `{ref}.docx` 落盘 + 写一行 artifacts，
    **不回写 metadata**；只认 metadata 会漏掉这些「已生成的报告产物」，而编辑器
    正是按 `/api/artifacts/{ref}/download` 读它们的（且该口径与 `{ref}.docx` 完全一致）。

    M3：连接与目录都按**任务所属包**取（`connect_for` / `files_for`）——B 任务的列表
    不能查 A 的库、也不能看 A 的 artifacts 目录。
    """
    folder = files_for(store, state.id)
    with connect_for(store, state.id) as conn:
        rows = conn.execute('SELECT id FROM artifacts WHERE task_id=? ORDER BY rowid DESC',
                            (state.id,)).fetchall()
    return [row['id'] for row in rows if (folder / f"{row['id']}.docx").exists()]


def _report_item(store, state, index):
    """一条列表项；**什么报告都没有的任务返回 None**（不进列表）。

    判定：有 `final_docx_ref` 且字节齐 → `saved`；否则只要有别的可读 docx 产物 → `draft`。
    报告名优先 `metadata['template_name']`，没有则用 `/api/tasks` 的派生 `display_name`。
    """
    name = str((state.metadata or {}).get('template_name') or '').strip() or display_name(state, index)
    updated = _updated_at(store, state)
    current = _payload(store, state)
    if current is not None:
        return {'task_id': state.id, 'name': name, 'updated_at': updated, 'status': 'saved',
                'bytes': _size(_docx_path(store, state.id, current['ref'])),
                'url': f'/api/tasks/{state.id}/final-docx'}
    refs = _docx_refs(store, state)
    if not refs:
        return None
    return {'task_id': state.id, 'name': name, 'updated_at': updated, 'status': 'draft',
            'bytes': _size(files_for(store, state.id) / f'{refs[0]}.docx'),
            'url': f'/api/artifacts/{refs[0]}/download'}


@router.get('/api/reports/editable')
def list_editable_reports():
    """左栏列表：只列有报告的任务，已软删的默认滤掉，更新时间倒序。

    `url` 是「该条目点开读哪份 docx」的现成地址：`saved` 走编辑版，`draft` 走产物下载。
    """
    from . import main

    store = main.store
    index = {item['id']: item for item in main.templates()}
    items = [item for item in (_report_item(store, state, index) for state in store.list_tasks()
                               if not (state.metadata or {}).get(DELETED_KEY)) if item is not None]
    return sorted(items, key=lambda item: item['updated_at'], reverse=True)


@router.delete('/api/reports/editable/{task_id}')
def delete_editable_report(task_id: str):
    """软删除：只写 `metadata['report_deleted_at']`（ISO8601），artifact 与磁盘文件不动。

    已删再删 → 200 幂等（返回首次的时间戳，不重复写 revision）。
    """
    store, state = _context(task_id)
    stamp = (state.metadata or {}).get(DELETED_KEY)
    if not stamp:
        stamp = now()
        _mark(store, state, DELETED_KEY, stamp)
    return {'task_id': task_id, 'deleted_at': stamp}


@router.post('/api/reports/editable/{task_id}/restore')
def restore_editable_report(task_id: str):
    """恢复：清掉软删时间戳（幂等）。界面先不做入口，接口先埋。"""
    store, state = _context(task_id)
    if (state.metadata or {}).get(DELETED_KEY):
        _mark(store, state, DELETED_KEY, None)
    return {'task_id': task_id, 'restored': True}
