from .config import DATA, PACKAGE, PACKAGE_DIR, ROOT
from core import paths
from core.tools import vocabulary
from core.charts import registry as chart_registry
from core.skills import registry as skill_registry
from core.prompts import registry as prompt_registry

paths.configure_data_root(DATA)
paths.configure_package_dir(PACKAGE_DIR)
# 客户模板目录（占位符清单 + 带占位符的 docx）按客户包隔离：目录名 = 包名，即
# `templates/<PACKAGE>/`。基座侧 `core/slot_writer.py` 只认 `paths.template_dir()`，
# 不认目录名；换包只改 `REPORT_PACKAGE`。目录存在性由 `template_dir()` 在**取用时**校验
# （缺失 → `template_dir_missing:<包>`，不静默回退），import 期不访问模板目录。
paths.configure_template_dir(ROOT / 'templates' / PACKAGE)
vocabulary.configure(PACKAGE_DIR)
chart_registry.configure(PACKAGE_DIR)
skill_registry.configure(PACKAGE_DIR, ROOT / 'skills')
prompt_registry.configure(PACKAGE_DIR)
__all__ = []
