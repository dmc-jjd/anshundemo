"""Public business tools. Each handler consumes artifacts and never dispatches another tool."""
from __future__ import annotations
from collections import Counter,defaultdict
from datetime import datetime,timedelta
from math import sqrt
from pathlib import Path
import hashlib,re,statistics,base64,io
from .schemas import ToolSpec, ToolResult
from .ooxml import read_xlsx
from .template_compare import parse_report_document,compare_reports
from core.tools import vocabulary
REQUIRED_COLUMNS=vocabulary.required_columns()
COLUMN_MAP=vocabulary.column_map()
SUMMARY_COLUMNS=vocabulary.summary_columns()
LOCALITIES=vocabulary.localities()

def _words(text:str)->set[str]:
    text=re.sub(r'\s+','',str(text or '').lower())
    chinese=re.findall(r'[\u4e00-\u9fff]{2,}|[a-z0-9]{3,}',text)
    out=set()
    for chunk in chinese:
        if re.fullmatch(r'[\u4e00-\u9fff]+',chunk):
            out.update(chunk[i:i+2] for i in range(len(chunk)-1))
        else: out.add(chunk)
    return out

def _records(ctx,ref):
    obj=ctx.store.get_artifact(ref)
    return obj['records'] if isinstance(obj,dict) and 'records' in obj else obj

def import_records(args,ctx):
    path=Path(args['path']); sheet=int(args.get('sheet_index',3))
    book=read_xlsx(path,sheet_index=sheet)
    rows=book['rows']; header=rows[0]['cells']
    for column in REQUIRED_COLUMNS:
        if column not in header: raise ValueError('missing_required_columns')
    records=[]; file_hash=hashlib.sha256(path.read_bytes()).hexdigest()
    for row in rows[1:]:
        cells=row['cells']; data={key:(cells[i] if i<len(cells) else '') for i,key in enumerate(header)}
        if not any(data.values()): continue
        rid=f'{file_hash[:12]}:{book["sheet"]}:{row["excel_row"]}'
        published=data.get('发布时间','')
        if re.fullmatch(r'\d+(?:\.\d+)?',published):
            try:published=(datetime(1899,12,30)+timedelta(days=float(published))).isoformat(timespec='minutes')
            except (ValueError,OverflowError):pass
        mapped={field:data.get(column,'') for column,field in COLUMN_MAP.items()}
        mapped['published']=published
        records.append({
            'id':rid,
            **mapped,
            'summary':data.get(SUMMARY_COLUMNS[0]) or (data.get(SUMMARY_COLUMNS[1],'') or '')[:1200],
            'source_ref':{'file_hash':file_hash,'sheet':book['sheet'],'row':row['excel_row']},
        })
    ref=ctx.store.put_artifact(ctx.task_id,'records',{'records':records,'file_hash':file_hash,'header':header,'sheet':book['sheet']})
    return ToolResult(status='ok',data_ref=ref,method=f'OOXML sheet {sheet}; every nonempty source row retained',warnings=[f'{len(records)} source rows'])

def filter_records(args,ctx):
    records=_records(ctx,args['records_ref']); scope=args.get('scope','negative')
    if scope=='negative': selected=[r for r in records if '负' in r.get('sentiment','')]
    elif scope=='positive': selected=[r for r in records if r.get('sentiment')=='正面']
    elif scope=='neutral': selected=[r for r in records if r.get('sentiment')=='中性']
    elif scope in ('warning','negative_warning','negative_or_warning'):
        vals={str(r.get('warning','')).strip() for r in records}
        if scope!='negative_or_warning' and not any(v in ('是','已预警','1','true','TRUE','预警') for v in vals):
            return ToolResult(status='needs_review',method='warning field examined',unresolved=[{'kind':'warning_rule','question':'预警字段没有可确认的真值规则','values':sorted(vals)[:20]}])
        truth=('是','已预警','1','true','TRUE','预警')
        if scope=='negative_or_warning': selected=[r for r in records if '负' in r.get('sentiment','') or str(r.get('warning','')).strip() in truth]
        else: selected=[r for r in records if str(r.get('warning','')).strip() in truth and (scope=='warning' or '负' in r.get('sentiment',''))]
    elif scope=='media': selected=[r for r in records if r.get('media_level')==args.get('media_level')]
    else: raise ValueError('unknown_scope')
    ref=ctx.store.put_artifact(ctx.task_id,'records',{'records':selected,'scope':scope,'parent_ref':args['records_ref']})
    return ToolResult(status='ok',data_ref=ref,method=f'exact field filter: {scope}',warnings=[f'{len(selected)} selected of {len(records)}'])

def resolve_locality(args,ctx):
    records=_records(ctx,args['records_ref']); terms=LOCALITIES
    results=[]; unresolved=[]
    for r in records:
        text=r['title']+' '+r.get('summary',''); hits=[k for k,ws in terms.items() if any(w in text for w in ws)]
        results.append({'record_id':r['id'],'candidates':hits,'evidence':hits})
        if len(hits)!=1: unresolved.append({'kind':'locality','record_ids':[r['id']],'question':'属地不唯一或缺失','candidates':hits})
    ref=ctx.store.put_artifact(ctx.task_id,'locality',{'items':results,'source_records_ref':args['records_ref']})
    return ToolResult(status='needs_review' if unresolved else 'ok',data_ref=ref,method='explicit district term match; no inferred locality',unresolved=unresolved[:20],warnings=[f'{len(unresolved)} locality rows need review'] if unresolved else [])

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

