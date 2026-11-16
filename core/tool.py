"""Public business tools. Each handler consumes artifacts and never dispatches another tool.

三不变量（`core/packages/` 同一套）：
    ① 模块级「包派生常量」必须为零——本模块旧的 5 个快照
       （必需列 / 列映射 / 摘要列 / 区县表 / 类目词表）已改为 PEP 562 惰性代理，
       每次读到才向当前包（或显式 `package=` 的包）解析；
    ② `configure*()` 只许启动期 / 子进程初始化期调用，绝不许请求期切包；
    ③ `package` 不许进 artifact payload。

为什么必须去快照：`REQUIRED_COLUMNS = vocabulary.required_columns()` 在**首次 import 期**
求值。多包并存时，B 包任务拿到的是 A 的列名/区县/类目——不报错，产物静默错；
`core/event_analysis.py` 的 `rules_hash` 也会算成 A 的分类规则哈希，checkpoint 复用判定跟着错。

`HANDLERS` / `READ_ONLY` / `ARGUMENTS` / `DESCRIPTIONS` 是**基座常量**（工具表与能力表），
不是包数据，保持模块级；`get_tool_specs()` 的「调用期就地扩表」副作用是现状契约，未改。
"""
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

_DOMAIN={**records.HANDLERS,**locality.HANDLERS,**events.HANDLERS,**metrics.HANDLERS,**documents.HANDLERS}
_DOMAIN['parse_report_document']=documents.parse_report_document_tool  # 对外名 ≠ 域函数名
_DOMAIN['render_chart']=render_chart
HANDLERS={name:_DOMAIN[name] for name in registry.TOOL_ORDER if name in _DOMAIN}  # 前 16 个基座工具
READ_ONLY=set(registry.BASE_READ_ONLY)
ARGUMENTS=dict(registry.BASE_ARGUMENTS)
DESCRIPTIONS=dict(registry.BASE_DESCRIPTIONS)

#: 旧公开名 → 包数据函数（PEP 562 惰性代理）。键序 = 旧模块里的声明序。
_LAZY={
    'REQUIRED_COLUMNS': lambda package=None: vocabulary.required_columns(package),
    'COLUMN_MAP': lambda package=None: vocabulary.column_map(package),
    'SUMMARY_COLUMNS': lambda package=None: vocabulary.summary_columns(package),
    'LOCALITIES': lambda package=None: vocabulary.localities(package),
    # 基座名；历史名（禁令词）的别名留在 app 壳，供旧调用方零改动
    'CLUSTER_RULES': lambda package=None: vocabulary.cluster_terms(package),
}


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


def __getattr__(name: str):
    """旧名惰性代理：第一次读到才解析当前包，随后缓存到模块字典（同一对象，不是副本）。"""
    factory = _LAZY.get(name)
    if factory is None:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    value = factory()
    globals()[name] = value
    return value
