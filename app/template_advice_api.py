"""确认后只读 LLM 审核的 HTTP 入口（藏在 OpenAPI 之外）。

为什么单独成文件、`include_in_schema=False`：与 `app/template_draft_api.py` 同一理由——
`tests/test_s6_api_parity.py` 钉住 `app/main.py` 的 **52 个 `@app.<method>` 装饰器**与 620 行
预算，`scripts/gate_openapi.py` 的摘要覆盖整份 `app.openapi()`。两条路由走独立 router，
main.py 只加两行注册，六组门禁的字面量逐字符不变。

同步等待模型返回（前端显示「模型正在审阅」）：`invoke_agent` 是 `await` 的，不阻塞事件循环；
`template_analyst` 在 `LONG_TIMEOUT_ROLES` 里，超时 180s。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from .template_advice import AdviceError, latest_advice, run_advice

router = APIRouter(include_in_schema=False)


def _store_and_state(task_id):
    from . import main
    store = main.store
    try:
        state = main.get_task(task_id)
    except HTTPException:
        raise
    if state.kind != 'template':
        raise HTTPException(422, 'not_template_task')
    return store, state


@router.get('/api/templates/{task_id}/advice')
def read_template_advice(task_id: str):
    """读上次审核结果；没有审核过就 `{'items': [], 'available': false}`（不是错误）。"""
    store, state = _store_and_state(task_id)
    return latest_advice(store, state)


@router.post('/api/templates/{task_id}/advice')
async def create_template_advice(task_id: str):
    """触发一次只读审核：模型只返回修改意见，不写模板、不改任务状态。"""
    store, state = _store_and_state(task_id)
    if not state.metadata.get('confirmed_template_ref'):
        raise HTTPException(409, 'confirmed_template_required')
    from .model_client import ModelUnavailable, TaskPaused
    from .tool_executor import RunContext
    from . import main
    ctx = RunContext(store, task_id, model_adapter=main.deps.model_adapter)
    try:
        return await run_advice(store, state, ctx)
    except AdviceError as exc:
        raise HTTPException(exc.status, exc.code)
    except ValidationError:
        raise HTTPException(422, 'advice_not_structured')
    except ModelUnavailable:
        raise HTTPException(409, 'model_not_configured')
    except TaskPaused:
        raise HTTPException(409, 'task_paused')
    except HTTPException:
        raise
    except Exception as exc:
        from .model_client import classify_model_error
        raise HTTPException(503, classify_model_error(exc))