def calculate_metrics(args,ctx):
    records=_records(ctx,args['records_ref']); sentiment=Counter(r['sentiment'] or '未知' for r in records); platform=Counter(r['platform'] or '未知' for r in records)
    metrics={'record_count':len(records),'sentiment':dict(sentiment),'platform':dict(platform),'warning_raw_count':sum(str(r.get('warning','')).strip() in ('是','已预警','1','true','TRUE','预警') for r in records)}
    day=Counter()
    for r in records:
        value=str(r.get('published',''))
        try:
            if re.fullmatch(r'\d+(?:\.\d+)?',value):
                key=(datetime(1899,12,30)+timedelta(days=float(value))).date().isoformat()
            else: key=value[:10]
            if key: day[key]+=1
        except (ValueError,OverflowError): pass
    metrics['daily_count']=dict(sorted(day.items()))
    metrics['peak_day']=max(day,key=day.get) if day else None
    if args.get('negative_ref'): metrics['negative_count']=len(_records(ctx,args['negative_ref']))
    if args.get('confirmed_event_groups_ref'):
        groups=ctx.store.get_artifact(args['confirmed_event_groups_ref'])['groups']; metrics['confirmed_event_count']=len(groups)
        metrics['confirmed_event_member_ids']=[x for g in groups for x in g['member_ids']]
    denom=args.get('denominator')
    if denom is not None: metrics['ratio']=None if not denom else len(records)/denom
    ref=ctx.store.put_artifact(ctx.task_id,'metrics',metrics)
    return ToolResult(status='needs_review' if denom==0 else 'ok',data_ref=ref,method='source record counts and separately confirmed event counts',unresolved=[{'kind':'zero_denominator','question':'分母为零，比例缺失'}] if denom==0 else [])

def group_events(args,ctx):
    from .event_grouping import group_by_representative
    records=_records(ctx,args['records_ref'])
    result=group_by_representative(records,float(args.get('threshold',.65)))
    result['source_records_ref']=args['records_ref']
    ref=ctx.store.put_artifact(ctx.task_id,'automatic_event_groups',result)
    return ToolResult(status='ok',data_ref=ref,method='title + summary cosine against immutable group representative; automatic grouping')

def classify_records(args,ctx):
    records=_records(ctx,args['records_ref']); items=[{'record_id':r['id'],'category':r['category'] or None} for r in records]
    ref=ctx.store.put_artifact(ctx.task_id,'classifications',{'items':items,'all_record_ids':[r['id'] for r in records]})
    missing=sum(x['category'] is None for x in items)
    return ToolResult(status='needs_review' if missing else 'ok',data_ref=ref,method='source event category field; blanks remain blank',warnings=[f'{missing} blank source categories'] if missing else [],unresolved=[{'kind':'missing_source_category','question':'原始分类为空；请运行独立聚类候选工具并人工确认'}] if missing else [])

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

def select_materials(args,ctx):
    records=_records(ctx,args['records_ref']); limit=int(args.get('limit',10))
    items=[{'record_id':r['id'],'title':r['title'],'source_ref':r['source_ref']} for r in records[:limit]]
    ref=ctx.store.put_artifact(ctx.task_id,'materials',{'items':items,'selection_rule':'source row order; representative quality unconfirmed'})
    return ToolResult(status='needs_review',data_ref=ref,method='source order preview only',unresolved=[{'kind':'selection_rule','question':'代表材料和 TOP10 排序规则待确认'}])

def read_evidence(args,ctx):
    data=ctx.store.get_artifact(args['data_ref']); ref=ctx.store.put_artifact(ctx.task_id,'evidence',data)
    return ToolResult(status='ok',data_ref=ref,method='local artifact read',tool_version='1')

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

def build_table(args,ctx):
    if not args.get('confirmed_event_groups_ref') or not args.get('ranking_rule'):
        return ToolResult(status='needs_review',method='editable table requires confirmed events and ranking rule',unresolved=[{'kind':'top10_rule','question':'缺少确认事件组或 TOP10 排序规则'}])
    groups=ctx.store.get_artifact(args['confirmed_event_groups_ref'])['groups']
    if args['ranking_rule']!='member_count_desc':
        return ToolResult(status='needs_review',method='unsupported ranking rule',unresolved=[{'kind':'top10_rule','question':'排序规则尚未实现或确认'}])
    ordered=sorted(groups,key=lambda g:(-len(g['member_ids']),g['member_ids'][0] if g['member_ids'] else ''))[:10]
    rows=[{'rank':i,'member_ids':g['member_ids'],'title':g.get('title') or '待核对代表标题','heat':None} for i,g in enumerate(ordered,1)]
    ref=ctx.store.put_artifact(ctx.task_id,'top10_table',{'rows':rows,'ranking_rule':args['ranking_rule'],'fact_ref':args.get('fact_ref'),'editable_word_table':True})
    return ToolResult(status='needs_review',data_ref=ref,method='confirmed-event member count ranking; heat still unconfirmed',unresolved=[{'kind':'heat_rule','question':'热度星级缺少来源规则'}])

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
