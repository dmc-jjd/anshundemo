"""BGE >=75% -> semantic LLM -> explicit uncertainty for human review.

The caller supplies units: individual records with dedup off, final event groups
with dedup on. No dictionary acceptance and no event grouping happen here.
"""
from __future__ import annotations

import asyncio
from collections import Counter,defaultdict
import hashlib
import json
import math
from typing import Literal

from pydantic import BaseModel,Field,ValidationError

from core.classify.local_bge import deployment_identity,predict_bge


class Classification(BaseModel):
    id:str
    category:str|None=None
    status:Literal['classified','uncertain']
    reason:str=Field(min_length=1)


class ClassificationBatch(BaseModel):
    items:list[Classification]


def _hash(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


async def classify_units(deps,task_id,units,records,overrides=None):
    from core.agent import get_prompt
    from core.model_client import invoke_agent,TaskPaused
    from core.tool_executor import RunContext
    from core.tools import vocabulary
    from core.manifest import load_manifest
    from core import paths

    store=deps.store
    labels=list(vocabulary.cluster_terms())
    config=load_manifest(paths.package_dir()).features.get('event_classification') or {}
    bge_config=next((s for s in config.get('stages',[]) if s.get('kind')=='bge'),{})
    llm_config=next((s for s in config.get('stages',[]) if s.get('kind')=='llm'),{})
    bge_enabled=bge_config.get('enabled',True) is True
    llm_enabled=llm_config.get('enabled',True) is True
    threshold=float(bge_config.get('confidence_threshold',.75))
    if not math.isfinite(threshold) or not 0<=threshold<=1:raise ValueError('invalid_bge_threshold')
    prompt=get_prompt('event_classifier.classify')
    policy={'version':1,'labels':labels,'threshold':threshold,'bge_enabled':bge_enabled,
            'llm_enabled':llm_enabled,'deployment':deployment_identity(),'prompt':prompt}
    unit_ids=[str(u['id']) for u in units]
    record_ids=[r['id'] for r in records]
    members=[rid for u in units for rid in u['member_ids']]
    if (len(unit_ids)!=len(set(unit_ids)) or len(record_ids)!=len(set(record_ids))
        or len(members)!=len(set(members)) or set(members)!=set(record_ids)
        or any(not u['member_ids'] for u in units)):
        raise ValueError('classification_units_must_cover_records_once')
    state=store.get_task(task_id)
    checkpoint=store.get_artifact(state.result_refs['semantic_classification_checkpoint']) if state.result_refs.get('semantic_classification_checkpoint') else {}
    if checkpoint.get('policy')!=_hash(policy):checkpoint={'policy':_hash(policy),'units':{}}
    saved=checkpoint['units'];by_id={r['id']:r for r in records};overrides=overrides or {}
    rows={};inputs=[]

    def persist(stage):
        latest=store.get_task(task_id)
        latest.result_refs['semantic_classification_checkpoint']=store.put_artifact(task_id,'semantic_classification_checkpoint',checkpoint)
        store.put_task(latest,latest.revision)
        store.append_event(task_id,{'type':'semantic_classification_progress','stage':stage,
            'completed':sum(x.get('status') in ('classified','uncertain') for x in rows.values()),'total':len(units)})

    for unit in units:
        members=[by_id[rid] for rid in unit['member_ids']]
        # The longest evidence is preferred, deterministically; IDs are never inferred from titles.
        chosen=sorted(members,key=lambda r:(-len(r.get('summary','')),str(r['id'])))[:3]
        evidence=[{'ref':r['id'],'title':r['title'],'summary':r.get('summary','')[:650]} for r in chosen]
        human={overrides[r['id']] for r in members if overrides.get(r['id'])}
        signature=_hash({'policy':checkpoint['policy'],'members':sorted(unit['member_ids']),
                         'evidence':evidence,'human':sorted(human)})
        key=str(unit['id']);prior=saved.get(key)
        if prior and prior.get('signature')==signature:
            row=dict(prior)
        else:
            row={'id':key,'member_ids':list(unit['member_ids']),'signature':signature,
                 'category':None,'source':'unresolved','status':'pending_model','reason':'等待模型完成分类'}
        row['evidence']=evidence
        if human:
            row.update(category=next(iter(human)) if len(human)==1 else None,
                source='human_override',status='classified' if len(human)==1 else 'uncertain',
                reason='保留人工指定分类' if len(human)==1 else '合并后的事件包含不同人工分类，需人工处理')
        rows[key]=row;saved[key]=row
        bge_retryable=row.get('bge',{}).get('reason','').startswith('bge_')
        if row['status']=='pending_model' and ('bge' not in row or bge_retryable):
            inputs.append({'id':key,'title':chosen[0]['title'] if chosen else '',
                           'summary':'\n'.join(r.get('summary','')[:650] for r in chosen)})
    if store.get_task(task_id).cancel_requested:raise TaskPaused('task_paused')
    if inputs and bge_enabled:
        store.append_event(task_id,{'type':'classification_stage','stage':'bge','status':'started','count':len(inputs),'threshold':threshold})
        try:verdicts=await asyncio.to_thread(predict_bge,inputs)
        except Exception as exc:
            from core.classify import Verdict
            verdicts=[Verdict(r['id'],reason='bge_unavailable:'+type(exc).__name__) for r in inputs]
        expected={r['id'] for r in inputs};counts=Counter(v.record_id for v in verdicts)
        verdict_by_id={v.record_id:v for v in verdicts if v.record_id in expected and counts[v.record_id]==1}
        for record in inputs:
            row=rows[record['id']];v=verdict_by_id.get(record['id'])
            confidence=v.confidence if v and math.isfinite(v.confidence) and 0<=v.confidence<=1 else None
            row['bge']={'category':v.category if v else None,'confidence':confidence,
                        'reason':v.reason if v else 'bge_missing_or_duplicate_result',
                        'model':dict(v.model) if v else {}}
            if v and v.source=='bge' and not v.borderline and confidence is not None and confidence>=threshold and v.category in labels:
                row.update(category=v.category,confidence=confidence,source='bge',status='classified',reason='BGE 分类头置信度达到阈值')
        persist('bge')
        degraded=sum(bool(r.get('bge',{}).get('reason','').startswith('bge_')) for r in rows.values())
        store.append_event(task_id,{'type':'classification_stage','stage':'bge','status':'finished',
            'accepted':sum(r['source']=='bge' for r in rows.values()),'degraded':degraded,'deployment':deployment_identity()})
    ctx=RunContext(store,task_id,model_adapter=deps.model_adapter)
    pending=[r for r in rows.values() if r['status']=='pending_model'];failures=[]
    # Bounded batches checkpoint independently. Provider failures stay pending, never become human uncertainty.
    batch_size=20
    batch_total=(len(pending)+batch_size-1)//batch_size
    for start in range(0,len(pending) if llm_enabled else 0,batch_size):
        if len(failures)>=3:break
        if store.get_task(task_id).cancel_requested:raise TaskPaused('task_paused')
        batch=pending[start:start+batch_size]
        payload={'instruction':prompt,'categories':labels,
            'events':[{'id':r['id'],'evidence':r['evidence']} for r in batch]}
        for attempt in range(3):
            try:
                response=await invoke_agent('event_classifier',payload,ClassificationBatch,ctx)
                answers=response.items
                if len(answers)!=len(batch) or {r.id for r in answers}!={r['id'] for r in batch}:raise ValueError('model_must_cover_exact_batch')
                if any(not a.reason.strip() or (a.status=='classified' and a.category not in labels) for a in answers):raise ValueError('invalid_classification_category_or_reason')
                for answer in answers:
                    rows[answer.id].update(category=answer.category if answer.status=='classified' else None,
                        source='llm',status=answer.status,reason=answer.reason)
                persist('llm')
                store.append_event(task_id,{'type':'classification_batch_completed','total':len(pending),
                    'batch_index':start//batch_size+1,'batch_total':batch_total,'batch_size':len(batch)})
                break
            except TaskPaused:raise
            except (ValidationError,ValueError) as exc:
                payload['correction_errors']=['Output must cover all IDs once, use categories and nonempty reason.']
                store.append_event(task_id,{'type':'classification_output_correction','attempt':attempt+1,'error':type(exc).__name__})
                if attempt==2:failures.append({'stage':'classification','ids':[r['id'] for r in batch],'error':type(exc).__name__})
            except Exception as exc:
                failures.append({'stage':'classification','ids':[r['id'] for r in batch],'error':type(exc).__name__});break
    themes=defaultdict(list);issues=[];counts={'bge':0,'llm':0,'human':0,'pending_model':0,'human_override':0}
    for row in rows.values():
        if row['status']=='uncertain':
            label='待人工分类';counts['human']+=1
            issues.append({'event_id':row['id'],'member_ids':row['member_ids'],'reason':row['reason']})
        elif row['status']=='pending_model':label='模型尚未处理';counts['pending_model']+=1
        else:label=row['category'];counts[row['source']]+=1
        themes[label].extend(row['member_ids'])
    result={'items':list(rows.values()),'theme_groups':[{'candidate_theme':k,'member_ids':v} for k,v in themes.items()],
        'all_record_ids':[rid for u in units for rid in u['member_ids']],
        'classification_issues':issues,'classification_counts':counts,'threshold':threshold,
        'method':{'type':'bge_then_llm_then_human','threshold':threshold,'deployment':deployment_identity()},
        'pending_model':bool(counts['pending_model']),'failures':failures}
    persist('pending_model' if result['pending_model'] else 'complete')
    store.append_event(task_id,{'type':'semantic_classification_summary','counts':counts,'threshold':threshold,'pending_model':result['pending_model']})
    return result


async def analyse_records(deps,task_id):
    store=deps.store;state=store.get_task(task_id)
    source_ref=state.result_refs['filter_records:negative_or_warning']
    records=store.get_artifact(source_ref)['records']
    units=[{'id':r['id'],'member_ids':[r['id']]} for r in records]
    result=await classify_units(deps,task_id,units,records)
    result['source_records_ref']=source_ref
    ref=store.put_artifact(task_id,'semantic_classification',result)
    cluster_ref=store.put_artifact(task_id,'theme_clusters',{'groups':result['theme_groups'],
        'items':result['items'],'all_record_ids':result['all_record_ids'],'method':result['method']})
    state=store.get_task(task_id)
    state.result_refs.update(semantic_classification=ref,cluster_event_themes=cluster_ref)
    state.metadata['analysis_pending']=result['pending_model']
    store.put_task(state,state.revision)
    return result
