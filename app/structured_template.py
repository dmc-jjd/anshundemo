"""薄壳：实现已在 `core/structured_template.py`（WP-S8-L2 搬迁，字节逐字未改）。

`_schema` 是被 4 个消费方用到的私有名（`app/template_draft.py:21`、`tests/test_frozen_writer.py:9`、
`tests/test_review_excerpt.py:5`、`tests/test_section_two.py:179/244`），`import *` 不会带出
下划线名，故在此显式再导出——壳里仍然 0 个 `def`。

`render_structured_docx` 内部的 `from .config import DATA` 与 `from .chart_spec import definitions`
同为函数内惰性导入，搬进 core 后逐字解析到 `core/config.py` / `core/chart_spec.py`。
"""
from core.structured_template import *  # noqa: F401,F403
from core.structured_template import _schema  # noqa: F401  旧私有名仍被 app 与测试消费
