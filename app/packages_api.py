"""客户包注册表：`GET /api/packages` + 建任务/上传时的包校验。

为什么单独成文件而不是塞进 `app/api_views/`：
    `tests/test_s6_api_parity.py` 把 `api_views/**` 钉成「框架无关」（不许 import fastapi），
    而本模块要注册 APIRouter。与 `hotspot_api.py` 同一约定：`include_in_schema=False`，
    `app/main.py` 只加一行 `include_router`，G-OPENAPI 不应变。

错误语义（M2 的关键：坏包绝不回落默认包）：
    - 未声明的包名       → 404 `package_not_found:<包>`
    - 在册但不可用       → 422 `package_unavailable:<包>:<原因>`
    - 空                 → 部署默认包（`REPORT_PACKAGE`）
    绝不「坏包就悄悄用默认包跑」——那会让操作员以为任务建成功了，产物却属于另一个客户。

`GET /api/packages` 的 `usable:false` 条目**仍在列表里**：注册表要能描述坏包，
否则运维看不见它。健康判定按需加载（manifest + template.json + 提示词 bundle），
不解析任何包内文件时启动期只花一次 scandir（100 包实测 ~1 ms）。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from core.packages import registry as package_registry

router = APIRouter(include_in_schema=False)


def catalog() -> list[dict]:
    """注册表快照（按需加载 + 指纹缓存）；坏包带 error 但仍在列表里。"""
    return list(package_registry.catalog())


def resolve_package(name: str = '') -> str:
    """校验目标包并返回包名；空 = 部署默认包。坏包/未知包明确拒绝（不静默回落）。"""
    from core.packages import context as package_context

    target = str(name or '').strip() or package_context.default_package()
    entry = next((item for item in catalog() if item['package'] == target), None)
    if entry is None:
        raise HTTPException(404, f'package_not_found:{target}')
    if not entry.get('usable'):
        raise HTTPException(422, f"package_unavailable:{target}:{entry.get('error') or 'unknown'}")
    return target


def uploads_for(store, package: str = '', default=None) -> Path:
    """目标包的上传目录；默认包优先用宿主注入的 `default`（`app/main.py:UPLOADS` 的测试注入面）。"""
    from core.packages import context as package_context

    target = str(package or '').strip() or package_context.default_package()
    if default is not None and target == package_context.default_package():
        return Path(default)
    helper = getattr(store, 'uploads_for', None)
    if callable(helper):
        return Path(helper(target))
    return Path(default) if default is not None else Path(store.root) / 'uploads'


def files_for(store, task_id: str) -> Path:
    """任务所属包的 artifacts 目录；旧 Store 退化为 `<root>/artifacts`。"""
    helper = getattr(store, 'files_for', None)
    return helper(task_id) if callable(helper) else Path(store.files)


def root_for(store, task_id: str) -> Path:
    """任务所属包的**数据根**（`hotspot/`、`reference-comparison/` 这类非 artifacts 目录用）。"""
    helper = getattr(store, 'root_for', None)
    return Path(helper(task_id)) if callable(helper) else Path(store.root)


def connect_for(store, task_id: str):
    """任务所属包的数据库连接；旧 Store 退化为 `store.connect()`。"""
    helper = getattr(store, 'connect_for', None)
    return helper(task_id) if callable(helper) else store.connect()


def store_for(store, package: str = '') -> object:
    """某个包的 Store（热点模块这类**无 task 上下文**的面用）；旧 Store 原样返回。"""
    helper = getattr(store, 'store_for', None)
    return helper(package or None) if callable(helper) else store


def artifact_file(store, ref: str, suffix: str = '.docx') -> Path:
    """`{ref}{suffix}` 的落盘位置（按 artifact 归属包解析）；旧 Store 退化为旧口径。"""
    helper = getattr(store, 'artifact_file', None)
    return helper(ref, suffix) if callable(helper) else Path(store.files) / f'{ref}{suffix}'


def resolve_files(store, ids: list[str], package: str = '', default=None) -> list[str]:
    """上传文件 id → 路径：先在目标包 uploads 找，再回落默认包 uploads。

    回落默认包只针对**文件查找**（旧上传仍在默认包，不能因为换包就 404），
    与「坏包不回落」是两件事：包本身必须可用，才走到这里。
    """
    folder = uploads_for(store, package, default)
    fallback = Path(default) if default is not None else uploads_for(store)
    found_paths: list[str] = []
    for fid in ids:
        found = sorted(Path(folder).glob(f'{fid}.*')) or sorted(fallback.glob(f'{fid}.*'))
        if not found:
            raise HTTPException(404, f'file_not_found: {fid}')
        found_paths.append(str(found[0]))
    return found_paths


def idempotent(store, key: str, value: str, package: str = '') -> str:
    """幂等键：按包落库；显式给根的旧 Store 没有 `package` 参数，退化为旧调用。"""
    try:
        return store.idempotent(key, value, package)
    except TypeError:
        return store.idempotent(key, value)


@router.get('/api/packages')
def packages() -> list[dict]:
    """客户包注册表：`[{package,name,report_type,version,usable,status,error}]`。"""
    return catalog()
