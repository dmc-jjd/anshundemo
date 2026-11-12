"""薄壳：实现在 `core/storage.py`（WP-S8-L3 搬迁），此处只 re-export 旧名。

`Store` 的默认根不再是 `app.config.DATA` 的**类定义期副本**，而是 `core/paths.data_root()`——
宿主 `app/__init__.py` 注入的仍是同一个 `DATA`（`tests/test_s7_decoupling.py:69` 钉死这条同一性）。
显式传根（`Store(tmp_path)` / `Store(DATA)`）的口径一字未变。

`Store` 的消费方有 35+ 处（`app/main.py`、`app/export.py`、13 个测试文件、20 个脚本），
全部按旧路径 import，本壳是它们的零改动出口。
"""
from core.storage import *  # noqa: F401,F403
from core.storage import ConflictError, Store  # noqa: F401  显式点名：默认根的注入点已换家
