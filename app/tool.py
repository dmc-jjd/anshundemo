"""组合根：实现已在 `core/tool.py`，本壳保留两个转发 `def`（S2 铁律 7）。

`tests/test_s2_shell_registry.py:30` 钉死本壳顶层 `def` 集合恰为
`{get_tool_specs, get_tool_handler}`；`get_tool_specs()` 的「调用期就地扩表」副作用是现状契约
（`app/workflow.py:225`、`app/tool_executor.py:117` 依赖它），所以两个 `def` 不能退化成纯 re-export。

扩表用的两个模块仍由**宿主**传入（`core/tools/registry.py:38` 的契约：core 不 import app），
故 `extra_modules` 的注入点留在本壳；core 侧的 `get_tool_specs(extra_modules=())` 默认不扩表。

`REQUIRED_COLUMNS` / `COLUMN_MAP` / `SUMMARY_COLUMNS` / `LOCALITIES` 不在 `__all__` 里，
但 `tests/test_s2_manifest_vocabulary.py:8` 仍按旧公开面从本壳取，故显式再导出。
"""
from __future__ import annotations
from core import tool as _core
from core.tool import *  # noqa: F401,F403
from core.tool import __all__ as _core_all, CLUSTER_RULES
from core.tool import REQUIRED_COLUMNS, COLUMN_MAP, SUMMARY_COLUMNS, LOCALITIES  # 不在 __all__ 的旧全局
from core.tools import registry

# CLUSTER_RULES 是基座名；CLUSTER_TERMS 是历史名，留在 app 壳供调用方零改动：
# 它是 S1 冻结的禁令词（计划书 §10），core 内不得出现；app 侧只做**别名**（同一对象，不是副本），
# 故 `app/event_analysis.py:76` 的 `from .tool import CLUSTER_TERMS` 与 A 包 `__all__` 全部零改动，
# L3 把 event_analysis 搬进 core 时同样 0 行改动。
CLUSTER_TERMS=CLUSTER_RULES
__all__=[name if name!='CLUSTER_RULES' else 'CLUSTER_TERMS' for name in _core_all]

def get_tool_specs()->list[ToolSpec]: from . import historical_web,writer_tools; return _core.get_tool_specs(extra_modules=(writer_tools,historical_web))
def get_tool_handler(name:str):
    get_tool_specs()
    return registry.get_tool_handler(name,HANDLERS)
