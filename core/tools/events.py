"""events 域工具：关键词/向量事件候选、自动归并、主题聚类与选题发现。自 `app/tool.py` 原样搬出，逻辑未改。

主题词典在 `cluster_event_themes` 函数内从 `vocabulary` 取，不在模块级取——`app.tool`
会 import 本模块，模块级回引 `app.tool` 必成环；`method['terms']` 写入的仍是同一份字典内容。
"""

from __future__ import annotations

from collections import Counter,defaultdict
from math import sqrt

from app.schemas import ToolResult
from . import vocabulary
from ._shared import records_of,words


def propose_keyword_event_candidates(args,ctx):
    """Stage 1: rare keyword overlap forms review candidates, preserving singleton records."""
    records=records_of(ctx,args['records_ref']); token_sets=[words(r['title']) for r in records]
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
    prior=ctx.store.get_artifact(args['keyword_candidates_ref']); records=records_of(ctx,prior['records_ref'])
    by_id={r['id']:r for r in records}; groups=prior['groups']
    group_of={rid:g['candidate_id'] for g in groups for rid in g['member_ids']}
    docs=[words(r['title']+' '+r.get('summary','')[:80]) for r in records]
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
    from .dedup import group_by_representative
    records=records_of(ctx,args['records_ref'])
    threshold=args.get('threshold')
    threshold=float(threshold) if threshold is not None else vocabulary.dedup_threshold()
    result=group_by_representative(records,threshold)
    result['source_records_ref']=args['records_ref']
    ref=ctx.store.put_artifact(ctx.task_id,'automatic_event_groups',result)
    return ToolResult(status='ok',data_ref=ref,method='title + summary cosine against immutable group representative; automatic grouping')

def cluster_event_themes(args,ctx):
    """Independent lexical theme clustering, with no claim that the source category is populated."""
    records=records_of(ctx,args['records_ref']); groups=defaultdict(list); items=[]
    terms=vocabulary.cluster_terms()
    for r in records:
        text=r['title']+' '+r.get('summary','')[:300]
        scores={label:sum(text.count(term) for term in label_terms) for label,label_terms in terms.items()}
        best=max(scores,key=scores.get) if scores else None
        label=best if best and scores[best]>0 else '待人工分类'
        evidence=[term for term in terms.get(label,[]) if term in text]
        groups[label].append(r['id'])
        items.append({'record_id':r['id'],'candidate_theme':label,'matched_terms':evidence,'source_ref':r['source_ref'],'source_category':r.get('category') or None,'status':'candidate'})
    ref=ctx.store.put_artifact(ctx.task_id,'theme_clusters',{'groups':[{'candidate_theme':k,'member_ids':v} for k,v in groups.items()],'items':items,'all_record_ids':[r['id'] for r in records],'method':{'type':'versioned transparent term dictionary','terms':terms,'source_field':'title + first 300 chars of summary','human_confirmation_required':True},'source_records_ref':args['records_ref']})
    return ToolResult(status='needs_review',data_ref=ref,method='lexical theme candidates; source category field is not silently filled',warnings=[f'{len(records)} records retained; {len(groups)} candidate buckets'],unresolved=[{'kind':'theme_confirmation','question':'主题词典候选需结合原文和 817 行测试表对照后人工确认'}])

def discover_topics(args,ctx):
    records=records_of(ctx,args['records_ref']); counts=Counter(r['category'] for r in records if r['category'])
    candidates=ctx.store.get_artifact(args['cluster_ref'])['groups'] if args.get('cluster_ref') else []
    ref=ctx.store.put_artifact(ctx.task_id,'topics',{'source_categories':dict(counts),'candidate_clusters':candidates,'record_ids':[r['id'] for r in records],'status':'requires_semantic_review'})
    return ToolResult(status='needs_review',data_ref=ref,method='source category frequency and separately supplied clustering candidates; naming unconfirmed',unresolved=[{'kind':'topic_naming','question':'主题名称需模型或人工确认'}])

HANDLERS={f.__name__:f for f in (propose_keyword_event_candidates,propose_vector_event_neighbors,group_events,cluster_event_themes,discover_topics)}
