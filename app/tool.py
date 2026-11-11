"""Public business tools. Each handler consumes artifacts and never dispatches another tool."""
from __future__ import annotations
from collections import Counter
import base64,io
from .schemas import ToolSpec, ToolResult
from core.tools import vocabulary
from core.tools.records import import_records,filter_records,classify_records,select_materials,read_evidence
from core.tools.locality import resolve_locality
from core.tools.metrics import calculate_metrics,build_table
from core.tools.events import (propose_keyword_event_candidates,propose_vector_event_neighbors,
                               group_events,cluster_event_themes,discover_topics)
from core.tools.documents import parse_report_document_tool,compare_report_structures
REQUIRED_COLUMNS=vocabulary.required_columns()
COLUMN_MAP=vocabulary.column_map()
SUMMARY_COLUMNS=vocabulary.summary_columns()
LOCALITIES=vocabulary.localities()
CLUSTER_TERMS=vocabulary.cluster_terms()

def render_chart(args,ctx):
    from PIL import Image,ImageDraw,ImageFont
    chart_type=args['chart_type']; metrics=ctx.store.get_artifact(args['metrics_ref'])
    candidate=False
    if chart_type=='sentiment': values=metrics['sentiment']; title='舆情情绪分布（原始记录）'
    elif chart_type=='daily': values=metrics['daily_count']; title='每日信息量（原始记录）'
    elif chart_type=='platform': values=metrics['platform']; title='媒体环节分布（原始记录）'
    elif chart_type=='theme':
        if not args.get('cluster_ref'): return ToolResult(status='needs_review',method='theme chart requires cluster input',unresolved=[{'kind':'chart_input','question':'分类候选缺失'}])
        groups=ctx.store.get_artifact(args['cluster_ref'])['groups']; values={g['candidate_theme']:len(g['member_ids']) for g in groups}; title='敏感及负面并集主题候选分布'; candidate=True
    elif chart_type=='locality':
        if not args.get('locality_ref'): return ToolResult(status='needs_review',method='locality chart requires locality input',unresolved=[{'kind':'chart_input','question':'属地候选缺失'}])
        items=ctx.store.get_artifact(args['locality_ref'])['items']; values=dict(Counter(x['candidates'][0] for x in items if len(x['candidates'])==1)); title='敏感及负面并集属地候选分布'; candidate=True
    else: raise ValueError('unknown_chart_type')
    if not values: return ToolResult(status='needs_review',method='chart has no data',unresolved=[{'kind':'chart_input','question':'无可绘制数据'}])
    font_path='C:/Windows/Fonts/msyh.ttc'
    font=ImageFont.truetype(font_path,24); small=ImageFont.truetype(font_path,18)
    width,height=1050,640; img=Image.new('RGB',(width,height),'#ffffff'); d=ImageDraw.Draw(img)
    d.text((36,22),title+(' · 未确认' if candidate else ''),font=font,fill='#17374b')
    if chart_type=='daily':
        ordered=sorted(values.items())
        maxval=max(values.values()) or 1; left,right,top,bottom=85,1000,95,550
        d.line((left,bottom,right,bottom),fill='#9fb2bb',width=2); d.line((left,top,left,bottom),fill='#9fb2bb',width=2)
        points=[]
        for i,(label,value) in enumerate(ordered):
            x=left+int(i/max(1,len(ordered)-1)*(right-left)); y=bottom-int(value/maxval*(bottom-top))
            points.append((x,y))
            if i%max(1,len(ordered)//8)==0: d.text((x-18,bottom+8),label[5:],font=small,fill='#5b6c77')
        if len(points)>1: d.line(points,fill='#2d7895',width=4)
        for x,y in points: d.ellipse((x-4,y-4,x+4,y+4),fill='#2d7895')
        d.text((35,75),f'峰值 {maxval} 条',font=small,fill='#334b5c')
    else:
        ordered=sorted(values.items(),key=lambda kv:kv[1],reverse=True)[:15]
        maxval=max(v for _,v in ordered) or 1
        step=min(165,(height-155)/len(ordered)); bar_height=min(42,max(20,step-12))
        for i,(label,value) in enumerate(ordered):
            y=int(80+i*step); d.text((35,y),str(label)[:10],font=small,fill='#334b5c')
            bar=int(value/maxval*600); d.rectangle((230,y+4,230+bar,y+4+bar_height),fill='#2d7895')
            d.text((240+bar,y),str(value),font=small,fill='#17374b')
    d.text((35,603),'来源：本任务数据工件；候选图须人工确认后才能用于正式报告',font=small,fill='#6c7c86')
    buffer=io.BytesIO(); img.save(buffer,format='PNG')
    ref=ctx.store.put_artifact(ctx.task_id,'chart',{'chart_type':chart_type,'title':title,'values':values,'candidate':candidate,'metrics_ref':args['metrics_ref'],'source_refs':[x for x in (args.get('cluster_ref'),args.get('locality_ref')) if x],'png_base64':base64.b64encode(buffer.getvalue()).decode(),'style_version':2,'method':'Pillow chart; candidate labels shown when unconfirmed'})
    return ToolResult(status='needs_review' if candidate else 'ok',data_ref=ref,method='Pillow chart from referenced metrics; candidate watermark where applicable',unresolved=[{'kind':'chart_confirmation','question':'候选主题或属地图不能作为正式图表'}] if candidate else [])

HANDLERS={x.__name__:x for x in [import_records,filter_records,resolve_locality,group_events,propose_keyword_event_candidates,propose_vector_event_neighbors,calculate_metrics,classify_records,cluster_event_themes,discover_topics,select_materials,read_evidence,render_chart,build_table,parse_report_document_tool,compare_report_structures]}
HANDLERS['parse_report_document']=HANDLERS.pop('parse_report_document_tool')

DESCRIPTIONS={'propose_keyword_event_candidates':'第一轮关键词匹配形成同事件候选组','propose_vector_event_neighbors':'第二轮向量化近邻消费第一轮候选，补充跨组和隔天跟进候选'}
READ_ONLY={'read_evidence','parse_report_document','compare_report_structures','render_chart','build_table'}
ARGUMENTS={
    'group_events':{'required':['records_ref'],'properties':{'records_ref':'artifact_ref','threshold':'number (0,1]'}},
    'import_records':{'required':['path'],'properties':{'path':'string','sheet_index':'integer'}},
    'filter_records':{'required':['records_ref','scope'],'properties':{'records_ref':'artifact_ref','scope':'all|positive|neutral|negative|warning|negative_warning|negative_or_warning|media','media_level':'string'}},
    'propose_keyword_event_candidates':{'required':['records_ref'],'properties':{'records_ref':'artifact_ref','keyword_jaccard':'number'}},
    'propose_vector_event_neighbors':{'required':['keyword_candidates_ref'],'properties':{'keyword_candidates_ref':'artifact_ref','min_score':'number','max_neighbors':'integer'}},
    'cluster_event_themes':{'required':['records_ref'],'properties':{'records_ref':'artifact_ref'}},
    'render_chart':{'required':['metrics_ref','chart_type'],'properties':{'metrics_ref':'artifact_ref','chart_type':'sentiment|daily|platform|theme|locality'}},
}
def get_tool_specs()->list[ToolSpec]:
    from .writer_tools import HANDLERS as writers,SCHEMAS,DESCRIPTIONS as descriptions
    HANDLERS.update(writers);READ_ONLY.update(writers);ARGUMENTS.update(SCHEMAS);DESCRIPTIONS.update(descriptions)
    from .historical_web import HANDLERS as web,SCHEMAS as webschemas,DESCRIPTIONS as webdesc
    HANDLERS.update(web);READ_ONLY.update(web);ARGUMENTS.update(webschemas);DESCRIPTIONS.update(webdesc)
    requirements={'propose_vector_event_neighbors':['keyword_event_candidates'],'propose_keyword_event_candidates':['normalized_records'],'cluster_event_themes':['normalized_records']}
    products={'import_records':['normalized_records'],'propose_keyword_event_candidates':['keyword_event_candidates'],'propose_vector_event_neighbors':['vector_event_neighbors'],'cluster_event_themes':['theme_cluster_candidates']}
    return [ToolSpec(name=n,version='2' if n=='group_events' else '1',description=DESCRIPTIONS.get(n,n.replace('_',' ')),required_capabilities=requirements.get(n,[]),produced_capabilities=products.get(n,[]),mutates_facts=n not in READ_ONLY,arguments_schema=ARGUMENTS.get(n,{})) for n in HANDLERS]
def get_tool_handler(name:str):
    get_tool_specs()
    return HANDLERS[name]

__all__ = ['import_records','filter_records','resolve_locality','group_events',
           'propose_keyword_event_candidates','propose_vector_event_neighbors','calculate_metrics',
           'classify_records','cluster_event_themes','discover_topics','select_materials','read_evidence',
           'render_chart','build_table','parse_report_document_tool','compare_report_structures',
           'CLUSTER_TERMS','HANDLERS','READ_ONLY','ARGUMENTS','DESCRIPTIONS',
           'get_tool_specs','get_tool_handler']
