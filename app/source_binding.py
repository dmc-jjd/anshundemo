"""薄壳：实现在 `core/source_binding.py`（WP-S8-L4 搬迁，逻辑逐字未改）。

`from app.source_binding import SourceCatalog, NumberedAnswers, NumberedRevision,
NumberedSlot, invoke_numbered_writer` 等既有公开面全部零变化——本壳与 core 里是**同一对象**
（不是副本），故 `tests/test_source_binding.py` 与 `app/structured_writer.py:15` 的
`monkeypatch.setattr(writer,'invoke_numbered_writer',...)` 都不需要改指向。
"""
from core.source_binding import *  # noqa: F401,F403
