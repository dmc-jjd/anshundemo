"""图表呈现契约的薄壳：客户包注入点 + 既有公开名。实现全部在 core/charts/spec.py。"""
from .config import DATA
from core.charts import spec as _spec,registry

KINDS=registry.ids()
DEFAULTS={c['id']:c['style'] for c in registry.charts()}
TITLES={c['id']:c['title'] for c in registry.charts()}
STYLE_NAMES=_spec.STYLE_NAMES
ChartStyles=_spec.ChartStyles

def definitions(template):
    return _spec.definitions(template,DATA)

def styles_for(template,overrides=None):
    return _spec.styles_for(template,overrides,data_root=DATA)

def with_styles(template,styles):
    return _spec.with_styles(template,styles,data_root=DATA)

def source_image(template,kind,source_index=0):
    return _spec.source_image(template,kind,source_index,data_root=DATA)

__all__=['KINDS','DEFAULTS','TITLES','STYLE_NAMES','ChartStyles','definitions','styles_for','with_styles','source_image']
