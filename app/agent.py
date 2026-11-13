"""薄壳：实现已在 `core/agent.py`（WP-S8-L2 搬迁，字节逐字未改），此处只 re-export 全部旧名。

为什么 `agent` 必须随本层一起进 core：`model_client` 里的 `get_prompt` / `AGENT_DEFINITIONS`
就来自这里，而 agent 是 L0 层模块（`docs/team/任务分解-S8.md` §0.3）——L0 批次未含它，
L2 的 `model_client` 依赖它，按层序补齐，不新增任何注入函数。

`AGENT_PROMPTS` / `REPORT_PROMPT_PROFILES` 在壳上是**同一对象引用**（不是副本）：
`monkeypatch.setitem` / `pop` 这类原地 mutation 对 `core.agent.get_prompt` 同样生效。
标量常量（如 `MODEL_*`）则相反，patch 必须打在 `core` 侧，打在壳上只改副本。
"""
from core.agent import *  # noqa: F401,F403
from core.agent import provenance  # noqa: F401  # 键 → 'package' | 'base'（分层解析来源）
