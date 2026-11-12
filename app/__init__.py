from .config import DATA, PACKAGE_DIR, ROOT
from core import paths
from core.tools import vocabulary
from core.charts import registry as chart_registry
from core.skills import registry as skill_registry
from core.prompts import registry as prompt_registry

paths.configure_data_root(DATA)
paths.configure_package_dir(PACKAGE_DIR)
vocabulary.configure(PACKAGE_DIR)
chart_registry.configure(PACKAGE_DIR)
skill_registry.configure(PACKAGE_DIR, ROOT / 'skills')
prompt_registry.configure(PACKAGE_DIR)
__all__ = []
