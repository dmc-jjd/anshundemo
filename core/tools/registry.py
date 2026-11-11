"""工具注册表的基座部分：工具顺序、基座工具词汇与聚合函数。

自 `app/tool.py` 原样搬出（WP-S2-F），语义未改：`get_tool_specs()` 仍会把写作阶段
与网络检索工具**就地**并进调用方传入的三张表——这个副作用是现状契约
（`app/workflow.py:199` 与 `tests/test_core.py` 依赖它），不是遗漏。
S3 之后再按 `core.ports.ToolRegistry` 改成只读注册表。
"""

from __future__ import annotations

from app.schemas import ToolSpec

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


def get_tool_specs(handlers, readonly, arguments, descriptions) -> list[ToolSpec]:
    """把写作阶段与网络检索工具就地并入传入的表，再按表序产出 specs。

    调用期才 import：与现状一致（不在 import 期把 writer/web 拉进依赖图，防环），
    且只有真正取 specs 时才付这次 import 的成本。
    """
    from app.writer_tools import HANDLERS as writers, SCHEMAS, DESCRIPTIONS as descriptions_writer
    handlers.update(writers); readonly.update(writers); arguments.update(SCHEMAS); descriptions.update(descriptions_writer)
    from app.historical_web import HANDLERS as web, SCHEMAS as web_schemas, DESCRIPTIONS as descriptions_web
    handlers.update(web); readonly.update(web); arguments.update(web_schemas); descriptions.update(descriptions_web)
    requirements = {'propose_vector_event_neighbors': ['keyword_event_candidates'], 'propose_keyword_event_candidates': ['normalized_records'], 'cluster_event_themes': ['normalized_records']}
    products = {'import_records': ['normalized_records'], 'propose_keyword_event_candidates': ['keyword_event_candidates'], 'propose_vector_event_neighbors': ['vector_event_neighbors'], 'cluster_event_themes': ['theme_cluster_candidates']}
    return [ToolSpec(name=n, version='2' if n == 'group_events' else '1', description=descriptions.get(n, n.replace('_', ' ')), required_capabilities=requirements.get(n, []), produced_capabilities=products.get(n, []), mutates_facts=n not in readonly, arguments_schema=arguments.get(n, {})) for n in handlers]


def get_tool_handler(name: str, catalog):
    """按名取 handler。调用方负责先 `get_tool_specs(...)`（现状语义：查到的一定是已扩表的表）。"""
    return catalog[name]
