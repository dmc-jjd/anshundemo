"""模板任务软删除的 HTTP 入口（藏在 OpenAPI 之外）。

为什么单独成文件、而不是写进 `app/main.py`：与 `app/template_draft_api.py` 同一理由——
`tests/test_s6_api_parity.py` 钉死 main.py 的 52 个 `@app.<method>` 装饰器与 620 行预算，
`scripts/gate_openapi.py` 的摘要覆盖整份 `app.openapi()`。路由走独立
`include_in_schema=False` 的 APIRouter，main.py 只加 import + include_router 两行，
G-OPENAPI 逐字符不变。

软删除是标记而非真删：见 `app/api_views/template_library.py` 模块 docstring。
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .api_views.template_library import soft_delete_template

router = APIRouter(include_in_schema=False)


@router.delete('/api/template-tasks/{task_id}')
def delete_template_task(task_id: str, force: bool = False):
    """软删除模板任务；被报告任务引用时默认 409 并带引用数，force=true 才继续。"""
    from . import main
    error, payload = soft_delete_template(main.store, task_id, force)
    if error:
        body = {'detail': error[1]}
        if payload:
            body.update(payload)
        return JSONResponse(status_code=error[0], content=body)
    return payload
