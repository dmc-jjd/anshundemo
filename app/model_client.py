"""薄壳：实现已在 `core/model_client.py`（WP-S8-L2 搬迁），此处只 re-export 全部旧名。

**`MODEL_URL` / `MODEL_NAME` / `MODEL_KEY` / `MODEL_THINKING` / `MODEL_REASONING_EFFORT` 在壳上
只是副本**（`import *` 拷的是字符串值）——monkeypatch 必须打 `core.model_client`：打在壳上只
改副本，core 侧仍读自己的模块全局，静默失效（S8 §4.3；三个测试文件共 9 处已改指 core）。

`AGENT_DEFINITIONS` 在 core 侧是 `invoke_agent` 调用期的惰性导入（agent 在 import 期读提示词
注册表，裸 core 下 import 会炸），故本壳显式再导出，维持
`app.model_client.AGENT_DEFINITIONS is app.agent.AGENT_DEFINITIONS` 的同一性
（`tests/test_s5_prompt_parity.py:42` 钉死这条）。
"""
from core.model_client import *  # noqa: F401,F403
from core.agent import AGENT_DEFINITIONS  # noqa: F401  同一性出口，非配置注入
