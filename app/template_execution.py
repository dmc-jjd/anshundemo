"""Three-round template repair with durable batch histories and a human gate."""
from .agent import get_prompt
import asyncio
import time
from pydantic import ValidationError
from .model_client import invoke_agent
from .state import RawTemplateResult
from .template_review import compile_review
from .template_validation import collect_errors,batch_schema
from .timing import stamp,elapsed

MAX_TEMPLATE_ROUNDS=3


class ManualTemplateReviewRequired(RuntimeError):
    pass


class TemplateOutputUnavailable(RuntimeError):
    pass


async def review_batches(store,state,ctx,packet,comparison_ref):
    checkpoints=state.metadata['template_review_checkpoints']
    batches=state.metadata.setdefault('template_batches',{})
    indexes=[b['index'] for b in packet['source_reports'][0]['blocks']]
    def persist():store.put_task(state,state.revision)

    async def run_batch(targets,key=None,initial=None):
        key=key or ','.join(map(str,targets))
        batch=batches.setdefault(key,{'targets':targets,'rounds':[],'status':'pending'})
        validate_targets=None if key=='all' else targets
        if key in checkpoints:
            raw=store.get_artifact(checkpoints[key])
            issues=collect_errors(raw,packet,comparison_ref,validate_targets)
            if not issues:
                batch['status']='passed';return checkpoints[key],raw
            initial=raw;checkpoints.pop(key)
        if batch['status']=='human_required':raise ManualTemplateReviewRequired(key)
        if batch['status']=='unusable':
            batch.setdefault('archived_rounds',[]).extend(batch['rounds'])
            batch['rounds']=[];batch['status']='pending'
        rounds=batch['rounds']
        if initial is not None and not rounds:
            issues=collect_errors(initial,packet,comparison_ref,validate_targets)
            at=stamp();ref=store.put_artifact(state.id,'template_model_response',initial)
            rounds.append({'number':1,'started_at':at,'ended_at':at,'elapsed_ms':0,'status':'invalid',
                           'response_ref':ref,'errors':issues,'origin':'assembled_candidate'})
        while len([r for r in rounds if r['status'] in ('invalid','passed')])<MAX_TEMPLATE_ROUNDS:
            prior=[r for r in rounds if r['status']=='invalid']
            number=len(prior)+1
            request={'task_scope':{'target_blocks':targets,'round':number,'maximum_rounds':MAX_TEMPLATE_ROUNDS,
                'instruction':get_prompt('template_analyst.batch')},
                **packet,'target_blocks':targets}
            if prior:
                request['repair']={'rejected_response':store.get_artifact(prior[-1]['response_ref']) if prior[-1].get('response_ref') else None,
                    'errors':prior[-1]['errors'],
                    'history':[{'round':r['number'],'errors':r['errors']} for r in prior],
                    'instruction':get_prompt('template_analyst.repair')}
            entry={'number':number,'started_at':stamp(),'status':'running','errors':[],
                   'request_ref':store.put_artifact(state.id,'template_round_input',request)}
            rounds.append(entry);batch['status']='running';persist()
            store.append_event(state.id,{'type':'template_round_started','batch':key,'round':number,'maximum_rounds':MAX_TEMPLATE_ROUNDS})
            call_started=time.perf_counter()
            try:
                answer=await invoke_agent('template_analyst',request,RawTemplateResult,ctx,response_schema=batch_schema(targets))
                entry['model_elapsed_ms']=round((time.perf_counter()-call_started)*1000)
                raw=answer.root
                entry['response_ref']=store.put_artifact(state.id,'template_model_response',raw)
                validation_started=time.perf_counter()
                issues=collect_errors(raw,packet,comparison_ref,validate_targets)
                entry['validation_elapsed_ms']=round((time.perf_counter()-validation_started)*1000)
            except ValidationError as exc:
                entry['model_elapsed_ms']=round((time.perf_counter()-call_started)*1000)
                raw=None
                issues=[{'code':'invalid_json','message':'模型未返回可读取的JSON对象。','actual':str(exc)[:400]}]
            except Exception as exc:
                entry['model_elapsed_ms']=round((time.perf_counter()-call_started)*1000)
                entry.update(status='transport_error',ended_at=stamp(),error_type=type(exc).__name__,error=str(exc)[:400])
                entry['elapsed_ms']=elapsed(entry['started_at'],entry['ended_at']);batch['status']='transport_error';persist()
                raise
            entry.update(status='invalid' if issues else 'passed',ended_at=stamp(),errors=issues)
            entry['elapsed_ms']=elapsed(entry['started_at'],entry['ended_at'])
            if not issues:
                checkpoints[key]=entry['response_ref'];batch['status']='passed';persist()
                store.append_event(state.id,{'type':'template_round_passed','batch':key,'round':number,'elapsed_ms':entry['elapsed_ms']})
                return entry['response_ref'],raw
            batch['status']='repairing';persist()
            store.append_event(state.id,{'type':'template_validation_error','batch':key,'round':number,
                'errors':issues,'response_ref':entry.get('response_ref'),'elapsed_ms':entry['elapsed_ms']})
        reviewable=any(r.get('response_ref') and isinstance(store.get_artifact(r['response_ref']).get('blocks'),list)
                       and store.get_artifact(r['response_ref'])['blocks'] for r in rounds)
        batch['status']='human_required' if reviewable else 'unusable';persist()
        if reviewable:raise ManualTemplateReviewRequired(key)
        raise TemplateOutputUnavailable('三轮后仍未取得可审阅的模板结构，请检查模型输出后重试。')

    combined={'summary':'','blocks':[],'fields':[],'unresolved_items':[]};refs=[]
    target_batches=[indexes[i:i+3] for i in range(0,len(indexes),3)]
    for offset in range(0,len(target_batches),3):
        outcomes=await asyncio.gather(*(run_batch(targets) for targets in target_batches[offset:offset+3]),return_exceptions=True)
        failures=[o for o in outcomes if isinstance(o,BaseException)]
        if failures:
            manual=next((o for o in failures if isinstance(o,ManualTemplateReviewRequired)),None)
            raise manual or failures[0]
        for ref,data in outcomes:
            refs.append(ref);combined['summary']+=data['summary']+'\n'
            for name in ('blocks','fields','unresolved_items'):combined[name].extend(data[name])
        store.append_event(state.id,{'type':'template_model_progress','completed':sum(len(v['targets']) for k,v in batches.items() if k!='all' and v['status'] in ('passed','human_corrected')),
                                    'total':len(indexes),'source_count':len(packet['source_reports'])})
    global_errors=collect_errors(combined,packet,comparison_ref)
    if global_errors or 'all' in batches:
        ref,combined=await run_batch(indexes,'all',combined);refs.append(ref)
    return combined,refs
