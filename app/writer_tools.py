"""薄壳：实现在 `core/writer_tools.py`（WP-S8-L1 搬迁，字节逐字未改），此处只 re-export 全部旧名字。

`get_tool_specs(extra_modules=...)` 仍由 `app/tool.py` 把**本壳**传进去就地合表（组合根在宿主），
10 个旧对外名全部覆盖：`ChartRequest/chart_payload/plot_frozen_chart/CHARTS/HANDLERS/SCHEMAS/
DESCRIPTIONS/native_tools/frozen_statistics/query_frozen_materials`。
`configure_report_factory(FrozenReport)` 的副作用随实现一起搬进 core（`import` 本壳即完成注册）。
"""
from core.writer_tools import *  # noqa: F401,F403
