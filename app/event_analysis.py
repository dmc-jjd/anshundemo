"""Local event matches -> model adjudication -> genuinely uncertain human cases."""
from __future__ import annotations
from .agent import get_prompt
from collections import Counter,defaultdict
from typing import Literal,Annotated
import asyncio,copy,hashlib,json,re
from pydantic import BaseModel,Field,ValidationError
from .model_client import invoke_agent
from .tool_executor import RunContext

class MergeAnswer(BaseModel):
    id:str
    decision:Literal['same','different','uncertain']
    reason:str=Field(min_length=1)
class MergeBatch(BaseModel):
    items:list[MergeAnswer]
class Classification(BaseModel):
    id:str
    category:str|None=None
    status:Literal['classified','uncertain']
    reason:str=Field(min_length=1)
class ClassificationBatch(BaseModel):
    items:list[Classification]
class BriefComplete(BaseModel):
    model_config={'str_strip_whitespace':True}
    id:str
    status:Literal['complete']
    summary:str=Field(min_length=15,max_length=35,description='15至35字，主语加事件行为，加有来源依据的后果；不要泛写引起关注。')
    source_refs:list[str]=Field(min_length=1)
    reason:str=''
class BriefUncertain(BaseModel):
    model_config={'str_strip_whitespace':True}
    id:str
    status:Literal['uncertain']
    summary:Literal['']=''
    source_refs:list[str]=Field(default_factory=list)
    reason:str=Field(min_length=1)
class BriefBatch(BaseModel):
    items:list[Annotated[BriefComplete|BriefUncertain,Field(discriminator='status')]]

class ConsolidatedGroup(BaseModel):
    model_config={'extra':'forbid'}
    group_ids:list[str]=Field(min_length=1,description='只填写输入候选中的事件ID，例如 event-103。不得填写标题。组代表由程序确定。')
class UncertainRelation(BaseModel):
    source_group:str
    target_group:str
    reason:str=Field(min_length=1)
class Consolidation(BaseModel):
    groups:list[ConsolidatedGroup]
    uncertain_pairs:list[UncertainRelation]=Field(default_factory=list)

def validate_consolidation(response,pool_ids,cannot_merge=()):
    covered=[gid for group in response.groups for gid in group.group_ids]
    missing=sorted(set(pool_ids)-set(covered));extra=sorted(set(covered)-set(pool_ids))
    duplicate=sorted(gid for gid,count in Counter(covered).items() if count>1)
    if missing or extra or duplicate:
        raise ValueError(json.dumps({'code':'consolidation_must_cover_exact_pool','missing':missing,'extra':extra,'duplicate':duplicate}))
    partition={gid:index for index,group in enumerate(response.groups) for gid in group.group_ids}
    if any(a in partition and b in partition and partition[a]==partition[b] for a,b in cannot_merge):raise ValueError('human_distinct_event_decision_must_be_preserved')
    if any(p.source_group not in partition or p.target_group not in partition or partition[p.source_group]==partition[p.target_group] for p in response.uncertain_pairs):
        raise ValueError('uncertain_pairs_must_reference_known_groups_in_different_partitions')

def negative_ranking(groups,records,limit=10):
    by_id={r['id']:r for r in records};result=[]
    for group in groups:
        negative_ids=[rid for rid in group['member_ids'] if by_id[rid].get('sentiment')=='负面'
                      and str(by_id[rid].get('warning','')).strip() in ('是','已预警','1','true','TRUE','预警')]
        if negative_ids:
            result.append({'id':group['id'],'negative_ids':negative_ids,'negative_count':len(negative_ids),
                'negative_warning_count':len(negative_ids),
                'representative_id':negative_ids[0],
                'fingerprint':hashlib.sha256(json.dumps(sorted(negative_ids)).encode()).hexdigest()})
    return sorted(result,key=lambda r:(-r['negative_count'],r['id']))[:limit]

