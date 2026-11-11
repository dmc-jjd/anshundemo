"""The Writer's bounded read-only tools. No imports or fact edits are exposed."""
import base64,io,threading
from pathlib import Path
from pydantic import BaseModel,ConfigDict
from typing import Literal
from .frozen_report import FrozenReport,Calculation,MaterialQuery,query_materials
from .schemas import ToolResult

class ChartRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    chart_type:Literal['sentiment','daily','platform','theme','locality']
    style:Literal['pie','line','bar','barh']|None=None

CHARTS=['sentiment','daily','platform','theme','locality']
_plot_lock=threading.Lock()

def chart_payload(report,kind,style=None):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.font_manager import FontProperties
    from .chart_spec import styles_for
    if kind not in CHARTS:raise ValueError('unknown_chart_type')
    template=report.store.get_artifact(report.state.template_ref)
    selected=styles_for(template,report.state.metadata.get('chart_styles'))[kind]
    style=style or selected
    styles_for(template,{kind:style})
    values={'sentiment':report.metrics.get('sentiment',{}),'daily':report.metrics.get('daily_count',{}),
            'platform':report.metrics.get('platform',{}),'theme':report.categories_for(),
            'locality':report.counties_for()}[kind]
    if not values:raise ValueError('chart_data_missing:'+kind)
    titles=dict(zip(CHARTS,['舆情调性分布','每日舆情信息量','传播平台分布','已确认事件分类','事件涉及属地（跨区及不明单列）']))
    unit='件' if kind in ('theme','locality') else '条'
    fontpath=Path('C:/Windows/Fonts/msyh.ttc')
    font=FontProperties(fname=str(fontpath),size=12) if fontpath.exists() else FontProperties(family='DejaVu Sans',size=12)
    with _plot_lock:
        fig=Figure(figsize=(10,4.8),dpi=160,layout='constrained');FigureCanvasAgg(fig);ax=fig.subplots()
        labels=list(values);counts=list(values.values())
        if style=='pie':
            if sum(counts)<=0:raise ValueError('pie_requires_positive_total')
            palette=['#5b9bd5','#70ad47','#ed7d31','#ffc000','#8064a2','#45a6aa','#a5a5a5','#c0504d']
            if kind=='sentiment':palette=[{'正面':'#70ad47','中性':'#5b9bd5','负面':'#c0504d'}.get(label,'#a5a5a5') for label in labels]
            wedges,_,_=ax.pie(counts,colors=palette,startangle=90,autopct=lambda p:f'{p:.1f}%' if p>=1 else '',textprops={'fontsize':12},pctdistance=.72)
            total=sum(counts);legend=[f'{label}：{n}{unit}（{n/total*100:.2f}%）' for label,n in zip(labels,counts)]
            ax.legend(wedges,legend,loc='center left',bbox_to_anchor=(1,.5),frameon=False,prop=font);ax.set_aspect('equal')
        elif style=='line':
            ax.plot(range(len(labels)),counts,color='#16748c',linewidth=2)
            step=max(1,len(labels)//8);ticks=list(range(0,len(labels),step));ax.set_xticks(ticks,[labels[i][5:] for i in ticks])
        elif style=='barh':
            bars=ax.barh(range(len(labels)),counts,color='#16748c');ax.set_yticks(range(len(labels)),labels,fontproperties=font);ax.invert_yaxis()
            ax.bar_label(bars,padding=3,fontsize=10);ax.margins(x=.16)
        else:
            bars=ax.bar(range(len(labels)),counts,color='#16748c');ax.set_xticks(range(len(labels)),[x[5:] if kind=='daily' else x for x in labels],fontproperties=font,rotation=40,ha='right')
            ax.bar_label(bars,padding=3,fontsize=10);ax.margins(y=.15)
        ax.set_title(titles[kind],fontproperties=font)
        if style!='pie':
            ax.set_xlabel('数量（'+unit+'）' if style=='barh' else '日期' if kind=='daily' else TITLES_AXIS.get(kind,'类别'),fontproperties=font)
            if style!='barh':ax.set_ylabel('数量（'+unit+'）',fontproperties=font)
            ax.spines[['top','right']].set_visible(False);ax.grid(axis='x' if style=='barh' else 'y',alpha=.15)
        out=io.BytesIO();fig.savefig(out,format='png');fig.clear()
    return {'chart_type':kind,'style':style,'fact_ref':report.fact_ref,'counts':values,'unit':unit,
            'x_axis':None if style=='pie' else '数量' if style=='barh' else '日期' if kind=='daily' else '类别',
            'y_axis':None if style=='pie' else '类别' if style=='barh' else '数量',
            'scope':'confirmed_events' if kind in ('theme','locality') else 'all_records',
            'locality_basis':'冻结属地识别的唯一候选；跨区及不明单列' if kind=='locality' else None,
            'png_base64':base64.b64encode(out.getvalue()).decode()}

def frozen_statistics(args,ctx):
    report=FrozenReport(ctx.store,ctx.task_id);data=report.calculate(Calculation.model_validate(args))
    return ToolResult(status='ok',data_ref=ctx.store.put_artifact(ctx.task_id,'writer_calculation',data),method='frozen_calculation')

def query_frozen_materials(args,ctx):
    data=query_materials(FrozenReport(ctx.store,ctx.task_id),args)
    return ToolResult(status='ok',data_ref=ctx.store.put_artifact(ctx.task_id,'writer_materials',data),method='frozen_material_query')

def plot_frozen_chart(args,ctx):
    from .chart_spec import styles_for
    request=ChartRequest.model_validate(args);report=FrozenReport(ctx.store,ctx.task_id)
    chosen=styles_for(ctx.store.get_artifact(report.state.template_ref),report.state.metadata.get('chart_styles'))[request.chart_type]
    if request.style and request.style!=chosen:raise ValueError('chart_style_owned_by_template_or_human')
    data=chart_payload(report,request.chart_type,chosen)
    return ToolResult(status='ok',data_ref=ctx.store.put_artifact(ctx.task_id,'writer_chart',data),method='matplotlib_agg')

HANDLERS={f.__name__:f for f in (frozen_statistics,query_frozen_materials,plot_frozen_chart)}
SCHEMAS={'frozen_statistics':Calculation.model_json_schema(),'query_frozen_materials':MaterialQuery.model_json_schema(),'plot_frozen_chart':ChartRequest.model_json_schema()}
DESCRIPTIONS={'frozen_statistics':'只读计算冻结事实；返回确定数值及来源，不改变口径','query_frozen_materials':'按日期、分类、关键词分页查询冻结记录的标题和原文梗概','plot_frozen_chart':'依据冻结事实用Matplotlib绘图；返回图表引用和统计值'}
def native_tools():return [{'type':'function','function':{'name':n,'description':DESCRIPTIONS[n],'parameters':SCHEMAS[n]}} for n in HANDLERS]

TITLES_AXIS={'sentiment':'调性','platform':'传播平台','theme':'事件分类','locality':'属地'}
