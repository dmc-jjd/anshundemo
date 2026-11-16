"""Whole-template semantic review: every base block goes to the model in one call.

Why one shot, and not three-block batches: a three-block window cut straight
through a numbered list (last item + next subsection heading + its lead
paragraph). The same model then described one positional slot three different
ways in different batches, and items 1—3 kept their ordinal as fixed text while
items 4—5 swallowed it into the field value. With the whole report in view the
model can name positions consistently, and the program's structural list
compiler sees the run as one unit.

The trade-off is deliberate: there is no per-batch resume point. A failed pass
is retried whole (three semantic rounds under the same contract). A truncated
response raises ``TemplateResponseTruncated`` instead of leaving a half-built
candidate template behind, so the user is told to retry the whole thing rather
than to expect a partial resume.

``template_analyst.batch`` keeps the single-pass output contract, and the
per-field size budget lives in ``template_analyst.template``: one response must
fit ``core/model_client``'s 24000-token cap, so the prompt keeps field text
terse instead of asking for commentary.
"""
from .agent import get_prompt
import time
from pydantic import ValidationError
from .model_client import invoke_agent
from .state import RawTemplateResult
from .template_validation import collect_errors,batch_schema
from .timing import stamp,elapsed

MAX_TEMPLATE_ROUNDS=3
FULL_TEMPLATE_KEY='all'


class ManualTemplateReviewRequired(RuntimeError):
    pass


class TemplateOutputUnavailable(RuntimeError):
    pass


class TemplateResponseTruncated(RuntimeError):
    """模型输出被截断：整份重试，绝不返回半成品候选。"""


def _last_finish_reason(store,task_id):
    """最近一次模型调用的 finish_reason（截断归因用；桩不写事件时返回 None）。"""
    try:events=store.events(task_id)
    except Exception:return None
    for event in reversed(events):
        if event.get('type')=='model_call':return event.get('finish_reason')
    return None


def _truncated_json(exc):
    """ValidationError 是否由 JSON 被截断引起（而不是字段内容不合法）。"""
    if not isinstance(exc,ValidationError):return None
    for issue in exc.errors(include_input=False,include_url=False):
        message=str(issue.get('msg') or '')
        if (issue.get('type')=='json_invalid' or 'EOF while parsing' in message
                or 'Unterminated string' in message):
            return message or 'json_invalid'
    return None


def _truncation_error(store,task_id,detail):
    finish_reason=_last_finish_reason(store,task_id) or 'unknown'
    return ('template_response_truncated: 模型输出被截断（finish_reason=%s），JSON 不完整（%s）。'
            '本次为全量单次研判，没有分批断点，不能续跑：请整份重试，或提高 max_tokens、'
            '压缩字段说明后重试。'%(finish_reason,detail[:160]))


