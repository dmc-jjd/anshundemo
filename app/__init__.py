from .config import DATA_BASE, PACKAGE, PACKAGE_DIR, ROOT
from core import paths
from core.packages import registry as package_registry
from core.tools import vocabulary
from core.charts import registry as chart_registry
from core.skills import registry as skill_registry
from core.prompts import registry as prompt_registry

# 部署级数据**基根**（`data/`）。包数据根由包名派生（`data/packages/<包>/`）；
# 旧单根布局未迁移时 `core.paths.data_root()` 会按默认包回落旧根并 warning 一次。
paths.configure_data_root(DATA_BASE)
paths.configure_package_dir(PACKAGE_DIR)
# 客户模板目录（占位符清单 + 带占位符的 docx）按客户包隔离：目录名 = 包名，即
# `templates/<PACKAGE>/`。基座侧 `core/slot_writer.py` 只认 `paths.template_dir()`，
# 不认目录名；换包只改 `REPORT_PACKAGE`。目录存在性由 `template_dir()` 在**取用时**校验
# （缺失 → `template_dir_missing:<包>`，不静默回退），import 期不访问模板目录。
paths.configure_template_dir(ROOT / 'templates' / PACKAGE)
# 启动期只 scandir（不解析任何包内文件）。100 包实测 ~1 ms；全量 configure 是秒级，
# 只允许在首次使用时按需加载（见 `GET /api/packages` / `core.packages.registry.catalog`）。
package_registry.bootstrap()
# 分词器：M3 起不再有「默认包进 FREQ」这一步——词表按包走最长匹配覆盖层，首次用到时才读
# 该包的 template.json/dict.txt（见 core/text.py 模块 docstring）。这里只绑定包上下文。
vocabulary.configure(PACKAGE_DIR)
chart_registry.configure(PACKAGE_DIR)
skill_registry.configure(PACKAGE_DIR, ROOT / 'skills')
prompt_registry.configure(PACKAGE_DIR)
__all__ = []
