"""三轮模板语义研判（同一角色 template_analyst，评审角色不拆分）。

轮次状态机（用户拍板的规则，逐字实现）：
  第 1 轮（初稿轮，必跑，不做完美判定）
      输入：3 篇报告 + 机器本地比对模板（packet.local_hypothesis）
      产出：模板稿 v1 + review_items（第一轮修改意见）
  第 2 轮（判定轮，必跑）
      输入：3 篇报告 + 机器模板 + v1 + 第一轮修改意见
      动作：a) prior_opinion_resolved 逐条核对第一轮意见是否全量改到位
            b) 按 6 条固定清单自审（提示词原文在 template_analyst.repair）
      完美条件（全部满足）：结构错误 0 且 重要=0 且 建议<3 且第一轮意见全量 resolved
        → 结束模型研判，当前模板为最终候选，交人工确认
        否则当前响应即模板稿 v2，进入第 3 轮
  第 3 轮（终审轮，仅第 2 轮不完美时执行）
      输入：前两轮模板与意见 + v2
      产出：最终模板 v3 + review_items（全部 advisory，人工可采纳也可忽略）
      无论完美与否都交人工确认；终审仍报出「重要」项 → 追加质量事故事件。

模型调用次数：最少 2（r1+r2 完美）、最多 3。非法 JSON 等硬失败按同一语义轮原地重试
（HARD_ATTEMPTS 次），不消耗语义轮次；截断立即抛 TemplateResponseTruncated；
传输错误立即上抛（与旧行为一致）。第 3 轮结构仍非法时走 ManualTemplateReviewRequired
人工异常研判兜底。

checkpoint 恢复：批次台账带 engine='three_round_v1' 标记，按已持久化的语义轮续跑
（r1 完跑 r2，r2 不完美则跑 r3），只有终态候选才走快速通道，绝不跳过 r2/r3。
"""
from .agent import get_prompt
import time
from pydantic import ValidationError
from .model_client import invoke_agent
from .state import RawTemplateResult
from .template_validation import collect_errors,batch_schema
from .timing import stamp,elapsed

MAX_TEMPLATE_ROUNDS=3
HARD_ATTEMPTS=3
FULL_TEMPLATE_KEY='all'
ENGINE='three_round_v1'
SEVERITY_IMPORTANT='重要'
SEVERITY_SUGGESTION='建议'
MAX_REVIEW_ITEMS=40

ROUND_STAGE={1:'first',2:'judge',3:'final'}
# 每轮装配哪条已注册提示词（名字不许以 _PROMPT/_INSTRUCTION 结尾：那是散落字面量的探测名）。
ROUND_INSTRUCTION_KEY={1:'template_analyst.batch',2:'template_analyst.repair',3:'template_analyst.advice'}


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
            '三轮研判均为整份模板输出，没有分批断点，不能续跑：请整份重试，或提高 max_tokens、'
            '压缩字段说明后重试。'%(finish_reason,detail[:160]))


def _template_part(raw):
    """结构校验/编译只认四个契约键；review_items 等研判扩展不进 TemplateReviewResult（extra=forbid）。"""
    if not isinstance(raw,dict):return {}
    return {key:raw[key] for key in ('summary','blocks','fields','unresolved_items') if key in raw}


def _review_items(raw):
    """清洗模型自报意见：非列表/非字典项丢弃；severity 非法值降级「建议」；数量封顶。

    返回 (items, normalized_count)；items 元素全是普通 dict，缺省键补默认值，保证旧工件可读。
    """
    values=raw.get('review_items') if isinstance(raw,dict) else None
    if not isinstance(values,list):return [],0
    items=[];normalized=0
    for value in values[:MAX_REVIEW_ITEMS]:
        if not isinstance(value,dict):continue
        severity=value.get('severity')
        if severity not in (SEVERITY_IMPORTANT,SEVERITY_SUGGESTION):
            severity=SEVERITY_SUGGESTION;normalized+=1
        def text(key):
            v=value.get(key)
            return v if isinstance(v,str) else ''
        items.append({'severity':severity,'checklist':text('checklist'),
                      'field_id':text('field_id'),'message':text('message'),'evidence':text('evidence')})
    return items,normalized


def _prior_resolved(raw,expected_count):
    """第二轮对第一轮意见的逐条回执：缺项/类型错都按「未全量处理」处理（严格，不替模型放行）。"""
    values=raw.get('prior_opinion_resolved') if isinstance(raw,dict) else None
    if not isinstance(values,list) or len(values)!=expected_count:return None
    resolved=[]
    for i,value in enumerate(values):
        if not isinstance(value,dict):return None
        index=value.get('opinion_index')
        note=value.get('note')
        resolved.append({'opinion_index':index if isinstance(index,int) else i,
                         'resolved':bool(value.get('resolved')),
                         'note':note if isinstance(note,str) else ''})
    return resolved


