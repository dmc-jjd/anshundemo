"""客户包数据面：必需列、列名映射、摘要列、区县词典、事件词典、去重阈值的唯一读取口。

数据源是 `<package_dir>/template.json`，由 `app/__init__.py` 在首次 `import app.*`
时 `configure` 一次；未配置就调用一律 `RuntimeError('package_not_configured')`，
不静默回落默认值——回落会让包数据形同虚设。
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


def _contract() -> dict[str, Any]:
    return _get().get('data_contract') or {}


def _vocabulary() -> dict[str, Any]:
    return _get().get('vocabulary') or {}


def required_columns() -> list[str]:
    return list(_contract()['required_columns'])


def column_map() -> dict[str, str]:
    """返回副本，保持模板里的键序（records 工件字段序由它决定）。"""
    return dict(_contract()['column_map'])


def summary_columns() -> list[str]:
    return list(_contract()['summary_columns'])


def localities() -> dict[str, list[str]]:
    return dict(_vocabulary()['localities'])


def cluster_terms() -> dict[str, list[str]]:
    """事件主题词典，键序即模型枚举序，调用方用 `list()` 取类别时依赖它。"""
    return dict(_vocabulary()['cluster_terms'])


def dedup_threshold() -> float:
    return float(_contract()['dedup']['threshold'])


def dedup_candidate_floor() -> float:
    """候选下限比例（0-1），不是绝对条数。"""
    return float(_contract()['dedup']['candidate_floor_ratio'])