async def analyse_events(deps,task_id):
    from .tool import CLUSTER_TERMS
    store=deps.store;state=store.get_task(task_id)
    local=store.get_artifact(state.result_refs['group_events'])
    records=store.get_artifact(local['source_records_ref'])['records'];by_id={r['id']:r for r in records}
    source_key=state.result_refs['group_events']
    checkpoint=store.get_artifact(state.result_refs['event_analysis_checkpoint']) if state.result_refs.get('event_analysis_checkpoint') else {}
    if checkpoint.get('source_key')!=source_key:checkpoint={'source_key':source_key,'merges':{},'classes':{},'briefs':{}}
    rules_hash=hashlib.sha256(json.dumps(CLUSTER_TERMS,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if checkpoint.get('classification_rules_hash') not in (None,rules_hash):checkpoint['classes']={}
    checkpoint['classification_rules_hash']=rules_hash
    # Preserve previous evidence and decisions, but regenerate summaries violating the new rule.
    for key,brief in list(checkpoint['briefs'].items()):
        if brief['status']=='complete' and not 15<=len(brief['summary'].strip())<=35:
            del checkpoint['briefs'][key]
    ctx=RunContext(store,task_id,model_adapter=deps.model_adapter)
    failures=[]
    # 分阶段独立失败预算：一个阶段失败不阻断后续阶段（merge 失败不再连带跳过 classification/summaries）。
    merge_failures=0; top10_failures=0; class_failures=0; summary_failures=0
    def evidence(ids,limit=3):
        ordered=sorted(ids,key=lambda rid:len(by_id[rid].get('summary','')),reverse=True)[:limit]
        return [{'ref':rid,'title':by_id[rid]['title'],'summary':by_id[rid].get('summary','')[:650],
                 'published':by_id[rid].get('published','')} for rid in ordered]
    def persist(stage,completed):
        latest=store.get_task(task_id)
        latest.result_refs['event_analysis_checkpoint']=store.put_artifact(task_id,'event_analysis_checkpoint',checkpoint)
        latest.metadata['analysis_stage']=stage;store.put_task(latest,latest.revision)
        store.append_event(task_id,{'type':'event_analysis_progress','stage':stage,'completed':completed})
    async def ask(role,payload,model,expected):
        response=await invoke_agent(role,payload,model,ctx)
        if len(response.items)!=len(expected) or {x.id for x in response.items}!=set(expected):raise ValueError('model_must_cover_exact_batch')
        return response.items
    # Rebuild from immutable local output plus validated previous decisions.
    groups={g['id']:{**g,'member_ids':list(g['member_ids'])} for g in local['groups']};parent={key:key for key in groups}
    previous=store.get_artifact(state.result_refs['event_analysis']) if state.result_refs.get('event_analysis') else {}
    def root(key):
        while parent[key]!=key:key=parent[key]
        return key
    ambiguities=[]
    remaining=list(local.get('borderline_candidates',[]))
    snapshot=checkpoint.get('merge_snapshot')
    if not snapshot and previous.get('source_key')==source_key and not any(f.get('stage')=='merge_judgment' for f in previous.get('failures',[])):
        # Migrate an older completed merge stage without repeating successful provider calls.
        positions={rid:g['id'] for g in previous['groups'] for rid in g['member_ids']}
        if set(positions)==set(local['all_record_ids']):
            for group in previous['groups']:groups[group['id']]=group
            parent={g['id']:positions[g['representative_id']] for g in local['groups']}
            snapshot={'groups':groups,'parent':parent,'remaining':[],'ambiguities':previous.get('merge_ambiguities',[])}
    if snapshot:
        groups=copy.deepcopy(snapshot['groups']);parent=dict(snapshot['parent']);remaining=list(snapshot['remaining']);ambiguities=copy.deepcopy(snapshot['ambiguities'])
    def apply_merge(pair,source,target,answer):
        a,b=groups[source],groups[target]
        if answer['decision']=='same':
            b['member_ids'].extend(a['member_ids']);parent[source]=target
        elif answer['decision']=='uncertain':
            ambiguities.append({'id':pair['id'],'source_id':a['representative_id'],'target_id':b['representative_id'],
                                'source_evidence':evidence([a['representative_id']]),'target_evidence':evidence([b['representative_id']]),
                                'score':pair['score'],'reason':answer['reason']})
    while remaining and merge_failures<3:
        batch=[];deferred=[];used_sources=set();used_targets=set()
        for pair in remaining:
            source,target=root(pair['source_group']),root(pair['target_group'])
            if source==target:continue
            key=f'{pair["id"]}:{source}:{target}'
            cached=checkpoint['merges'].get(key)
            if cached:
                if batch:deferred.append(pair)
                else:apply_merge(pair,source,target,cached)
                continue
            if len(batch)>=48 or source in used_sources or source in used_targets or target in used_sources:
                deferred.append(pair);continue
            batch.append((pair,source,target,key));used_sources.add(source);used_targets.add(target)
        if batch:
            async def judge_chunk(chunk):
                try:
                    answers=await ask('event_judge',{'instruction':get_prompt('event_judge.pairs'),
                        'pairs':[{'id':key,'vector_score':pair['score'],'source':evidence([groups[source]['representative_id']]),
                                  'target':evidence([groups[target]['representative_id']])} for pair,source,target,key in chunk]},MergeBatch,[x[3] for x in chunk])
                    return chunk,answers,None
                except Exception as exc:return chunk,[],{'stage':'merge_judgment','error':type(exc).__name__}
            results=await asyncio.gather(*(judge_chunk(batch[i:i+12]) for i in range(0,len(batch),12)))
            for chunk,answers,error in results:
                if error:
                    failures.append(error);merge_failures+=1;deferred.extend(x[0] for x in chunk)
                else:
                    indexed={a.id:a.model_dump() for a in answers};checkpoint['merges'].update(indexed)
                    for pair,source,target,key in chunk:apply_merge(pair,source,target,indexed[key])
        remaining=deferred
        checkpoint['merge_snapshot']=copy.deepcopy({'groups':groups,'parent':parent,'remaining':remaining,'ambiguities':ambiguities})
        persist('merge_judgment',len(checkpoint['merges']))
    if not remaining:
        checkpoint['merge_snapshot']=copy.deepcopy({'groups':groups,'parent':parent,'remaining':[],'ambiguities':ambiguities})
    final_groups=[g for key,g in groups.items() if root(key)==key]
    # A title/lexical retrieval miss must not leave duplicate events in the published TOP10.
    checkpoint.setdefault('top10_consolidations',{})
    for iteration in range(3):
        if top10_failures>=3:break
        pool=negative_ranking(final_groups,records,30)
        if len(pool)<2:break
        signature=hashlib.sha256(json.dumps([(r['id'],r['fingerprint']) for r in pool]).encode()).hexdigest()
        answer=checkpoint['top10_consolidations'].get(signature)
        if answer is None:
            validation_error=None;last_response=None
            record_groups={rid:group['id'] for group in final_groups for rid in group['member_ids']}
            cannot_merge=[(record_groups[a],record_groups[b]) for a,b in local.get('human_distinct_pairs',[]) if a in record_groups and b in record_groups]
            for attempt in range(2):
                try:
                    payload={'instruction':get_prompt('event_judge.top10'),
                        'allowed_ids':[r['id'] for r in pool],
                        'human_confirmed_distinct_pairs':cannot_merge,
                        'events':[{'id':r['id'],'count':r['negative_warning_count'],'evidence':evidence(r['negative_ids'],2)} for r in pool]}
                    if validation_error:payload.update(previous_response=last_response,validation_error=validation_error,instruction=payload['instruction']+get_prompt('event_judge.repair'))
                    response=await invoke_agent('event_judge',payload,Consolidation,ctx)
                    last_response=response.model_dump()
                    checkpoint.setdefault('top10_review_attempts',[]).append({'signature':signature,'response':last_response})
                    validate_consolidation(response,payload['allowed_ids'],cannot_merge)
                    order={row['id']:index for index,row in enumerate(pool)}
                    answer={**last_response,'groups':[{**group,'representative':min(group['group_ids'],key=lambda key:order[key])} for group in last_response['groups']]}
                    checkpoint['top10_consolidations'][signature]=answer
                    persist('top10_deduplication',len(checkpoint['top10_consolidations']));break
                except Exception as exc:
                    validation_error=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
                    checkpoint.setdefault('top10_validation_errors',[]).append({'signature':signature,'error':validation_error})
                    persist('top10_validation_retry',attempt+1)
            if answer is None:
                failures.append({'stage':'top10_deduplication','error':validation_error});top10_failures+=1;break
        merged=0
        for partition in answer['groups']:
            target=root(partition['representative'])
            for gid in partition['group_ids']:
                source=root(gid)
                if source!=target:groups[target]['member_ids'].extend(groups[source]['member_ids']);parent[source]=target;merged+=1
        for index,pair in enumerate(answer.get('uncertain_pairs',[])):
            source,target=root(pair['source_group']),root(pair['target_group'])
            if source!=target:
                ambiguities.append({'id':f'top10-{signature[:12]}-{index}','source_id':groups[source]['representative_id'],
                    'target_id':groups[target]['representative_id'],'source_evidence':evidence([groups[source]['representative_id']]),
                    'target_evidence':evidence([groups[target]['representative_id']]),'reason':pair['reason']})
        final_groups=[g for key,g in groups.items() if root(key)==key]
        if not merged:break
    final_positions={rid:g['id'] for g in final_groups for rid in g['member_ids']}
    human_distinct={frozenset((final_positions[a],final_positions[b])) for a,b in local.get('human_distinct_pairs',[]) if a in final_positions and b in final_positions}
    ambiguities=list({(case['source_id'],case['target_id']):case for case in ambiguities
                      if final_positions[case['source_id']]!=final_positions[case['target_id']]
                      and frozenset((final_positions[case['source_id']],final_positions[case['target_id']])) not in human_distinct}.values())
    fingerprints=checkpoint.setdefault('classification_members',{g['id']:hashlib.sha256(json.dumps(sorted(g['member_ids'])).encode()).hexdigest() for g in previous.get('groups',[])})
    for group in final_groups:
        fingerprint=hashlib.sha256(json.dumps(sorted(group['member_ids'])).encode()).hexdigest()
        if fingerprints.get(group['id']) not in (None,fingerprint):checkpoint['classes'].pop(group['id'],None)
        fingerprints[group['id']]=fingerprint
    local_classes={};pending=[];class_reasons={};manual_conflicts={}
    for group in final_groups:
        gid=group['id'];members=[by_id[rid] for rid in group['member_ids']]
        human_categories={local.get('human_category_overrides',{}).get(rid) for rid in group['member_ids']}
        human_categories.discard(None)
        if len(human_categories)==1:
            local_classes[gid]=next(iter(human_categories));class_reasons[gid]='人工明确指定的事件分类';continue
        if len(human_categories)>1:
            manual_conflicts[gid]='合并后的事件包含不同的人工指定分类：'+'、'.join(sorted(human_categories))
            continue
        source_categories=Counter(r.get('category') for r in members if r.get('category') in CLUSTER_TERMS)
        text=' '.join(r['title']+' '+r.get('summary','')[:600] for r in members[:3])
        scores={label:sum(text.count(word) for word in terms) for label,terms in CLUSTER_TERMS.items()}
        best=max(scores,key=scores.get);high=scores[best]
        if len(source_categories)==1:
            local_classes[gid]=next(iter(source_categories));class_reasons[gid]='来源已有有效分类'
        elif high>0 and list(scores.values()).count(high)==1:
            local_classes[gid]=best;class_reasons[gid]='本地分类词命中：'+ '、'.join(w for w in CLUSTER_TERMS[best] if w in text)
        elif gid not in checkpoint['classes']:pending.append(group)
    async def classify_batch(batch):
        payload={'instruction':get_prompt('event_classifier.classify'),
            'categories':list(CLUSTER_TERMS)+['其他'],
            'events':[{'id':g['id'],'evidence':evidence(g['member_ids'])} for g in batch]}
        feedback=None; error_name=''
        for attempt in range(3):
            try:
                if feedback:payload['correction_errors']=feedback
                answers=await ask('event_classifier',payload,ClassificationBatch,[g['id'] for g in batch])
                for answer in answers:
                    if answer.status=='classified' and answer.category not in set(CLUSTER_TERMS)|{'其他'}:raise ValueError('unknown_category')
                return answers,None
            except ValidationError as exc:
                error_name='ValidationError'
                feedback=['.'.join(map(str,e['loc']))+': '+e['msg'] for e in exc.errors(include_url=False,include_input=False)]
                store.append_event(task_id,{'type':'classification_output_correction','attempt':attempt+1,'errors':feedback})
            except ValueError as exc:
                error_name='ValueError'
                feedback=[str(exc)]
                store.append_event(task_id,{'type':'classification_output_correction','attempt':attempt+1,'errors':feedback})
            except Exception as exc:
                # 传输/模型不可用等错误不做输出纠偏，直接记失败并交由上层汇总。
                return [],{'stage':'classification','ids':[g['id'] for g in batch],'error':type(exc).__name__}
        return [],{'stage':'classification','ids':[g['id'] for g in batch],'error':error_name or 'classify_failed'}
    batches=[pending[offset:offset+12] for offset in range(0,len(pending),12)]
    for offset in range(0,len(batches),4):
        if class_failures>=3:break
        results=await asyncio.gather(*(classify_batch(batch) for batch in batches[offset:offset+4]))
        for answers,error in results:
            if error:failures.append(error);class_failures+=1
            else:
                checkpoint['classes'].update({a.id:a.model_dump() for a in answers})
                persist('classification',len(checkpoint['classes']))
    themes=defaultdict(list);classification_issues=[]
    for group in final_groups:
        gid=group['id'];answer=checkpoint['classes'].get(gid)
        if gid in manual_conflicts:
            category='待人工分类';class_reasons[gid]=manual_conflicts[gid]
            classification_issues.append({'event_id':gid,'member_ids':group['member_ids'],'reason':manual_conflicts[gid]})
        elif gid in local_classes:category=local_classes[gid]
        elif answer and answer['status']=='classified':category=answer['category'];class_reasons[gid]=answer['reason']
        elif answer:
            category='待人工分类';class_reasons[gid]=answer['reason']
            classification_issues.append({'event_id':gid,'member_ids':group['member_ids'],'reason':answer['reason']})
        else:category='模型尚未处理';class_reasons[gid]='等待模型完成分类，不属于人工待办'
        themes[category].extend(group['member_ids'])
    ranking=negative_ranking(final_groups,records)
    for offset in range(0,len(ranking),5):
        if summary_failures>=3:break
        batch=[item for item in ranking[offset:offset+5] if item['fingerprint'] not in checkpoint['briefs']]
        if not batch:continue
        try:
            answers=await ask('event_summarizer',{'instruction':get_prompt('event_summarizer.summary'),
                'events':[{'id':item['fingerprint'],'evidence':evidence(item['negative_ids'],4)} for item in batch]},BriefBatch,[item['fingerprint'] for item in batch])
            for answer in answers:
                item=next(x for x in batch if x['fingerprint']==answer.id)
                if answer.status=='complete':
                    source=' '.join(by_id[rid]['title']+' '+by_id[rid].get('summary','') for rid in item['negative_ids'])
                    if not answer.summary.strip() or not answer.source_refs or not set(answer.source_refs)<=set(item['negative_ids']):raise ValueError('invalid_brief_sources')
                    if any(n not in source for n in re.findall(r'\d+(?:\.\d+)?',answer.summary)):raise ValueError('unsupported_number_in_brief')
            checkpoint['briefs'].update({a.id:a.model_dump() for a in answers});persist('top10_summaries',len(checkpoint['briefs']))
        except Exception as exc:failures.append({'stage':'top10_summaries','error':type(exc).__name__});summary_failures+=1
    top10=[]
    for rank,item in enumerate(ranking,1):
        brief=checkpoint['briefs'].get(item['fingerprint'])
        top10.append({**item,'rank':rank,'summary':brief['summary'] if brief and brief['status']=='complete' else '',
                      'status':brief['status'] if brief else 'pending_model',
                      'source_refs':brief['source_refs'] if brief else [],'reason':(brief.get('reason') or (brief['summary'] if brief['status']=='uncertain' else '')) if brief else '模型尚未生成有效梗概'})
    pending_model=bool(failures or '模型尚未处理' in themes or any(x['status']=='pending_model' for x in top10))
    result={'groups':final_groups,'all_record_ids':local['all_record_ids'],'source_key':source_key,
        'merge_ambiguities':ambiguities,'classification_issues':classification_issues,'classification_reasons':class_reasons,
        'theme_groups':[{'candidate_theme':label,'member_ids':members} for label,members in themes.items()],
        'top10':top10,'top10_rule':{'scope':'negative_and_warning','unit':'deduplicated_event',
            'ranking':'negative_warning_member_count','direction':'descending','display':'serious_concise_summary','summary_min_chars':15,'summary_max_chars':35},
        'pending_model':pending_model,'failures':failures,
        'counts':{'local_event_groups':len(local['groups']),'model_event_groups':len(final_groups),
                  'merge_cases':len(checkpoint['merges']),'human_merge_cases':len(ambiguities),
                  'locally_classified_events':len(local_classes),'events_requiring_model_classification':sum(g['id'] not in local_classes for g in final_groups),
                  'human_summary_cases':sum(row['status']=='uncertain' for row in top10),
                  'human_classification_events':len(classification_issues),'human_classification_records':sum(len(x['member_ids']) for x in classification_issues)}}
    persist('complete' if not pending_model else 'pending_model',len(final_groups))
    latest=store.get_task(task_id);ref=store.put_artifact(task_id,'event_analysis',result);latest.result_refs['event_analysis']=ref
    latest.metadata['analysis_pending']=pending_model;store.put_task(latest,latest.revision)
    return result
