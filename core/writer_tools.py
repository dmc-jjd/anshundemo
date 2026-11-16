"""The Writer's bounded read-only tools. No imports or fact edits are exposed.

三不变量（`core/packages/` 同一套）：
    ① 模块级「包派生常量」必须为零——旧 `CHARTS = [c['id'] for c in registry.charts()]`
       在首次 import 期冻结成当时那个包的图种集合（B 包只有 3 张图、A 包 5 张），
       现改为 `charts(package=None)` + PEP 562 惰性旧名；
    ② `configure*()` 只许启动期 / 子进程初始化期调用，绝不许请求期切包；
    ③ `package` 不许进 artifact payload。
"""
from .frozen_report import FrozenReport,Calculation,MaterialQuery,query_materials
from .schemas import ToolResult
from core.charts import registry
from core.charts.renderers.matplotlib import ChartRequest,chart_payload,configure_report_factory,plot_frozen_chart  # noqa: F401  既有导入方依赖

configure_report_factory(FrozenReport)  # 渲染器的报告工厂由宿主注册（core 不 import app）


def charts(package=None):
    """该包声明的图表 id（声明序 = 报告里出图的顺序）。"""
    return [c['id'] for c in registry.charts(package)]


def frozen_statistics(args,ctx):
    report=FrozenReport(ctx.store,ctx.task_id);data=report.calculate(Calculation.model_validate(args))
    return ToolResult(status='ok',data_ref=ctx.store.put_artifact(ctx.task_id,'writer_calculation',data),method='frozen_calculation')

def query_frozen_materials(args,ctx):
    data=query_materials(FrozenReport(ctx.store,ctx.task_id),args)
    return ToolResult(status='ok',data_ref=ctx.store.put_artifact(ctx.task_id,'writer_materials',data),method='frozen_material_query')

HANDLERS={f.__name__:f for f in (frozen_statistics,query_frozen_materials,plot_frozen_chart)}
SCHEMAS={'frozen_statistics':Calculation.model_json_schema(),'query_frozen_materials':MaterialQuery.model_json_schema(),'plot_frozen_chart':ChartRequest.model_json_schema()}
DESCRIPTIONS={'frozen_statistics':'只读计算冻结事实；返回确定数值及来源，不改变口径','query_frozen_materials':'按日期、分类、关键词分页查询冻结记录的标题和原文梗概','plot_frozen_chart':'依据冻结事实用Matplotlib绘图；返回图表引用和统计值'}
def native_tools():return [{'type':'function','function':{'name':n,'description':DESCRIPTIONS[n],'parameters':SCHEMAS[n]}} for n in HANDLERS]

__all__=['FrozenReport','Calculation','MaterialQuery','query_materials','ToolResult','ChartRequest',
         'chart_payload','configure_report_factory','plot_frozen_chart','charts','frozen_statistics',
         'query_frozen_materials','HANDLERS','SCHEMAS','DESCRIPTIONS','native_tools','CHARTS']


def __getattr__(name: str):
    """旧名 `CHARTS` 惰性代理：第一次读到才解析当前包，随后缓存到模块字典（同一对象）。"""
    if name == 'CHARTS':
        value = charts()
        globals()[name] = value
        return value
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
