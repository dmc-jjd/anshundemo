"""「一个包一个家」的解析层：`current_package` / `package_context` / `load_package`。

对外只暴露三个名字（其余走 `core.packages.registry` / `core.packages.context`）：
    current_package()          → str     当前上下文的包名（未设置回落默认包）
    package_context(pkg)       → 上下文管理器  作用域内把「当前包」设为 pkg（ContextVar）
    load_package(pkg=None)     → PackageLoad  解析结果（manifest/template/prompts/... 按需 + 带指纹缓存）

调用方纪律：
    * 解析「包内数据」时**别读模块级常量**，调 `load_package(pkg)` 或带 `package=` 的 getter；
    * `package` 只活在 Python 侧：不进 artifact payload、不进 TaskState 的产物字段（M1 边界）。
"""

from __future__ import annotations

from core.packages.context import (
    PackageRef,
    bind,
    current_package,
    current_ref,
    default_package,
    package_context,
    unbind,
)
from core.packages.registry import (
    PackageError,
    PackageLoad,
    bootstrap,
    cache_info,
    catalog,
    discover,
    invalidate,
    load,
    load_directory,
    package_dir,
    packages_root,
    preload,
)

#: 公开别名（任务书要求的入口名）。
load_package = load

__all__ = [
    'PackageError',
    'PackageLoad',
    'PackageRef',
    'bind',
    'bootstrap',
    'cache_info',
    'catalog',
    'current_package',
    'current_ref',
    'default_package',
    'discover',
    'invalidate',
    'load',
    'load_directory',
    'load_package',
    'package_context',
    'package_dir',
    'packages_root',
    'preload',
    'unbind',
]
