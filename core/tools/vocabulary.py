"""客户包数据面：必需列、列名映射、摘要列、区县词典、事件词典、去重阈值的唯一读取口。

数据源是 `<package_dir>/template.json`，由 `app/__init__.py` 在首次 `import app.*`
时 `configure` 一次；未配置就调用一律 `RuntimeError('package_not_configured')`，
不静默回落默认值——回落会让包数据形同虚设。
"""

from __future__ import annotations

import json
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


def dedup_merge_rounds() -> int:
    """去重轮次开关。缺省 1（只跑第一轮，行为与第二轮落地前逐字节一致），2=组级聚合归并。"""
    return int((_contract().get('dedup') or {}).get('merge_rounds', 1))


def dedup_merge_threshold() -> float:
    """第二轮组级余弦阈值。缺省 0.5；客户包可单独标定，与第一轮 threshold 互不影响。"""
    return float((_contract().get('dedup') or {}).get('merge_threshold', 0.5))


#: 兜底推导用的四类文本槽位（见 `writer_slots` docstring 第 2 条）。
_DERIVED_WRITER_SLOT_TYPES = frozenset({
    'theme_cluster', 'source_text', 'narrative_from_sources', 'computed_judgement',
})


def writer_slots() -> tuple[str, ...]:
    """模板声明的可写槽位（writer 负责填写的占位符 id），**客户业务口径**。

    来源优先级：
    1. 包内 `template.json` 顶层 `writer_slots`（字符串数组，元素是占位符 id）。
       新客户**应显式声明**：这组 id 是业务口径的产物，推导不出来——当前客户模板
       99 个占位符里 `kind='highlight'` 有 66 个，而这 9 个只是其中被业务选中的子集。
    2. 缺省（旧包没写 `writer_slots`）才回退：读注入的模板目录里
       `report.template.json`，取 `slot_type` ∈ {theme_cluster, source_text,
       narrative_from_sources, computed_judgement} 的占位符（当前模板 15 个）。
       这是**兼容旧包的近似兜底，不是权威口径**：它比业务口径宽 6 个槽位，
       会让 writer 多写；新客户请走第 1 条显式声明。

    只许函数内调用：模块级求值会在 configure 之前炸（与 `paths` 各取值函数同一条纪律）。
    """
    template = _get()
    if 'writer_slots' in template:
        return tuple(str(slot_id) for slot_id in (template['writer_slots'] or ()))
    return _derived_writer_slots()


def _derived_writer_slots() -> tuple[str, ...]:
    """兜底推导（仅旧包无 `writer_slots` 时走）：占位符清单不在包内，在注入的模板目录。"""
    from core import paths

    manifest = json.loads((paths.template_dir() / 'report.template.json').read_text(encoding='utf-8'))
    return tuple(
        str(placeholder['id'])
        for placeholder in (manifest.get('placeholders') or ())
        if placeholder.get('slot_type') in _DERIVED_WRITER_SLOT_TYPES
    )
