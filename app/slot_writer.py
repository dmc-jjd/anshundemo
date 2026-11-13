"""薄壳：实现在 `core/slot_writer.py`（WP-S8-L4 搬迁，逻辑逐字未改）。

旧公开面全部经本壳保持（同一对象引用，不是副本）：
    `write_first_section_slots`  —— `app/workflow.py:440`
    `writer_slot_ids`            —— `app/reviewers.py:22`（原常量 `WRITER_SLOT_IDS`
                                    已搬回客户包 `template.json`，基座只留函数）
    `SlotAnswer`                 —— `scripts/inspect_writer_request.py:8`
    `_issue` 不导出：全仓 0 消费，且下划线名本来就不进星号导出面。

客户模板目录不再写死在实现里：`app/__init__.py` 通过 `core.paths.configure_template_dir(...)`
注入一次（换包即换模板，见 `docs/team/任务分解-S8.md` §6 D7(a)）。
"""
from core.slot_writer import *  # noqa: F401,F403
