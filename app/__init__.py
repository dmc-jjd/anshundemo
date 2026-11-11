from .config import PACKAGE_DIR, ROOT
from core.tools import vocabulary
from core.charts import registry as chart_registry
from core.skills import registry as skill_registry

vocabulary.configure(PACKAGE_DIR)
chart_registry.configure(PACKAGE_DIR)
skill_registry.configure(PACKAGE_DIR, ROOT / 'skills')
__all__ = []
