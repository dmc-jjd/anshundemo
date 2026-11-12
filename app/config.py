"""薄壳：环境常量与模型端点实现在 `core/config.py`（WP-S8-L1 搬迁，逐字未改）。

`PACKAGE` / `PACKAGE_DIR` 是**宿主绑定**而非基座常量（P7「只加包、不动基座」：
换客户包只改 `REPORT_PACKAGE`，不改代码），所以它们留在这里、不随 `core/config.py` 上移。
"""
import os

from core.config import *  # noqa: F401,F403
from core import config as _core_config

# 包选择点：P7「只加包、不动基座」要求换客户包不改代码，所以这里必须是环境变量。
# 缺省仍是 anshun_monthly，现有行为零变化。
PACKAGE = os.getenv('REPORT_PACKAGE', 'anshun_monthly')
PACKAGE_DIR = _core_config.ROOT / 'packages' / PACKAGE
