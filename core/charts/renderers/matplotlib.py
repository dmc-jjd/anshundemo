"""Matplotlib 正式图渲染器：依据冻结事实绘制报告图。标题/单位/口径/轴标签一律取自客户包 charts 段。"""
import base64,io,threading
from pathlib import Path
from pydantic import BaseModel,ConfigDict
from typing import Literal
from core.tools.contracts import ToolResult
from core import paths
from core.charts import registry
from core.charts.spec import styles_for

class ChartRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    chart_type:str
    style:Literal['pie','line','bar','barh']|None=None

# 图表 id 集合不再是模块级快照（旧 `CHARTS=[c['id'] for c in registry.charts()]` 在首次
# import 期冻结成当时那个包，B 包只有 3 张图）；现在每次按当前包（`registry.ids()`）判定。
_plot_lock=threading.Lock()
# 报告对象工厂由宿主注入（`app/writer_tools.py` 注册 `FrozenReport`）——core 不 import app。
_report_factory=None

def configure_report_factory(factory):
    global _report_factory
    _report_factory=factory

def chart_payload(report,kind,style=None):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.font_manager import FontProperties
    from core.charts.spec import resolve_chart,family_of,chart_title,declared_ids
    template=report.store.get_artifact(report.state.template_ref) if getattr(report,'state',None) and report.state.template_ref else {}
    if kind not in declared_ids(template):raise ValueError('unknown_chart_type')
    selected=styles_for(template,report.state.metadata.get('chart_styles'),data_root=paths.data_root())[kind]
    style=style or selected
    styles_for(template,{kind:style},data_root=paths.data_root())
    chart=resolve_chart(kind,template)
    family=family_of(chart)
    scope=chart.get('scope') or 'all_records'
    binding=(chart.get('binding') or {}).get('source') or ''
    _artifact,_,key=binding.partition('.')
    try:
        if _artifact=='theme_clusters':
            values=report.categories_for(scope if scope!='all_records' else 'confirmed_events')
        elif _artifact=='locality':
            values=report.counties_for(scope if scope!='all_records' else 'confirmed_events')
        elif _artifact=='metrics':
            values=report.metric_counts(key,scope)
        else:
            raise KeyError(_artifact)
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
            if family=='sentiment':palette=[{'正面':'#70ad47','中性':'#5b9bd5','负面':'#c0504d'}.get(label,'#a5a5a5') for label in labels]
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
            bars=ax.bar(range(len(labels)),counts,color='#16748c');ax.set_xticks(range(len(labels)),[x[5:] if family=='daily' else x for x in labels],fontproperties=font,rotation=40,ha='right')
            ax.bar_label(bars,padding=3,fontsize=10);ax.margins(y=.15)
        ax.set_title(chart_title(chart),fontproperties=font)
        if style!='pie':
            ax.set_xlabel('数量（'+unit+'）' if style=='barh' else '日期' if family=='daily' else chart.get('axis_label') or '类别',fontproperties=font)
            if style!='barh':ax.set_ylabel('数量（'+unit+'）',fontproperties=font)
            ax.spines[['top','right']].set_visible(False);ax.grid(axis='x' if style=='barh' else 'y',alpha=.15)
        out=io.BytesIO();fig.savefig(out,format='png');fig.clear()
    return {'chart_type':kind,'style':style,'fact_ref':report.fact_ref,'counts':values,'unit':unit,
            'x_axis':None if style=='pie' else '数量' if style=='barh' else '日期' if family=='daily' else '类别',
            'y_axis':None if style=='pie' else '类别' if style=='barh' else '数量',
            'scope':scope,
            'locality_basis':chart.get('locality_basis'),
            'png_base64':base64.b64encode(out.getvalue()).decode()}

def plot_frozen_chart(args,ctx):
    request=ChartRequest.model_validate(args)
    if _report_factory is None:raise RuntimeError('report_factory_not_configured')
    report=_report_factory(ctx.store,ctx.task_id)
    chosen=styles_for(ctx.store.get_artifact(report.state.template_ref),report.state.metadata.get('chart_styles'),data_root=paths.data_root())[request.chart_type]
    if request.style and request.style!=chosen:raise ValueError('chart_style_owned_by_template_or_human')
    data=chart_payload(report,request.chart_type,chosen)
    return ToolResult(status='ok',data_ref=ctx.store.put_artifact(ctx.task_id,'writer_chart',data),method='matplotlib_agg')

HANDLERS={f.__name__:f for f in (plot_frozen_chart,)}
