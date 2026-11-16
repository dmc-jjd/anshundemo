"""图表呈现契约的薄壳：客户包注入点 + 既有公开名。实现全部在 core/charts/spec.py。

M2：数据根不再在 import 期固化（`from .config import DATA` 是部署单根时代的写法）。
模块级 `DATA` 保留为**显式覆盖位**（测试 `monkeypatch.setattr(core.chart_spec, 'DATA', …)`
一直这么用），缺省 `None` = **调用期**按当前包解析 `paths.data_root()`——否则多包同进程时
`uploads/` 会永远读默认包（`layout_source` 回退找不到当前包上传的版式）。
"""
from pathlib import Path

from . import paths
from core.charts import spec as _spec,registry

#: `None` = 按当前包解析（M2 默认）；显式 Path = 覆盖（测试/单包脚本的旧用法）。
DATA: Path | None = None

KINDS=registry.ids()
DEFAULTS={c['id']:c['style'] for c in registry.charts()}
TITLES={c['id']:c['title'] for c in registry.charts()}
STYLE_NAMES=_spec.STYLE_NAMES
ChartStyles=_spec.ChartStyles

def _root() -> Path:
    return DATA if DATA is not None else paths.data_root()

def definitions(template):
    return _spec.definitions(template,_root())

def layout_available(template):
    return _spec.layout_available(template,_root())

def styles_for(template,overrides=None):
    return _spec.styles_for(template,overrides,data_root=_root())

def with_styles(template,styles):
    return _spec.with_styles(template,styles,data_root=_root())

def source_image(template,kind,source_index=0):
    return _spec.source_image(template,kind,source_index,data_root=_root())

__all__=['KINDS','DEFAULTS','TITLES','STYLE_NAMES','ChartStyles','definitions','layout_available','styles_for','with_styles','source_image']
