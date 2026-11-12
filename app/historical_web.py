"""薄壳：实现在 `core/historical_web.py`（WP-S8-L1 搬迁，字节逐字未改），此处只 re-export 全部旧名字。

`MODEL_URL` / `MODEL_KEY` / `request` 也在壳上（壳的副本）——monkeypatch 必须打
**`core.historical_web`**：打在壳上只改副本，`core` 侧仍读自己的模块全局（静默失效，S8 §4.3）。
"""
from core.historical_web import *  # noqa: F401,F403
