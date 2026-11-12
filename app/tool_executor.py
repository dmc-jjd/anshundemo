"""薄壳：实现在 `core/tool_executor.py`（WP-S8-L3 搬迁），此处只 re-export 旧名。

`RunContext` / `execute_tool` 的**实现**在基座；8 个宿主模块
（`workflow` `structured_writer` `historical_research` `historical_reader` `reviewers`
`slot_writer` `event_analysis` `source_binding` 的旧名 import）与 13 个测试/脚本零改动。

私有名 `_configure_package` 显式再导出：`tests/test_s8_subprocess_configure.py` 按旧路径取它，
是「spawn 子进程自己配置四个注册表」的硬前置用例。其余私有函数
（`_bounded_run` / `_run_in_process` / `_default_policy` / `_ref_key` / `_reject` / `_POLICY`）
无外部消费方，不导出。

`PACKAGE_DIR` 不再是本模块的名字——包目录改由 `core/paths.package_dir()` 注入
（宿主 `__init__` 配置），故 `_default_policy()` 与子进程参数都在函数内取。
"""
from core.tool_executor import *  # noqa: F401,F403
from core.tool_executor import RunContext, _configure_package, execute_tool  # noqa: F401
