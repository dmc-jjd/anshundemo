"""Public business tools. Each handler consumes artifacts and never dispatches another tool."""
from __future__ import annotations
from collections import Counter,defaultdict
from math import sqrt
import base64,io
from .schemas import ToolSpec, ToolResult
from .template_compare import parse_report_document,compare_reports
from core.tools import vocabulary
from core.tools._shared import records_of as _records, words as _words
from core.tools.records import import_records,filter_records,classify_records,select_materials,read_evidence
from core.tools.locality import resolve_locality
from core.tools.metrics import calculate_metrics,build_table
REQUIRED_COLUMNS=vocabulary.required_columns()
COLUMN_MAP=vocabulary.column_map()
SUMMARY_COLUMNS=vocabulary.summary_columns()
LOCALITIES=vocabulary.localities()

def propose_keyword_event_candidates(args,ctx):
    """Stage 1: rare keyword overlap forms review candidates, preserving singleton records."""
    records=_records(ctx,args['records_ref']); token_sets=[_words(r['title']) for r in records]
    freq=Counter(t for ts in token_sets for t in ts)
    postings=defaultdict(list)
    for i,ts in enumerate(token_sets):
        for t in ts:
            if 1<freq[t]<=max(10,min(60,len(records)//100)): postings[t].append(i)
    parent=list(range(len(records)))
    def find(i):
        while parent[i]!=i: parent[i]=parent[parent[i]]; i=parent[i]
        return i
    def union(a,b): parent[find(b)]=find(a)
    candidate_pairs=set()
    for ids in postings.values():
        for a_pos,a in enumerate(ids):
            for b in ids[a_pos+1:]:
                if a==b: continue
                pair=(a,b) if a<b else (b,a)
                candidate_pairs.add(pair)
    threshold=float(args.get('keyword_jaccard',0.72))
    for a,b in candidate_pairs:
        ta,tb=token_sets[a],token_sets[b]
        if ta and tb and len(ta&tb)/len(ta|tb)>=threshold: union(a,b)
    groups=defaultdict(list)
    for i,r in enumerate(records): groups[find(i)].append(r['id'])
    out=[{'candidate_id':f'kw-{j}','member_ids':members,'status':'candidate' if len(members)>1 else 'unresolved_singleton'} for j,members in enumerate(groups.values(),1)]
    ref=ctx.store.put_artifact(ctx.task_id,'keyword_candidates',{'groups':out,'records_ref':args['records_ref'],'method':{'threshold':threshold,'token':'Chinese bigrams and alphanumeric terms','pair_count':len(candidate_pairs)},'all_record_ids':[r['id'] for r in records]})
    return ToolResult(status='needs_review',data_ref=ref,method='rare-keyword inverted index and Jaccard candidate grouping; never auto-confirm',warnings=[f'{len(out)} candidate groups from {len(records)} records'],unresolved=[{'kind':'event_confirmation','question':'关键词候选需人工确认、拆分或独立'}])

def propose_vector_event_neighbors(args,ctx):
    """Stage 2: sparse TF-IDF nearest candidates across stage-1 groups; no all-pairs scan."""
    prior=ctx.store.get_artifact(args['keyword_candidates_ref']); records=_records(ctx,prior['records_ref'])
    by_id={r['id']:r for r in records}; groups=prior['groups']
    group_of={rid:g['candidate_id'] for g in groups for rid in g['member_ids']}
    docs=[_words(r['title']+' '+r.get('summary','')[:80]) for r in records]
    df=Counter(t for doc in docs for t in doc); n=len(docs)
    weights=[]; postings=defaultdict(list)
    for i,doc in enumerate(docs):
        d={t:1/(1+df[t]/max(1,n)) for t in doc if df[t]<=max(20,min(80,n//100))}
        norm=sqrt(sum(v*v for v in d.values())) or 1
        d={t:v/norm for t,v in d.items()}; weights.append(d)
        for t in d: postings[t].append(i)
    min_score=float(args.get('min_score',0.45)); max_neighbors=int(args.get('max_neighbors',8)); max_candidates=int(args.get('max_candidates_per_record',200))
    pairs={}; evaluated=0
    for i,r in enumerate(records):
        overlaps=Counter()
        for t in weights[i]:
            for j in postings[t]:
                if j>i and group_of[r['id']]!=group_of[records[j]['id']]: overlaps[j]+=1
        ranked=[j for j,_ in overlaps.most_common(max_candidates)]
        local=[]
        for j in ranked:
            evaluated+=1; score=sum(v*weights[j].get(t,0) for t,v in weights[i].items())
            if score>=min_score: local.append((score,j))
        for score,j in sorted(local,reverse=True)[:max_neighbors]:
            other=records[j]; pairs[(r['id'],other['id'])]={'record_ids':[r['id'],other['id']],'candidate_groups':[group_of[r['id']],group_of[other['id']]],'score':round(score,4),'status':'candidate','reason':'cross-group lexical vector proximity; follow-up over days is eligible'}
    ref=ctx.store.put_artifact(ctx.task_id,'vector_neighbors',{'neighbors':list(pairs.values()),'keyword_candidates_ref':args['keyword_candidates_ref'],'all_record_ids':prior['all_record_ids'],'method':{'type':'sparse TF-IDF-like cosine','min_score':min_score,'max_neighbors':max_neighbors,'max_candidates_per_record':max_candidates,'evaluated_pairs':evaluated,'time_window':'not enforced; calibrate with real adjudicated cases'}})
    return ToolResult(status='needs_review',data_ref=ref,method='inverted-index sparse vector neighbor search across keyword groups; similarity only proposes review',warnings=[f'{evaluated} candidate pairs scored; {len(pairs)} neighbors emitted'],unresolved=[{'kind':'event_confirmation','question':'向量近邻含跨日跟进候选，需人工合并、拆分、独立或排除'}])

def group_events(args,ctx):
    from .event_grouping import group_by_representative
    records=_records(ctx,args['records_ref'])
    result=group_by_representative(records,float(args.get('threshold',.65)))
    result['source_records_ref']=args['records_ref']
    ref=ctx.store.put_artifact(ctx.task_id,'automatic_event_groups',result)
    return ToolResult(status='ok',data_ref=ref,method='title + summary cosine against immutable group representative; automatic grouping')

CLUSTER_TERMS=vocabulary.cluster_terms()

def cluster_event_themes(args,ctx):
    """Independent lexical theme clustering, with no claim that the source category is populated."""
    records=_records(ctx,args['records_ref']); groups=defaultdict(list); items=[]
    for r in records:
        text=r['title']+' '+r.get('summary','')[:300]
        scores={label:sum(text.count(term) for term in terms) for label,terms in CLUSTER_TERMS.items()}
        best=max(scores,key=scores.get) if scores else None
        label=best if best and scores[best]>0 else '待人工分类'
        evidence=[term for term in CLUSTER_TERMS.get(label,[]) if term in text]
        groups[label].append(r['id'])
        items.append({'record_id':r['id'],'candidate_theme':label,'matched_terms':evidence,'source_ref':r['source_ref'],'source_category':r.get('category') or None,'status':'candidate'})
    ref=ctx.store.put_artifact(ctx.task_id,'theme_clusters',{'groups':[{'candidate_theme':k,'member_ids':v} for k,v in groups.items()],'items':items,'all_record_ids':[r['id'] for r in records],'method':{'type':'versioned transparent term dictionary','terms':CLUSTER_TERMS,'source_field':'title + first 300 chars of summary','human_confirmation_required':True},'source_records_ref':args['records_ref']})
    return ToolResult(status='needs_review',data_ref=ref,method='lexical theme candidates; source category field is not silently filled',warnings=[f'{len(records)} records retained; {len(groups)} candidate buckets'],unresolved=[{'kind':'theme_confirmation','question':'主题词典候选需结合原文和 817 行测试表对照后人工确认'}])

def discover_topics(args,ctx):
    records=_records(ctx,args['records_ref']); counts=Counter(r['category'] for r in records if r['category'])
    candidates=ctx.store.get_artifact(args['cluster_ref'])['groups'] if args.get('cluster_ref') else []
    ref=ctx.store.put_artifact(ctx.task_id,'topics',{'source_categories':dict(counts),'candidate_clusters':candidates,'record_ids':[r['id'] for r in records],'status':'requires_semantic_review'})
    return ToolResult(status='needs_review',data_ref=ref,method='source category frequency and separately supplied clustering candidates; naming unconfirmed',unresolved=[{'kind':'topic_naming','question':'主题名称需模型或人工确认'}])

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

def parse_report_document_tool(args,ctx):
    data=parse_report_document(args['path']); ref=ctx.store.put_artifact(ctx.task_id,'parsed_document',data)
    return ToolResult(status='ok',data_ref=ref,method='OOXML blocks with original positions')

def compare_report_structures(args,ctx):
    data=compare_reports([ctx.store.get_artifact(x) for x in args['document_refs']]); ref=ctx.store.put_artifact(ctx.task_id,'template_comparison',data)
    return ToolResult(status='needs_review',data_ref=ref,method='local sequence alignment; semantic differences unconfirmed',unresolved=[{'kind':'template_review','question':'差异与槽位需模型或人工检查'}])

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
