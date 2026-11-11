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
# 包选择点：P7「只加包、不动基座」要求换客户包不改代码，所以这里必须是环境变量。
# 缺省仍是 anshun_monthly，现有行为零变化。
PACKAGE = os.getenv('REPORT_PACKAGE', 'anshun_monthly')
PACKAGE_DIR = ROOT / 'packages' / PACKAGE

