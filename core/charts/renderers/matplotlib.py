"""Matplotlib 正式图渲染器：依据冻结事实绘制报告图。标题/单位/口径/轴标签一律取自客户包 charts 段。"""
import base64,io,threading
from pathlib import Path
from pydantic import BaseModel,ConfigDict
from typing import Literal
from app.frozen_report import FrozenReport
from app.schemas import ToolResult
from core.charts import registry
from core.charts.spec import styles_for

class ChartRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    chart_type:Literal['sentiment','daily','platform','theme','locality']
    style:Literal['pie','line','bar','barh']|None=None

# 模块级常量：既有调用方按 list 使用（app.writer_tools 经 app 层 import，此时已 configure）
CHARTS=[c['id'] for c in registry.charts()]
_plot_lock=threading.Lock()

def chart_payload(report,kind,style=None):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.font_manager import FontProperties
    from app.config import DATA
    if kind not in CHARTS:raise ValueError('unknown_chart_type')
    template=report.store.get_artifact(report.state.template_ref)
    selected=styles_for(template,report.state.metadata.get('chart_styles'),data_root=DATA)[kind]
    style=style or selected
    styles_for(template,{kind:style},data_root=DATA)
    chart=registry.chart(kind)
    _artifact,_,key=chart['binding']['source'].partition('.')
    # 三个一次性全算：dict 字面量保留现状语义，categories_for()/counties_for() 对所有 kind 都会调用
    try:
        values={'metrics':report.metrics.get(key,{}),'theme_clusters':report.categories_for(),
                'locality':report.counties_for()}[_artifact]
    except KeyError:raise ValueError('unknown_chart_source') from None
    if not values:raise ValueError('chart_data_missing:'+kind)
    unit=chart['unit']
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
        ax.set_title(chart['final_title'],fontproperties=font)
        if style!='pie':
            ax.set_xlabel('数量（'+unit+'）' if style=='barh' else '日期' if kind=='daily' else chart.get('axis_label') or '类别',fontproperties=font)
            if style!='barh':ax.set_ylabel('数量（'+unit+'）',fontproperties=font)
            ax.spines[['top','right']].set_visible(False);ax.grid(axis='x' if style=='barh' else 'y',alpha=.15)
        out=io.BytesIO();fig.savefig(out,format='png');fig.clear()
    return {'chart_type':kind,'style':style,'fact_ref':report.fact_ref,'counts':values,'unit':unit,
            'x_axis':None if style=='pie' else '数量' if style=='barh' else '日期' if kind=='daily' else '类别',
            'y_axis':None if style=='pie' else '类别' if style=='barh' else '数量',
            'scope':chart['scope'],
            'locality_basis':chart.get('locality_basis'),
            'png_base64':base64.b64encode(out.getvalue()).decode()}

def plot_frozen_chart(args,ctx):
    from app.config import DATA
    request=ChartRequest.model_validate(args);report=FrozenReport(ctx.store,ctx.task_id)
    chosen=styles_for(ctx.store.get_artifact(report.state.template_ref),report.state.metadata.get('chart_styles'),data_root=DATA)[request.chart_type]
    if request.style and request.style!=chosen:raise ValueError('chart_style_owned_by_template_or_human')
    data=chart_payload(report,request.chart_type,chosen)
    return ToolResult(status='ok',data_ref=ctx.store.put_artifact(ctx.task_id,'writer_chart',data),method='matplotlib_agg')

HANDLERS={f.__name__:f for f in (plot_frozen_chart,)}
