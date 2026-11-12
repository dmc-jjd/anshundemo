"""薄壳：实现在 `core/event_analysis.py`（WP-S8-L3 搬迁），此处只 re-export 旧名。

`analyse_events` / `negative_ranking` / `validate_consolidation` / `Consolidation` / `BriefBatch`
的消费方（`app/workflow.py`、`app/data_review.py`、`app/storage.py` 的环内同批引用、
`tests/test_event_analysis.py`、`scripts/serve_data_review_validation.py`）全部零改动。

分类词表在基座里叫 `CLUSTER_RULES`（`app/tool.py:24` 仍保留 `CLUSTER_TERMS` 别名给宿主），
`core` 侧的 7 行改名是同一对象，分类结果与规则哈希逐字节不变。
"""
from core.event_analysis import *  # noqa: F401,F403
