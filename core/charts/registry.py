"""图表实例注册表：从客户包 `template.json` 的 `charts` 段读图表实例定义。

与 `core/tools/vocabulary.py` 同构（M1 起两处共用**同一份** `template.json` 缓存）：
每个 getter 都带 `package=None`，`None` = 当前上下文（ContextVar，未设置回落默认包）；
显式包名按 `packages/<包名>` 解析。包里没写图表就是错（`KeyError` / 空列表），不回落默认值
——回落会把客户标题带回基座，也会让「这个包到底有几张图」不可判定。

三不变量（`core/packages/` 同一套）：
    ① 模块级「包派生常量」必须为零——`_package_dir` 只作 legacy 显式注入槽
       （`_UNSET` = 未注入；`None` = 显式未配置 → `package_not_configured`；`Path` = 显式目录）；
    ② `configure()` 只许启动期 / 子进程初始化期调用，绝不许请求期切包；
    ③ `package` 不许进 artifact payload。

缓存：`template.json` 只有 `core/packages/registry.PackageLoad.template` 一份（键含包名 + 指纹，
容量 8）。此处原先的 `@lru_cache(maxsize=4) _template` 与 `core/tools/vocabulary.py` 各持一份，
M1 合并掉了——同一份文件不再读两遍、缓存两份。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.packages import registry as _packages

#: legacy 显式注入槽的「未注入」哨兵（语义见模块 docstring ①）。
_UNSET = object()
_package_dir: object = _UNSET


def configure(package_dir: Path) -> None:
    """绑定客户包目录并校验模板（幂等：加载层按指纹缓存，同目录重复调用不重读）。

    只许启动期 / 子进程初始化期调用。
    """
    from core.packages import context as _context

    directory = Path(package_dir)
    _context.bind(directory.name, directory)
    _packages.load_directory(directory).template


def _load(package: str | None = None):
    """解析目标包：legacy 槽优先（仅当显式注入过），否则走包上下文。"""
    if package is None and _package_dir is not _UNSET:
        if _package_dir is None:
            raise RuntimeError('package_not_configured')
        return _packages.load_directory(Path(_package_dir))
    return _packages.load(package)


def _get(package: str | None = None) -> dict[str, Any]:
    return _load(package).template


def charts(package: str | None = None) -> list[dict[str, Any]]:
    """图表实例定义（副本），顺序即模板声明序（客户包里 5 张图的顺序）。"""
    return [dict(item) for item in (_get(package).get('charts') or [])]


def ids(package: str | None = None) -> list[str]:
    return [item['id'] for item in charts(package)]


def chart(chart_id: str, package: str | None = None) -> dict[str, Any]:
    for item in charts(package):
        if item['id'] == chart_id:
            return item
    raise KeyError('unknown_chart_type:' + chart_id)
