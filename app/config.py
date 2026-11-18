"""薄壳：环境常量与模型端点实现在 `core/config.py`（WP-S8-L1 搬迁，逐字未改）。

`PACKAGE` / `PACKAGE_DIR` 是**宿主绑定**而非基座常量（P7「只加包、不动基座」：
换客户包只改 `REPORT_PACKAGE`，不改代码），所以它们留在这里、不随 `core/config.py` 上移。

M2 起 `DATA` 是**默认包的包数据根**（`data/packages/<默认包>`），不再是部署基根：
`DATA_BASE` 才是基根（`data/`）。旧单根布局未迁移时 `paths.resolve_data_root()` 会按默认包
回落旧根并 warning 一次——所以「代码先合入、数据后迁移」的中间态重启不会丢数据。
"""
import os

from core.config import *  # noqa: F401,F403
from core import config as _core_config
from core import paths as _paths

# 包选择点：P7「只加包、不动基座」要求换客户包不改代码，所以这里必须是环境变量。
# 与 `core.packages.context.default_package()` 同一事实源；缺省不再写死客户包名，
# 由 `REPORT_PACKAGE`（现网 `.env`）提供。
from core.packages.context import default_package

PACKAGE = default_package()
PACKAGE_DIR = _core_config.ROOT / 'packages' / PACKAGE

# 部署基根（`data/`）：迁移脚本、共享价目表以它为准。
DATA_BASE = _core_config.DATA
# 当前部署默认包的数据根：与运行期 `core.paths.data_root()` 同一段判定（含旧根回落）。
DATA = _paths.resolve_data_root(DATA_BASE, PACKAGE)
