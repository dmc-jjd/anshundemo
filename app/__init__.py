from .config import PACKAGE_DIR
from core.tools import vocabulary
from core.charts import registry as chart_registry

vocabulary.configure(PACKAGE_DIR)
chart_registry.configure(PACKAGE_DIR)
__all__ = []