def _counts(items):
    important=sum(1 for item in items if item['severity']==SEVERITY_IMPORTANT)
    return important,len(items)-important


def _round_schema(indexes,round_no):
    """在结构 schema 上追加研判扩展键；模板四键的约束（块数/枚举）保持不变。"""
    schema=batch_schema(indexes)
    item_schema={'type':'object','properties':{
            'severity':{'type':'string','enum':[SEVERITY_IMPORTANT,SEVERITY_SUGGESTION]},
            'checklist':{'type':'string'},'field_id':{'type':'string'},
            'message':{'type':'string'},'evidence':{'type':'string'}},
        'required':['severity','message','evidence'],'additionalProperties':False}
    schema.setdefault('properties',{})['review_items']={'type':'array','maxItems':MAX_REVIEW_ITEMS,'items':item_schema}
    required=[key for key in schema.get('required',[]) if key!='review_items']
    schema['required']=required+['review_items']
    if round_no==2:
        schema['properties']['prior_opinion_resolved']={'type':'array','items':{
            'type':'object','properties':{'opinion_index':{'type':'integer'},
                'resolved':{'type':'boolean'},'note':{'type':'string'}},
            'required':['opinion_index','resolved'],'additionalProperties':False}}
        schema['required'].append('prior_opinion_resolved')
    return schema


def _completed_semantic_rounds(rounds):
    """已完成（拿到响应并做过结构校验）的语义轮：{number: 最后一条完成 entry}。"""
    done={}
    for entry in rounds:
        if entry.get('number') in ROUND_STAGE and entry.get('response_ref') and entry.get('stage')==ROUND_STAGE.get(entry.get('number')):
            if entry.get('status') in ('passed','invalid'):
                done[entry['number']]=entry
    return done


def _reviewable(raw):
    return isinstance(raw,dict) and isinstance(raw.get('blocks'),list) and bool(raw['blocks'])


# 工作流编译候选的边界：研判扩展键（review_items 等）不进 extra=forbid 的 TemplateReviewResult。
template_part_for_compile=_template_part


