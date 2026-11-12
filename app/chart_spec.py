"""薄壳：实现已在 `core/chart_spec.py`（WP-S8-L2 搬迁，字节逐字未改），此处只 re-export 全部旧名。

为什么 `chart_spec` 随本层进 core：`structured_template:83` 的 `from .chart_spec import definitions`
是**函数内惰性**导入，搬进 core 后逐字解析到 `core/chart_spec.py`——0 行改动的前提是它同在
core（`docs/team/任务分解-S8.md` §0.3 把它排在 L1）。

`DATA` 的注入点随 `config` 一并进 core（`core/config.py:DATA`），与本壳旧值同一对象来源。
"""
from core.chart_spec import *  # noqa: F401,F403
