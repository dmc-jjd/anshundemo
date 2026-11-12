"""工具注册表的基座部分：工具顺序、基座工具词汇与聚合函数。

自 `app/tool.py` 原样搬出（WP-S2-F），语义未改：`get_tool_specs()` 仍会把写作阶段
与网络检索工具**就地**并进调用方传入的三张表——这个副作用是现状契约
（`app/workflow.py:199` 与 `tests/test_core.py` 依赖它），不是遗漏。
S3 之后再按 `core.ports.ToolRegistry` 改成只读注册表。
"""

from __future__ import annotations

from core.tools.contracts import ToolSpec

#: 表序决定 `G-SPECS` 指纹，也决定 `workflow.py:200` 给模型的工具清单顺序，不得改动。
TOOL_ORDER = ('import_records', 'filter_records', 'resolve_locality', 'group_events',
              'propose_keyword_event_candidates', 'propose_vector_event_neighbors',
              'calculate_metrics', 'classify_records', 'cluster_event_themes', 'discover_topics',
              'select_materials', 'read_evidence', 'render_chart', 'build_table',
              'compare_report_structures', 'parse_report_document',
              'frozen_statistics', 'query_frozen_materials', 'plot_frozen_chart',
              'search_historical_web', 'fetch_historical_page')

BASE_DESCRIPTIONS = {'propose_keyword_event_candidates': '第一轮关键词匹配形成同事件候选组', 'propose_vector_event_neighbors': '第二轮向量化近邻消费第一轮候选，补充跨组和隔天跟进候选'}
BASE_READ_ONLY = {'read_evidence', 'parse_report_document', 'compare_report_structures', 'render_chart', 'build_table'}
BASE_ARGUMENTS = {
    'group_events': {'required': ['records_ref'], 'properties': {'records_ref': 'artifact_ref', 'threshold': 'number (0,1]'}},
    'import_records': {'required': ['path'], 'properties': {'path': 'string', 'sheet_index': 'integer'}},
    'filter_records': {'required': ['records_ref', 'scope'], 'properties': {'records_ref': 'artifact_ref', 'scope': 'all|positive|neutral|negative|warning|negative_warning|negative_or_warning|media', 'media_level': 'string'}},
    'propose_keyword_event_candidates': {'required': ['records_ref'], 'properties': {'records_ref': 'artifact_ref', 'keyword_jaccard': 'number'}},
    'propose_vector_event_neighbors': {'required': ['keyword_candidates_ref'], 'properties': {'keyword_candidates_ref': 'artifact_ref', 'min_score': 'number', 'max_neighbors': 'integer'}},
    'cluster_event_themes': {'required': ['records_ref'], 'properties': {'records_ref': 'artifact_ref'}},
    'render_chart': {'required': ['metrics_ref', 'chart_type'], 'properties': {'metrics_ref': 'artifact_ref', 'chart_type': 'sentiment|daily|platform|theme|locality'}},
}


def get_tool_specs(handlers, readonly, arguments, descriptions, *, extra_modules=()) -> list[ToolSpec]:
    """把注入的工具模块就地并入传入的表，再按表序产出 specs。

    模块由组合根（`app/tool.py`）经 `extra_modules` 传入——core 不 import app。
    扩表顺序的唯一决定处是这里的循环序（先 writer 后 web）：`G-SPECS` 的 21 项与指纹即判据。
    """
    for module in extra_modules:
        handlers.update(module.HANDLERS); readonly.update(module.HANDLERS)
        arguments.update(module.SCHEMAS); descriptions.update(module.DESCRIPTIONS)
    requirements = {'propose_vector_event_neighbors': ['keyword_event_candidates'], 'propose_keyword_event_candidates': ['normalized_records'], 'cluster_event_themes': ['normalized_records']}
    products = {'import_records': ['normalized_records'], 'propose_keyword_event_candidates': ['keyword_event_candidates'], 'propose_vector_event_neighbors': ['vector_event_neighbors'], 'cluster_event_themes': ['theme_cluster_candidates']}
    return [ToolSpec(name=n, version='2' if n == 'group_events' else '1', description=descriptions.get(n, n.replace('_', ' ')), required_capabilities=requirements.get(n, []), produced_capabilities=products.get(n, []), mutates_facts=n not in readonly, arguments_schema=arguments.get(n, {})) for n in handlers]


