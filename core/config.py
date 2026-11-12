"""宿主环境常量：仓库根、数据根、模型端点、预算（WP-S8-L1，自 `app/config.py:1-36` 逐字搬迁，未改一行）。

为什么这层能进基座：`usage` / `historical_web` / `model_client` 它们只读这里的常量，
而常量是 env 的唯一读取点；不搬则这三个模块每个都要新增注入函数（Ponytail：搬迁类禁止新增公开函数）。

**包选择点不进基座**：`PACKAGE` / `PACKAGE_DIR` 留在宿主 `app/config.py`——P7「只加包、不动基座」
要求换客户包只改 `REPORT_PACKAGE`，且基座里不该出现 `packages/<客户包>` 这层知识。
因此本文件不含任何客户包名。

与 `core/paths.py` 的分工：这里是**import 期求值的常量**；需要「可注入」的数据根仍走
`core/paths.data_root()`（`chart_spec` 等 4 个消费方用它，本文件不参与）。
"""

from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]

def _load_local_env() -> None:
    """Load project settings without echoing credentials or overriding the process."""
    path = ROOT / '.env'
    if not path.is_file():
        return
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        name, value = line.split('=', 1)
        name = name.strip()
        if name not in {'REPORT_MODEL_URL', 'REPORT_MODEL_NAME', 'REPORT_MODEL_KEY',
                        'REPORT_MODEL_THINKING', 'REPORT_MODEL_REASONING_EFFORT',
                        'REPORT_DEMO_DATA', 'REPORT_MAX_TOOL_CALLS',
                        'REPORT_MAX_PLANNING_CALLS'}:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(name, value)

_load_local_env()
DATA = Path(os.getenv('REPORT_DEMO_DATA', ROOT / 'data'))
DATA.mkdir(parents=True, exist_ok=True)
MODEL_URL = os.getenv('REPORT_MODEL_URL', '')
MODEL_NAME = os.getenv('REPORT_MODEL_NAME', '')
MODEL_KEY = os.getenv('REPORT_MODEL_KEY', '')
MODEL_THINKING = os.getenv('REPORT_MODEL_THINKING', 'enabled')
MODEL_REASONING_EFFORT = os.getenv('REPORT_MODEL_REASONING_EFFORT', 'low')
MAX_TOOL_CALLS = int(os.getenv('REPORT_MAX_TOOL_CALLS', '40'))
MAX_PLANNING_CALLS = int(os.getenv('REPORT_MAX_PLANNING_CALLS', '12'))
