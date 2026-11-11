"""图表实例注册表：从客户包 `template.json` 的 `charts` 段读图表实例定义。

与 `core/tools/vocabulary.py` 同构：`app/__init__.py` 在首次 `import app.*` 时 `configure` 一次；
未配置就调用一律 `RuntimeError('package_not_configured')`，不静默回落默认值
——回落会让客户图表数据形同虚设，也会把客户标题带回基座。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from core.manifest import load_template

_package_dir: Path | None = None


def configure(package_dir: Path) -> None:
    """绑定客户包目录并预热模板缓存。幂等：同目录重复调用不重读文件。"""
    global _package_dir
    _package_dir = Path(package_dir)
    _template(_package_dir)


@lru_cache(maxsize=4)
def _template(package_dir: Path) -> dict[str, Any]:
    return load_template(package_dir)


def _get() -> dict[str, Any]:
    if _package_dir is None:
        raise RuntimeError('package_not_configured')
    return _template(_package_dir)


def charts() -> list[dict[str, Any]]:
    """图表实例定义（副本），顺序即模板声明序 = 报告里 5 张图的顺序。"""
    return [dict(item) for item in (_get().get('charts') or [])]


def ids() -> list[str]:
    return [item['id'] for item in charts()]


def chart(chart_id: str) -> dict[str, Any]:
    for item in charts():
        if item['id'] == chart_id:
            return item
    raise KeyError('unknown_chart_type:' + chart_id)
