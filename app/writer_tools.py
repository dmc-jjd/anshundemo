"""The Writer's bounded read-only tools. No imports or fact edits are exposed."""
from .frozen_report import FrozenReport,Calculation,MaterialQuery,query_materials
from .schemas import ToolResult
from core.charts import registry
from core.charts.renderers.matplotlib import ChartRequest,chart_payload,configure_report_factory,plot_frozen_chart  # noqa: F401  既有导入方依赖

CHARTS=[c['id'] for c in registry.charts()]
configure_report_factory(FrozenReport)  # 渲染器的报告工厂由宿主注册（core 不 import app）

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