async def review_batches(store,state,ctx,packet,comparison_ref):
    """三轮研判入口（函数名沿用工作流接线）。

    返回 (final_raw, response_refs, meta)；meta 含 final_round / human_review_items /
    quality_incident，供 workflow 写入候选工件与事件。
    """
    indexes=[b['index'] for b in packet['source_reports'][0]['blocks']]
    batches=state.metadata.setdefault('template_batches',{})
    checkpoints=state.metadata.setdefault('template_review_checkpoints',{})
    if set(batches)!={FULL_TEMPLATE_KEY}:
        # 旧的三块分批台账与新执行模型不可互操作：整份重来，不把旧批次拼成新候选。
        batches.clear();checkpoints.clear()
    batch=batches.setdefault(FULL_TEMPLATE_KEY,{'targets':indexes,'rounds':[],'status':'pending'})
    batch['targets']=indexes

    def persist():store.put_task(state,state.revision)

    # 人工在异常研判页修正并通过结构校验后：人工修正即最终候选，直接进人工确认，
    # 不再补发研判轮（与旧的人工修正快速通道同义）。
    if (batch.get('status')=='human_corrected'
            and FULL_TEMPLATE_KEY in checkpoints):
        raw=store.get_artifact(checkpoints[FULL_TEMPLATE_KEY])
        if not collect_errors(_template_part(raw),packet,comparison_ref):
            meta={'final_round':None,'human_review_items':[],'quality_incident':False,'human_corrected':True}
            batch.update(status='passed',terminal='candidate_ready',final_response_ref=checkpoints[FULL_TEMPLATE_KEY],
                         round_meta=meta);persist()
            return raw,[checkpoints[FULL_TEMPLATE_KEY]],meta
    # 终态快速通道：只有三轮引擎自己写完终态才走；旧 checkpoint 不允许跳过 r2/r3。
    if batch.get('engine')==ENGINE and batch.get('terminal')=='candidate_ready' and batch.get('final_response_ref'):
        raw=store.get_artifact(batch['final_response_ref'])
        if not collect_errors(_template_part(raw),packet,comparison_ref):
            batch['status']='passed';persist()
            refs=[e['response_ref'] for e in batch['rounds'] if e.get('response_ref')]
            return raw,refs,batch.get('round_meta') or {'final_round':batch.get('final_round'),
                'human_review_items':batch.get('human_review_items',[]),'quality_incident':batch.get('quality_incident',False)}
        batch.pop('terminal',None)
    # 旧引擎留下的合法 checkpoint：仅在任务早已停在人工确认页时原样放行，避免给旧任务补发研判；
    # 其余情况（含中途恢复）归档旧轮次，按三轮重跑。
    if batch.get('engine')!=ENGINE and FULL_TEMPLATE_KEY in checkpoints:
        raw=store.get_artifact(checkpoints[FULL_TEMPLATE_KEY])
        if not collect_errors(_template_part(raw),packet,comparison_ref):
            if state.phase=='awaiting_template_confirmation':
                meta={'final_round':1,
                      'human_review_items':raw.get('review_items',[]) if isinstance(raw,dict) else [],
                      'quality_incident':False,'legacy_checkpoint':True}
                batch.update(status='passed',terminal='candidate_ready',
                             final_response_ref=checkpoints[FULL_TEMPLATE_KEY],round_meta=meta);persist()
                return raw,[checkpoints[FULL_TEMPLATE_KEY]],meta
        checkpoints.pop(FULL_TEMPLATE_KEY)
    if batch.get('engine')!=ENGINE:
        batch.setdefault('archived_rounds',[]).extend(batch.get('rounds',[]))
        batch['rounds']=[];batch['status']='pending'
    batch['engine']=ENGINE
    if batch['status']=='human_required':raise ManualTemplateReviewRequired(FULL_TEMPLATE_KEY)
    if batch['status']=='unusable':
        batch.setdefault('archived_rounds',[]).extend(batch['rounds'])
        batch['rounds']=[];batch['status']='pending'
    rounds=batch['rounds']
    done=_completed_semantic_rounds(rounds)
    if batch['status'] in ('truncated','transport_error','running'):
        # 硬失败/进程中断恢复：保留已完成的语义轮（r1 完就从 r2 续跑），
        # 只归档尾部未完成的尝试，绝不因快速通道跳过 r2/r3。
        keep={id(done[n]) for n in done}
        archived=[entry for entry in rounds if id(entry) not in keep]
        if archived:
            batch.setdefault('archived_rounds',[]).extend(archived)
            batch['rounds']=[done[n] for n in sorted(done)]
            rounds=batch['rounds'];persist()
        batch['status']='pending'

    def completed_raw(number):
        entry=done.get(number)
        return (store.get_artifact(entry['response_ref']),entry) if entry else (None,None)

    def build_request(round_no):
        request={'task_scope':{'target_blocks':indexes,'round':round_no,'maximum_rounds':MAX_TEMPLATE_ROUNDS,
            'stage':ROUND_STAGE[round_no],
            'instruction':get_prompt(ROUND_INSTRUCTION_KEY[round_no])},
            **packet,'target_blocks':indexes}
        context={'round':round_no,'maximum_rounds':MAX_TEMPLATE_ROUNDS}
        if round_no>=2:
            r1_raw,r1_entry=completed_raw(1)
            r1_items=(r1_entry.get('review_items') if r1_entry else []) or []
            context['structural_errors']=(r1_entry.get('errors') if round_no==2 and r1_entry else
                                          (done.get(round_no-1).get('errors') if round_no==3 and done.get(round_no-1) else []))
            if round_no==2:
                context['prior_round']={'template':_template_part(r1_raw),'review_items':r1_items}
                context['history']=[]
            else:
                r2_raw,r2_entry=completed_raw(2)
                context['prior_round']={'template':_template_part(r2_raw),
                    'review_items':(r2_entry.get('review_items') or []) if r2_entry else [],
                    'prior_opinion_resolved':(r2_entry.get('prior_opinion_resolved') if r2_entry else [])}
                context['history']=[{'round':1,'template':_template_part(r1_raw),'review_items':r1_items},
                                    {'round':2,'template':_template_part(r2_raw),
                                     'review_items':(r2_entry.get('review_items') or []) if r2_entry else []}]
        request['semantic_round']=context
        return request

    async def run_round(round_no):
        """跑一个语义轮；硬失败（非法 JSON）在本轮原地重试，不推进轮次。"""
        nonlocal done
        hard_attempt=0
        while True:
            hard_attempt+=1
            request=build_request(round_no)
            entry={'number':round_no,'stage':ROUND_STAGE[round_no],'started_at':stamp(),'status':'running',
                   'errors':[],'attempt':hard_attempt,
                   'request_ref':store.put_artifact(state.id,'template_round_input',request)}
            rounds.append(entry);batch['status']='running';persist()
            # 进度口径沿用「已覆盖目标块数」（前端 app.js 不允许改动，仍按 段 渲染），
            # 轮次信息另由 template_round_started/passed 事件承载（前端显示「第 N/3 轮」）。
            store.append_event(state.id,{'type':'template_model_progress','mode':'three_round','stage':'started',
                'round':round_no,'completed':0,'total':len(indexes),
                'source_count':len(packet['source_reports'])})
            store.append_event(state.id,{'type':'template_round_started','batch':FULL_TEMPLATE_KEY,'round':round_no,
                'stage':ROUND_STAGE[round_no],'maximum_rounds':MAX_TEMPLATE_ROUNDS})
            call_started=time.perf_counter()
            try:
                answer=await invoke_agent('template_analyst',request,RawTemplateResult,ctx,
                                          response_schema=_round_schema(indexes,round_no))
                entry['model_elapsed_ms']=round((time.perf_counter()-call_started)*1000)
                raw=answer.root
                entry['response_ref']=store.put_artifact(state.id,'template_model_response',raw)
                items,normalized=_review_items(raw)
                if normalized:
                    store.append_event(state.id,{'type':'template_round_item_normalized','batch':FULL_TEMPLATE_KEY,
                        'round':round_no,'count':normalized})
                entry['review_items']=items
                receipts=None
                if round_no==2:
                    r1_entry=done.get(1)
                    r1_items=(r1_entry.get('review_items') or []) if r1_entry else []
                    receipts=_prior_resolved(raw,len(r1_items))
                    entry['prior_opinion_resolved']=receipts or []
                validation_started=time.perf_counter()
                issues=collect_errors(_template_part(raw),packet,comparison_ref)
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
                        'round':round_no,'finish_reason':_last_finish_reason(store,state.id),'detail':truncated[:400]})
                    raise TemplateResponseTruncated(message) from exc
                issues=[{'code':'invalid_json','message':'模型未返回可读取的JSON对象。','actual':str(exc)[:400]}]
                entry.update(status='invalid',ended_at=stamp(),errors=issues)
                entry['elapsed_ms']=elapsed(entry['started_at'],entry['ended_at'])
                batch['status']='repairing';persist()
                store.append_event(state.id,{'type':'template_validation_error','batch':FULL_TEMPLATE_KEY,'round':round_no,
                    'stage':ROUND_STAGE[round_no],'errors':issues,'hard_retry':True,
                    'response_ref':entry.get('response_ref'),'elapsed_ms':entry['elapsed_ms']})
                if hard_attempt>=HARD_ATTEMPTS:return None
                done=_completed_semantic_rounds(rounds)
                continue
            except Exception as exc:
                entry['model_elapsed_ms']=round((time.perf_counter()-call_started)*1000)
                entry.update(status='transport_error',ended_at=stamp(),error_type=type(exc).__name__,error=str(exc)[:400])
                entry['elapsed_ms']=elapsed(entry['started_at'],entry['ended_at']);batch['status']='transport_error';persist()
                raise
            important,suggestions=_counts(items)
            unresolved_prior=False
            if round_no==2:
                # 回执缺失/数量不符/任一 resolved=false 都算「第一轮意见未全量处理」，不允许完美。
                unresolved_prior=(receipts is None or any(not r['resolved'] for r in receipts))
            verdict={'important':important,'suggestions':suggestions,
                     'structural_errors':len(issues),'prior_unresolved':bool(unresolved_prior)}
            if round_no==2:
                verdict['perfect']=(not issues and important==0 and suggestions<3 and not unresolved_prior)
            entry['verdict']=verdict
            entry.update(status='invalid' if issues else 'passed',ended_at=stamp(),errors=issues)
            entry['elapsed_ms']=elapsed(entry['started_at'],entry['ended_at'])
            persist()
            if issues:
                batch['status']='repairing'
                store.append_event(state.id,{'type':'template_validation_error','batch':FULL_TEMPLATE_KEY,'round':round_no,
                    'stage':ROUND_STAGE[round_no],'errors':issues,'response_ref':entry.get('response_ref'),
                    'elapsed_ms':entry['elapsed_ms']})
            else:
                passed_event={'type':'template_round_passed','batch':FULL_TEMPLATE_KEY,'round':round_no,
                    'stage':ROUND_STAGE[round_no],'elapsed_ms':entry['elapsed_ms'],
                    'important':important,'suggestions':suggestions}
                if round_no==2:passed_event['perfect']=bool(verdict['perfect'])
                store.append_event(state.id,passed_event)
            done=_completed_semantic_rounds(rounds)
            return store.get_artifact(entry['response_ref'])

    def finish(final_number,raw,entry):
        items=entry.get('review_items') or []
        incident=(final_number==3 and any(i['severity']==SEVERITY_IMPORTANT for i in items))
        meta={'final_round':final_number,'human_review_items':items,'quality_incident':incident}
        checkpoints[FULL_TEMPLATE_KEY]=entry['response_ref']
        batch.update(status='passed',terminal='candidate_ready',final_round=final_number,
                     final_response_ref=entry['response_ref'],human_review_items=items,
                     quality_incident=incident,round_meta=meta)
        persist()
        store.append_event(state.id,{'type':'template_model_progress','mode':'three_round','stage':'finished',
            'round':final_number,'completed':len(indexes),
            'total':len(indexes),'source_count':len(packet['source_reports'])})
        if final_number==3:
            # 第二轮完美时 run_round 已发过 template_round_passed（不重复）；
            # 第三轮终审另发带 advisory 口径的完成事件。
            store.append_event(state.id,{'type':'template_round_passed','batch':FULL_TEMPLATE_KEY,'round':final_number,
                'stage':ROUND_STAGE[final_number],'elapsed_ms':entry.get('elapsed_ms'),
                'advisory':True,'important':sum(1 for i in items if i['severity']==SEVERITY_IMPORTANT),
                'suggestions':sum(1 for i in items if i['severity']==SEVERITY_SUGGESTION),'final':True})
        if incident:
            store.append_event(state.id,{'type':'template_round_quality_incident','batch':FULL_TEMPLATE_KEY,
                'round':final_number,'important':sum(1 for i in items if i['severity']==SEVERITY_IMPORTANT)})
        refs=[e['response_ref'] for e in rounds if e.get('response_ref')
              and e.get('status') in ('passed','invalid') and e.get('number') in ROUND_STAGE]
        return raw,list(dict.fromkeys(refs)),meta

    # 续跑判定：r2 已完成且完美 → 终态；r2 完成但不完美、r3 未完成 → 跑 r3。
    r2_done=done.get(2)
    if r2_done is not None and r2_done.get('verdict',{}).get('perfect'):
        return finish(2,store.get_artifact(r2_done['response_ref']),r2_done)

    for round_no in (1,2,3):
        if round_no not in done:
            # 第 3 轮只在第 2 轮已完成且不完美时才允许执行。
            if round_no==3:
                r2_entry=done.get(2)
                if r2_entry is None:raise TemplateOutputUnavailable('第三轮缺少第二轮输入。')
                if r2_entry.get('verdict',{}).get('perfect'):
                    return finish(2,store.get_artifact(r2_entry['response_ref']),r2_entry)
            raw=await run_round(round_no)
            if raw is None:
                # 硬重试耗尽：有任意可审阅结构 → 人工异常研判；否则整份失败。
                reviewable=any(_reviewable(store.get_artifact(e['response_ref']))
                               for e in rounds if e.get('response_ref'))
                batch['status']='human_required' if reviewable else 'unusable';persist()
                if reviewable:raise ManualTemplateReviewRequired(FULL_TEMPLATE_KEY)
                raise TemplateOutputUnavailable('三轮研判在第 %d 轮连续返回不可读取的结构，'
                                                '没有分批断点、不支持续跑，请整份重试。'%round_no)
            done=_completed_semantic_rounds(rounds)
        entry=done[round_no]
        if round_no==1:
            continue
        if round_no==2:
            if entry.get('verdict',{}).get('perfect'):
                return finish(2,store.get_artifact(entry['response_ref']),entry)
            continue
        # round 3：结构合法即终态（意见全部 advisory）；结构非法时——
        # 有任意可审阅结构 → 人工异常研判兜底；连可审阅结构都没有 → 整份失败。
        if entry.get('errors'):
            reviewable=any(_reviewable(store.get_artifact(e['response_ref']))
                           for e in rounds if e.get('response_ref'))
            batch['status']='human_required' if reviewable else 'unusable';persist()
            if reviewable:raise ManualTemplateReviewRequired(FULL_TEMPLATE_KEY)
            raise TemplateOutputUnavailable('三轮研判结束仍未取得可审阅的模板结构；'
                                            '没有分批断点、不支持续跑，请整份重试。')
        return finish(3,store.get_artifact(entry['response_ref']),entry)
    raise TemplateOutputUnavailable('三轮研判未取得终态候选。')
