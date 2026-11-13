"""首页两个新模块的 HTTP 入口：今日热点话题 + 社媒热榜（都藏在 OpenAPI 之外）。

为什么单独成文件：`tests/test_s6_api_parity.py` 钉住 `app/main.py` 的 **52 个 `@app.<method>`
装饰器**与 ≤620 行预算；`scripts/gate_openapi.py` 的摘要覆盖整份 `app.openapi()`，新增 path 必然
移动 `G-OPENAPI`。故沿用「`include_in_schema=False` 的 APIRouter + main.py 一行注册」
（与 `app/template_draft_api.py` / `app/template_advice_api.py` / `app/final_document_api.py` 同一条约定）。

缓存语义（用户明确要求）：`GET /api/hotspot` **永不刷新**，只有 `POST /api/hotspot/collect`
才重新采集——「下次进入时不点采集按钮就不会变」。无缓存时 GET 只回空态，绝不顺手触发一次采集。

错误语义：搜索未配置 → **409 `search_not_configured`**（不许返回编造内容）；模型失败 / 结构
校验失败 → 502 对应错误码（`hotspot_model_failed` / `hotspot_schema_invalid`）。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from . import hotspot
from .social_hotlist import profile as social_profile

router = APIRouter(include_in_schema=False)


def _store():
    """请求期从 main 取（不在 import 期绑定，保持注入面柔性）。"""
    from . import main

    return main.store


@router.get('/api/hotspot')
def hotspot_view():
    return hotspot.view(_store())


@router.post('/api/hotspot/collect')
async def hotspot_collect():
    from .hotspot import HotspotError

    try:
        return await hotspot.collect(_store())
    except HotspotError as exc:
        raise HTTPException(exc.status, str(exc))


@router.get('/api/social-hotlist')
def social_hotlist(platform: str = 'weibo'):
    try:
        return social_profile(platform)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
