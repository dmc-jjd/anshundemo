"""Public business tools. Each handler consumes artifacts and never dispatches another tool."""
from __future__ import annotations
from .schemas import ToolSpec
from core.tools import vocabulary
from core.tools.records import import_records,filter_records,classify_records,select_materials,read_evidence
from core.tools.locality import resolve_locality
from core.tools.metrics import calculate_metrics,build_table
from core.tools.events import (propose_keyword_event_candidates,propose_vector_event_neighbors,
                               group_events,cluster_event_themes,discover_topics)
from core.tools.documents import parse_report_document_tool,compare_report_structures
from core.tools import records,locality,events,metrics,documents,registry
from core.charts.renderers.pillow import render_chart
REQUIRED_COLUMNS=vocabulary.required_columns()
COLUMN_MAP=vocabulary.column_map()
SUMMARY_COLUMNS=vocabulary.summary_columns()
LOCALITIES=vocabulary.localities()
CLUSTER_RULES=vocabulary.cluster_terms()  # 基座名；历史名是禁令词（S8 §0.4 A 类），旧名别名留在 app 壳供调用方零改动

_DOMAIN={**records.HANDLERS,**locality.HANDLERS,**events.HANDLERS,**metrics.HANDLERS,**documents.HANDLERS}
_DOMAIN['parse_report_document']=documents.parse_report_document_tool  # 对外名 ≠ 域函数名
_DOMAIN['render_chart']=render_chart
HANDLERS={name:_DOMAIN[name] for name in registry.TOOL_ORDER if name in _DOMAIN}  # 前 16 个基座工具
READ_ONLY=set(registry.BASE_READ_ONLY)
ARGUMENTS=dict(registry.BASE_ARGUMENTS)
DESCRIPTIONS=dict(registry.BASE_DESCRIPTIONS)

def get_tool_specs(extra_modules=())->list[ToolSpec]: return registry.get_tool_specs(HANDLERS,READ_ONLY,ARGUMENTS,DESCRIPTIONS,extra_modules=extra_modules)
def get_tool_handler(name:str):
    get_tool_specs()
    return registry.get_tool_handler(name,HANDLERS)

__all__ = ['import_records','filter_records','resolve_locality','group_events',
           'propose_keyword_event_candidates','propose_vector_event_neighbors','calculate_metrics',
           'classify_records','cluster_event_themes','discover_topics','select_materials','read_evidence',
           'render_chart','build_table','parse_report_document_tool','compare_report_structures',
           'CLUSTER_RULES','HANDLERS','READ_ONLY','ARGUMENTS','DESCRIPTIONS',
           'get_tool_specs','get_tool_handler']