async def review_batches(store,state,ctx,packet,comparison_ref):
    """Send every base block in one model call; the name is the workflow entry point."""
    indexes=[b['index'] for b in packet['source_reports'][0]['blocks']]
    batches=state.metadata.setdefault('template_batches',{})
    checkpoints=state.metadata.setdefault('template_review_checkpoints',{})
    if set(batches)!={FULL_TEMPLATE_KEY}:
        # 旧的三块分批台账与新执行模型不可互操作：整份重来，不把旧批次拼成新候选。
        batches.clear();checkpoints.clear()
    batch=batches.setdefault(FULL_TEMPLATE_KEY,{'targets':indexes,'rounds':[],'status':'pending'})
    batch['targets']=indexes

    def persist():store.put_task(state,state.revision)

    if FULL_TEMPLATE_KEY in checkpoints:
        raw=store.get_artifact(checkpoints[FULL_TEMPLATE_KEY])
        if not collect_errors(raw,packet,comparison_ref):
            batch['status']='passed';persist()
            return raw,[checkpoints[FULL_TEMPLATE_KEY]]
        checkpoints.pop(FULL_TEMPLATE_KEY)
    if batch['status']=='human_required':raise ManualTemplateReviewRequired(FULL_TEMPLATE_KEY)
    if batch['status'] in ('unusable','truncated'):
        batch.setdefault('archived_rounds',[]).extend(batch['rounds'])
        batch['rounds']=[];batch['status']='pending'
    rounds=batch['rounds']
    while len([r for r in rounds if r['status'] in ('invalid','passed')])<MAX_TEMPLATE_ROUNDS:
        prior=[r for r in rounds if r['status']=='invalid']
        number=len(prior)+1
        request={'task_scope':{'target_blocks':indexes,'round':number,'maximum_rounds':MAX_TEMPLATE_ROUNDS,
            'instruction':get_prompt('template_analyst.batch')},
            **packet,'target_blocks':indexes}
        if prior:
            request['repair']={'rejected_response':store.get_artifact(prior[-1]['response_ref']) if prior[-1].get('response_ref') else None,
                'errors':prior[-1]['errors'],
                'history':[{'round':r['number'],'errors':r['errors']} for r in prior],
                'instruction':get_prompt('template_analyst.repair')}
        entry={'number':number,'started_at':stamp(),'status':'running','errors':[],
               'request_ref':store.put_artifact(state.id,'template_round_input',request)}
        rounds.append(entry);batch['status']='running';persist()
        # 进度口径=已覆盖的目标块数：全量单次研判在开始与通过各报一次，completed 不会超过 total。
        store.append_event(state.id,{'type':'template_model_progress','mode':'single_shot','stage':'started',
            'completed':0,'total':len(indexes),'source_count':len(packet['source_reports'])})
        store.append_event(state.id,{'type':'template_round_started','batch':FULL_TEMPLATE_KEY,'round':number,
            'maximum_rounds':MAX_TEMPLATE_ROUNDS})
        call_started=time.perf_counter()
        try:
            answer=await invoke_agent('template_analyst',request,RawTemplateResult,ctx,response_schema=batch_schema(indexes))
            entry['model_elapsed_ms']=round((time.perf_counter()-call_started)*1000)
            raw=answer.root
            entry['response_ref']=store.put_artifact(state.id,'template_model_response',raw)
            validation_started=time.perf_counter()
            issues=collect_errors(raw,packet,comparison_ref)
            entry['validation_elapsed_ms']=round((time.perf_counter()-validation_started)*1000)
        except ValidationError as exc:
            entry['model_elapsed_ms']=round((time.perf_counter()-call_started)*1000)
            truncated=_truncated_json(exc)
            if truncated:
                message=_truncation_error(store,state.id,truncated)
                entry.update(status='truncated',ended_at=stamp(),
                             errors=[{'code':'template_response_truncated','message':message}])
                entry['elapsed_ms']=elapsed(entry['started_at'],entry['ended_at'])
                batch['status']='truncated';persist()
                store.append_event(state.id,{'type':'template_response_truncated','batch':FULL_TEMPLATE_KEY,
                    'finish_reason':_last_finish_reason(store,state.id),'detail':truncated[:400]})
                raise TemplateResponseTruncated(message) from exc
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
            checkpoints[FULL_TEMPLATE_KEY]=entry['response_ref'];batch['status']='passed';persist()
            store.append_event(state.id,{'type':'template_model_progress','mode':'single_shot','stage':'finished',
                'completed':len(indexes),'total':len(indexes),'source_count':len(packet['source_reports'])})
            store.append_event(state.id,{'type':'template_round_passed','batch':FULL_TEMPLATE_KEY,'round':number,
                'elapsed_ms':entry['elapsed_ms']})
            return raw,[entry['response_ref']]
        batch['status']='repairing';persist()
        store.append_event(state.id,{'type':'template_validation_error','batch':FULL_TEMPLATE_KEY,'round':number,
            'errors':issues,'response_ref':entry.get('response_ref'),'elapsed_ms':entry['elapsed_ms']})
    reviewable=any(r.get('response_ref') and isinstance(store.get_artifact(r['response_ref']).get('blocks'),list)
                   and store.get_artifact(r['response_ref'])['blocks'] for r in rounds)
    batch['status']='human_required' if reviewable else 'unusable';persist()
    if reviewable:raise ManualTemplateReviewRequired(FULL_TEMPLATE_KEY)
    raise TemplateOutputUnavailable('三轮全量研判仍未取得可审阅的模板结构；本次为全量单次研判，'
                                    '没有分批断点、不支持续跑，请整份重试。')
