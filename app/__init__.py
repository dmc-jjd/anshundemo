from .config import DATA, PACKAGE_DIR, ROOT
from core import paths
from core.tools import vocabulary
from core.charts import registry as chart_registry
from core.skills import registry as skill_registry
from core.prompts import registry as prompt_registry

paths.configure_data_root(DATA)
paths.configure_package_dir(PACKAGE_DIR)
# 客户模板目录（占位符清单 + 带占位符的 docx）是宿主绑定：基座侧 `core/slot_writer.py`
# 只认 `paths.template_dir()`，不认目录名。换模板只改这一行。
paths.configure_template_dir(ROOT / 'templates' / 'anshun-colored')
vocabulary.configure(PACKAGE_DIR)
chart_registry.configure(PACKAGE_DIR)
skill_registry.configure(PACKAGE_DIR, ROOT / 'skills')
prompt_registry.configure(PACKAGE_DIR)
__all__ = []
