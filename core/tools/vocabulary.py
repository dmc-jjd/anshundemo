"""客户包数据面：必需列、列名映射、摘要列、区县词典、事件词典、去重阈值的唯一读取口。

数据源是 `<package_dir>/template.json`。**M1 起解析不再依赖 configure()**：每个 getter 都带
`package=None`，`None` 时解析当前上下文（`core.packages.context` 的 ContextVar，未设置回落
默认包）；显式包名直接按 `packages/<包名>` 解析。未配置就调用**不再**回落默认值——包里没写
就是错（回退会让包数据形同虚设）。

三不变量（`core/packages/` 同一套）：
    ① 模块级「包派生常量」必须为零——`_package_dir` 只作 legacy 显式注入槽
       （`_UNSET` = 未注入；`None` = 显式未配置 → `package_not_configured`；`Path` = 显式目录）；
    ② `configure()` 只许启动期 / 子进程初始化期调用，绝不许请求期切包；
    ③ `package` 不许进 artifact payload。

`template.json` 的缓存**只有一份**（`core/packages/registry.PackageLoad.template`，键含包名 +
指纹、容量 8）。此处原先与 `core/charts/registry.py` 各持一份 `@lru_cache(maxsize=4) _template`，
同一份文件被读两遍、缓存两份；M1 合并掉了。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.packages import registry as _packages

#: legacy 显式注入槽的「未注入」哨兵（语义见模块 docstring ①）。
_UNSET = object()
_package_dir: object = _UNSET


def configure(package_dir: Path) -> None:
    """绑定客户包目录并校验它的模板（幂等：同目录重复调用不重读文件——加载层按指纹缓存）。

    只许启动期 / 子进程初始化期调用；**不要**在循环里对 N 个包调用（100 包 ≈ 7.69 s）。
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


def _contract(package: str | None = None) -> dict[str, Any]:
    return _get(package).get('data_contract') or {}


def _vocabulary(package: str | None = None) -> dict[str, Any]:
    return _get(package).get('vocabulary') or {}


def _contract_of(package: str | None = None) -> dict[str, Any]:
    """按包取合同：`package is None` 时以**零参**调用 `_contract`。

    为什么绕这一下：既有测试用零参替身打桩 `vocabulary._contract`（`monkeypatch.setattr`），
    内部无条件传参会破坏那个契约；而显式包名必须真的传下去。两者只能靠这一行同时满足。
    """
    return _contract() if package is None else _contract(package)


def _vocabulary_of(package: str | None = None) -> dict[str, Any]:
    """同上（零参打桩面）。"""
    return _vocabulary() if package is None else _vocabulary(package)


def required_columns(package: str | None = None) -> list[str]:
    return list(_contract_of(package)['required_columns'])


def column_map(package: str | None = None) -> dict[str, str]:
    """返回副本，保持模板里的键序（records 工件字段序由它决定）。"""
    return dict(_contract_of(package)['column_map'])


def summary_columns(package: str | None = None) -> list[str]:
    return list(_contract_of(package)['summary_columns'])


def sheet_index(package: str | None = None) -> int:
    """明细工作表序号：只读包合同 `data_contract.sheet_index`，缺键即失败，不默认 3。"""
    contract = _contract_of(package)
    if 'sheet_index' not in contract:
        raise ValueError('sheet_index_not_configured')
    return int(contract['sheet_index'])


def sentiment_values(package: str | None = None) -> list[str]:
    """包合同声明的调性枚举；未声明则空，不回落安顺三种调性。"""
    cfg = (_contract_of(package).get('sentiment') or {})
    return list(cfg.get('values') or ())


def filter_contract(package: str | None = None) -> dict:
    """筛选口径：只读 `data_contract.sentiment` / `warning`，不做基座回落。"""
    contract = _contract_of(package)
    return {
        'sentiment': dict(contract.get('sentiment') or {}),
        'warning': dict(contract.get('warning') or {}),
    }


def localities(package: str | None = None) -> dict[str, list[str]]:
    return dict(_vocabulary_of(package)['localities'])


def cluster_terms(package: str | None = None) -> dict[str, list[str]]:
    """事件主题词典，键序即模型枚举序，调用方用 `list()` 取类别时依赖它。"""
    return dict(_vocabulary_of(package)['cluster_terms'])


def dedup_threshold(package: str | None = None) -> float:
    return float(_contract_of(package)['dedup']['threshold'])


def dedup_candidate_floor(package: str | None = None) -> float:
    """候选下限比例（0-1），不是绝对条数。"""
    return float(_contract_of(package)['dedup']['candidate_floor_ratio'])


def dedup_merge_rounds(package: str | None = None) -> int:
    """去重轮次开关。缺省 1（只跑第一轮，行为与第二轮落地前逐字节一致），2=组级聚合归并。"""
    return int((_contract_of(package).get('dedup') or {}).get('merge_rounds', 1))


def dedup_merge_threshold(package: str | None = None) -> float:
    """第二轮组级余弦阈值。缺省 0.5；客户包可单独标定，与第一轮 threshold 互不影响。"""
    return float((_contract_of(package).get('dedup') or {}).get('merge_threshold', 0.5))


#: 兜底推导用的四类文本槽位（见 `writer_slots` docstring 第 2 条）。
_DERIVED_WRITER_SLOT_TYPES = frozenset({
    'theme_cluster', 'source_text', 'narrative_from_sources', 'computed_judgement',
})


def writer_slots(package: str | None = None) -> tuple[str, ...]:
    """模板声明的可写槽位（writer 负责填写的占位符 id），**客户业务口径**。

    来源优先级：
    1. 包内 `template.json` 顶层 `writer_slots`（字符串数组，元素是占位符 id）。
       新客户**应显式声明**：这组 id 是业务口径的产物，推导不出来——当前客户模板
       99 个占位符里 `kind='highlight'` 有 66 个，而这 9 个只是其中被业务选中的子集。
    2. 缺省（旧包没写 `writer_slots`）才回退：读该包的模板目录里
       `report.template.json`，取 `slot_type` ∈ {theme_cluster, source_text,
       narrative_from_sources, computed_judgement} 的占位符（当前模板 15 个）。
       这是**兼容旧包的近似兜底，不是权威口径**：它比业务口径宽 6 个槽位，
       会让 writer 多写；新客户请走第 1 条显式声明。

    只许函数内调用：模块级求值会在包解析之前炸（与 `paths` 各取值函数同一条纪律）。
    """
    template = _get(package)
    if 'writer_slots' in template:
        return tuple(str(slot_id) for slot_id in (template['writer_slots'] or ()))
    return _derived_writer_slots(package)


def _derived_writer_slots(package: str | None = None) -> tuple[str, ...]:
    """兜底推导（仅旧包无 `writer_slots` 时走）：占位符清单不在包内，在该包的模板目录。"""
    from core import paths
    from core.layout import manifest_path

    try:
        path = manifest_path(package)
    except RuntimeError as exc:
        if str(exc).startswith('template_dir_missing'):
            return ()
        raise
    if not path.is_file():
        return ()
    manifest = json.loads(path.read_text(encoding='utf-8'))
    return tuple(
        str(placeholder['id'])
        for placeholder in (manifest.get('placeholders') or ())
        if placeholder.get('slot_type') in _DERIVED_WRITER_SLOT_TYPES
    )