def get_tool_handler(name: str, catalog):
    """按名取 handler。调用方负责先 `get_tool_specs(...)`（现状语义：查到的一定是已扩表的表）。"""
    return catalog[name]


# --------------------------------------------------------------------------- #
# 能力依赖剪枝（方案 B）：按「客户需要哪些产物」反推可达工具集
# --------------------------------------------------------------------------- #

#: 工具 → 它需要的上游能力（缺了就跑不了）
TOOL_REQUIRES: dict[str, tuple[str, ...]] = {
    'propose_vector_event_neighbors': ('keyword_event_candidates',),
    'propose_keyword_event_candidates': ('normalized_records',),
    'cluster_event_themes': ('normalized_records',),
}

#: 工具 → 它产出的能力
TOOL_PRODUCES: dict[str, tuple[str, ...]] = {
    'import_records': ('normalized_records',),
    'propose_keyword_event_candidates': ('keyword_event_candidates',),
    'propose_vector_event_neighbors': ('vector_event_neighbors',),
    'cluster_event_themes': ('theme_cluster_candidates',),
}

#: 需要被「人工研判」才成立的产物 → 引入哪些工具
#: 这是「不是每份报告都要研判」的落点：不声明该产物时，相关工具不进白名单。
#:
#: 覆盖度硬约束：`CAPABILITY_TOOLS` 的并集必须**至少**等于任何一个客户包 `tools.allow`
#: 的全集，否则剪枝会静默丢工具（`test_capability_tools_cover_default_allow` 守着这条）。
CAPABILITY_TOOLS: dict[str, tuple[str, ...]] = {
    'records': ('import_records', 'filter_records'),
    'metrics': ('calculate_metrics', 'build_table'),
    'locality': ('resolve_locality',),
    'charts': ('render_chart',),
    'events': ('propose_keyword_event_candidates', 'propose_vector_event_neighbors',
               'group_events', 'cluster_event_themes', 'discover_topics',
               'classify_records', 'select_materials', 'read_evidence'),
    'documents': ('parse_report_document', 'compare_report_structures'),
}


#: 能力开关 → 它控制哪些工具。`features.<key>.enabled: false` 时整组退出白名单。
#:
#: 为什么需要这张表（verifier 抓出的假开关）：
#: 早先 `manifest.features.locality/dedup` 只被解析、无任何消费者，等于谎称可关。
#: `capabilities.require` 回答「要哪些产物」，这张表回答「某个能力开不开」——
#: 前者管有无，后者管开关，两者缺一都会让客户以为改了配置就生效。
FEATURE_TOOLS: dict[str, tuple[str, ...]] = {
    'locality': ('resolve_locality',),
    'dedup': ('group_events', 'propose_keyword_event_candidates', 'propose_vector_event_neighbors'),
    'event_classification': ('classify_records', 'cluster_event_themes', 'discover_topics'),
}


def resolve_tools(
    required: list[str] | tuple[str, ...],
    features: Mapping[str, Mapping[str, Any]] | None = None,
) -> frozenset[str]:
    """按客户声明的产物反推可达工具集（含传递依赖），并扣除被 features 关掉的能力。

    语义：`required` 里每一项都会被展开成它对应的工具；若某个工具要求上游能力，
    而该能力的生产者没被选中，就把生产者一并补齐。结果可直接喂给 `ToolPolicy.allow`。

    白名单同时是**门禁**——没选中的工具模型根本调不动（`tool_not_allowed`），
    于是「去重/分类/研判要不要跑」由客户包声明决定，而不是由一段 if 决定。

    `features` 为 None 或未声明某项能力时**不干预**（保持向后兼容）；
    显式 `enabled: false` 才扣工具。

    未声明的产物不会带出任何工具；`required` 为空时返回空集（不是全集）。
    """
    selected: set[str] = set()
    for capability in required:
        selected.update(CAPABILITY_TOOLS.get(capability, ()))

    # 沿 requires → produces 反推，直到不动点（当前图很浅，循环也只是几轮）
    changed = True
    while changed:
        changed = False
        for tool in tuple(selected):
            for need in TOOL_REQUIRES.get(tool, ()):
                for producer, produced in TOOL_PRODUCES.items():
                    if need in produced and producer not in selected:
                        selected.add(producer)
                        changed = True

    for feature, tools in FEATURE_TOOLS.items():
        config = (features or {}).get(feature)
        if config is None:
            continue                      # 未声明 = 不干预
        if config.get("enabled") is False:
            selected -= set(tools)

    return frozenset(selected)
