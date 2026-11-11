"""Automatic cosine grouping against an immutable representative, without chaining."""
from collections import Counter,defaultdict
from math import log,sqrt
import re

from . import vocabulary

def group_by_representative(records,threshold=None):
    if threshold is None:threshold=vocabulary.dedup_threshold()
    if not 0<threshold<=1:raise ValueError('similarity_threshold_must_be_between_zero_and_one')
    tokens=[]
    for record in records:
        text=re.sub(r'\s+',' ',record.get('title','')+' '+record.get('summary','')).lower()
        terms=[]
        for chunk in re.findall(r'[a-z0-9]+|[\u4e00-\u9fff]+',text):
            terms.extend([chunk[i:i+2] for i in range(len(chunk)-1)] if re.fullmatch(r'[\u4e00-\u9fff]+',chunk) and len(chunk)>1 else [chunk])
        tokens.append(Counter(terms))
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
            'method':{'type':'TF-IDF sparse cosine','input':'title + summary','threshold':threshold,
                      'representative':'first member, immutable','automatic':True,'comparisons':comparisons,
                      'model_candidate_floor':threshold*vocabulary.dedup_candidate_floor()}}
