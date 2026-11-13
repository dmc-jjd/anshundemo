"""Automatic cosine grouping against an immutable representative, without chaining."""
from collections import Counter,defaultdict
from math import log,sqrt

from core.text import NORMALIZATION_VERSION,TOKENIZER_VERSION,norm_or_raw,tokenize
from . import vocabulary

def group_by_representative(records,threshold=None):
    if threshold is None:threshold=vocabulary.dedup_threshold()
    if not 0<threshold<=1:raise ValueError('similarity_threshold_must_be_between_zero_and_one')
    tokens=[]
    for record in records:
        title=norm_or_raw(record,'normalized_title','title')
        summary=norm_or_raw(record,'normalized_summary','summary')
        tokens.append(Counter(tokenize(title+' '+summary)))
    frequency=Counter(term for terms in tokens for term in terms)
    vectors=[]
    for counts in tokens:
        vector={term:count*(log((len(records)+1)/(frequency[term]+1))+1) for term,count in counts.items()}
        norm=sqrt(sum(value*value for value in vector.values())) or 1
        vectors.append({term:value/norm for term,value in vector.items()})
    groups=[];index=defaultdict(set);scores={};comparisons=0;borderline=[]
    for i,record in enumerate(records):
        vector=vectors[i];similarities=defaultdict(float)
        for term,weight in vector.items():
            for gid in index[term]:similarities[gid]+=weight*vectors[groups[gid]['representative_index']][term]
        best=None;best_score=-1;comparisons+=len(similarities)
        for gid in sorted(similarities):
            score=similarities[gid]
            if score>best_score:best,best_score=gid,score
        if best is not None and best_score+1e-12>=threshold:
            groups[best]['member_ids'].append(record['id']);scores[record['id']]=round(min(1,best_score),6)
        else:
            new_index=len(groups)
            if best is not None and best_score>=threshold*vocabulary.dedup_candidate_floor():
                borderline.append({'id':f'pair-{len(borderline)+1}','source_group':f'event-{new_index+1}',
                    'target_group':groups[best]['id'],'score':round(best_score,6)})
            best=new_index
            groups.append({'id':f'event-{best+1}','title':record['title'],'representative_id':record['id'],
                           'representative_index':i,'member_ids':[record['id']]})
            for term in vector:index[term].add(best)
            scores[record['id']]=1.0
    for group in groups:group.pop('representative_index')
    return {'groups':groups,'member_scores':scores,'all_record_ids':[r['id'] for r in records],'borderline_candidates':borderline,
            'method':{'type':'TF-IDF sparse cosine','input':'normalized_title + normalized_summary','threshold':threshold,
                      'representative':'first member, immutable','automatic':True,'comparisons':comparisons,
                      'model_candidate_floor':threshold*vocabulary.dedup_candidate_floor(),
                      'normalization':NORMALIZATION_VERSION,'tokenizer':TOKENIZER_VERSION}}


def _merge_sort_key(group_id):
    """`event-9` 排在 `event-10` 前：纯字典序会让锚组选取跨到四位数编号，结果仍确定但不可解释。"""
    prefix,_,digits=group_id.rpartition('-')
    return (0,prefix,int(digits),group_id) if digits.isdigit() else (1,group_id,0,group_id)


def merge_group_round(groups,records,*,threshold=None):
    """第二轮：按「组级聚合向量」合并同一真实事件被拆开的多个组。返回 `(merged_groups, method)`。

    第一轮拿单条原文当代表，同事件不同措辞过不了阈值（共同词本来就被 IDF 压低）。
    这里把每组全部成员的 token 取并集（保留词频），再对「组集合」重算 IDF：单条里
    权重低的共同词在并集里成为稳定信号，各帖独有的罕见词被稀释。锚组与第一轮同样
    不可变——只与簇的锚组比余弦，不与簇内其它成员比，因此不链式漂移。
    """
    if threshold is None:threshold=vocabulary.dedup_merge_threshold()
    if not 0<threshold<=1:raise ValueError('merge_threshold_must_be_between_zero_and_one')
    by_id={record['id']:record for record in records}
    counters=[]
    for group in groups:
        counts=Counter()
        for rid in group['member_ids']:
            record=by_id.get(rid)
            if record is None:continue
            title=norm_or_raw(record,'normalized_title','title')
            summary=norm_or_raw(record,'normalized_summary','summary')
            counts.update(tokenize(title+' '+summary))
        counters.append(counts)
    frequency=Counter(term for counts in counters for term in counts)
    total=len(groups)
    vectors=[]
    for counts in counters:
        vector={term:count*(log((total+1)/(frequency[term]+1))+1) for term,count in counts.items()}
        norm=sqrt(sum(value*value for value in vector.values())) or 1
        vectors.append({term:value/norm for term,value in vector.items()})
    clusters=[];postings=defaultdict(list);comparisons=0
    for i in sorted(range(total),key=lambda index:_merge_sort_key(groups[index]['id'])):
        vector=vectors[i];similarities=defaultdict(float)
        for term,weight in vector.items():
            for cluster in postings[term]:similarities[cluster]+=weight*vectors[clusters[cluster]['anchor']][term]
        comparisons+=len(similarities)
        best=None;best_score=-1.0
        for cluster in sorted(similarities):
            if similarities[cluster]>best_score:best,best_score=cluster,similarities[cluster]
        if best is not None and best_score+1e-12>=threshold:
            clusters[best]['members'].append(i)
            clusters[best]['scores'][groups[i]['id']]=round(min(1.0,best_score),6)
        else:
            best=len(clusters)
            clusters.append({'anchor':i,'members':[i],'scores':{}})
            for term in vector:postings[term].append(best)
    merged=[]
    for cluster in sorted(clusters,key=lambda item:item['anchor']):
        anchor=groups[cluster['anchor']]
        member_ids=[rid for index in cluster['members'] for rid in groups[index]['member_ids']]
        item={'id':anchor['id'],'title':anchor['title'],'representative_id':anchor['representative_id'],
              'member_ids':member_ids,'member_count':len(member_ids)}
        if len(cluster['members'])>1:
            item['merged_from']=[groups[index]['id'] for index in cluster['members']]
            item['merge_scores']=dict(cluster['scores'])
        merged.append(item)
    method={'merge_type':'group-aggregate TF-IDF cosine against immutable anchor','merge_rounds':2,'merge_threshold':threshold,
            'merge_input':'union of member tokens (normalized_title + normalized_summary)',
            'merge_anchor':'first group in id order, immutable','merge_comparisons':comparisons,
            'normalization':NORMALIZATION_VERSION,'tokenizer':TOKENIZER_VERSION}
    return merged,method
