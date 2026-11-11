"""Hash-bound model reviews and bounded writer repairs over immutable facts."""
import copy,json,re,uuid,hashlib
from .agent import get_prompt,prompt_profile
from .state import WritingReviewReply,WritingRevisionReply,StyleJudgment
from .model_client import invoke_agent
from .tool_executor import RunContext
from .structured_template import load_confirmed_template,validate_values
from .frozen_report import FrozenReport
from .style_skill import skill_context,detect_style
from .source_binding import SourceCatalog,NumberedRevision,invoke_numbered_writer

ROLES=('format_reviewer','content_reviewer')
ACTIVE_PHASES={'writing','style_detection','format_review','content_review','final_format_review','revising'}

def text(value):return '\n\n'.join(map(str,value)) if isinstance(value,list) else str(value)

def document(store,state):
    draft=store.get_artifact(state.draft_ref)
    if draft.get('structured_template_ref'):
        template=load_confirmed_template(store,state.template_ref);definitions={f['id']:f for f in template['fields']}
    else:
        from .slot_writer import WRITER_SLOT_IDS
        template={};definitions={key:{'id':key,'owner':'writer' if key in WRITER_SLOT_IDS else 'data','display_name':key} for key in draft.get('slot_values',{})}
    fields={key:{'id':key,'name':definitions[key].get('display_name',key),'value':value['value'],
        'source_refs':value.get('source_refs',[]),'text':text(value['value']),'owner':definitions[key]['owner'],'kind':definitions[key].get('kind'),'rule':definitions[key].get('rule'),'format':definitions[key].get('format'),'value_schema':definitions[key].get('value_schema')} for key,value in draft.get('slot_values',{}).items() if key in definitions}
    machine={key:value for key,value in fields.items() if value['owner']=='writer' and 'human_edit' not in value['source_refs']}
    return draft,template,definitions,fields,machine

def supersede(store,state,role=None):
    for item in state.review_items:
        if item.get('kind')=='writing_review' and (role is None or item.get('reviewer')==role) and item['status']=='open':
            item.update(status='superseded',blocking=False)

def active_issues(state):
    return [i for i in state.review_items if i.get('kind')=='writing_review' and i.get('status')=='open']

def review_ready(state,draft_hash):
    report=state.metadata.get('review_report',{})
    return report.get('draft_hash')==draft_hash and report.get('policy_version')==review_policy(report.get('profile','anshun_monthly')) and all(report.get('reviewers',{}).get(role,{}).get('status') in ('passed','issues','human_confirmed') for role in ROLES) and not any(i.get('blocking') for i in active_issues(state))

def review_policy(profile):
    return hashlib.sha256(('writing-review-stage-retries-v5'+get_prompt('format_reviewer.review',profile)+get_prompt('content_reviewer.review',profile)+skill_context()['sha256']).encode()).hexdigest()

def format_passed(state,draft_hash):
    report=state.metadata.get('review_report',{})
    result=report.get('reviewers',{}).get('format_reviewer',{})
    return report.get('draft_hash')==draft_hash and report.get('policy_version')==review_policy(report.get('profile','anshun_monthly')) and result.get('status') in ('passed','issues','human_confirmed') and not any(i.get('blocking') for i in active_issues(state) if i.get('reviewer')=='format_reviewer')

def format_route(store,task_id):
    state=store.get_task(task_id)
    if state.cancel_requested:return 'finish'
    draft=store.get_artifact(state.draft_ref)
    run=state.metadata['writing_review_run']
    if format_passed(state,draft['content_hash']):
        run['format_stage_concluded']=True;store.put_task(state,state.revision);return 'content'
    result=state.metadata.get('review_report',{}).get('reviewers',{}).get('format_reviewer',{})
    if result.get('status')!='error' and run.get('stage_repair_attempts',{}).get('format_reviewer',0)<5 and repairable(store,state,'format_reviewer'):
        run['repair_stage']='format_reviewer';store.put_task(state,state.revision);return 'revise'
    # Forward the draft to content review, preserving every format finding. This never
    # converts an unresolved format review into a pass. `reason` distinguishes an actual
    # repair-budget limit from a writer decline or a reviewer error.
    if result.get('status')=='error':reason='error'
    elif run.get('stage_repair_attempts',{}).get('format_reviewer',0)>=5:reason='limit'
    else:reason='declined'
    run['format_limit_reached']=True;run['format_fallback_hash']=draft['content_hash'];run['format_stage_concluded']=True;run['format_forward_reason']=reason
    store.put_task(state,state.revision)
    store.append_event(task_id,{'type':'format_review_forwarded_to_content','draft_hash':draft['content_hash'],'status':result.get('status'),'reason':reason,'round':run['round'],'unresolved_format_issues':[i['id'] for i in active_issues(state) if i.get('reviewer')=='format_reviewer']})
    return 'content'

def begin_run(store,task_id,review_only=False):
    state=store.get_task(task_id)
    state.metadata['writing_review_required']=True
    profile=prompt_profile(state.metadata,store.get_artifact(state.template_ref))
    prior=state.metadata.get('writing_review_run',{})
    same=review_only and state.draft_ref and state.metadata.get('review_report',{}).get('draft_hash')==store.get_artifact(state.draft_ref)['content_hash'] and state.metadata.get('review_report',{}).get('policy_version')==review_policy(profile)
    if not same:
        supersede(store,state);state.metadata.pop('review_report',None)
    state.metadata['writing_review_run']={**(prior if same else {}),'id':prior.get('id',uuid.uuid4().hex) if same else uuid.uuid4().hex,
        'round':prior.get('round',1) if same else 1,'repair_attempts':prior.get('repair_attempts',0) if same else 0,
        'stage_repair_attempts':prior.get('stage_repair_attempts',{}) if same else {},'stage_rounds':prior.get('stage_rounds',{}) if same else {},
        'review_only':review_only,'finished':False,'style_refs':prior.get('style_refs',[]) if same else [],'profile':profile}
    # Reset per-run routing transient flags; re-runs must start the format→content→final_format sequence fresh.
    # Stage budget is enforced by stage_repair_attempts<5 / stage_rounds<5 (5 repair attempts per stage).
    for key in ('repair_stage','retry_reviewer','format_stage_concluded','format_limit_reached','format_fallback_hash','format_forward_reason'):
        state.metadata['writing_review_run'].pop(key,None)
    store.put_task(state,state.revision)

def local_review(store,task_id):
    state=store.get_task(task_id);draft,template,definitions,fields,machine=document(store,state)
    if state.fact_ref!=draft['fact_ref']:raise ValueError('stale_draft_fact')
    if template:validate_values(template,draft['slot_values'],set(draft['evidence_refs']))
    store.append_event(task_id,{'type':'writing_local_validation','draft_hash':draft['content_hash'],'missing':state.metadata.get('missing_fields',[])})
    return draft

def style_review(store,task_id):
    state=store.get_task(task_id);draft,template,definitions,fields,machine=document(store,state)
    ref,packet=detect_style(store,task_id,draft,list(definitions.values()))
    state.metadata['style_detection_ref']=ref;store.put_task(state,state.revision)
    if ref not in state.metadata['writing_review_run']['style_refs']:
        state.metadata['writing_review_run']['style_refs'].append(ref);store.put_task(state,state.revision)
    return packet

def payload_for(store,state,role):
    draft,template,definitions,fields,machine=document(store,state);report=FrozenReport(store,state.id)
    used={ref for value in machine.values() for ref in value['source_refs']};materials=[]
    for ref in used:
        row=report.by_id.get(ref)
        if row:materials.append({'ref':ref,**{key:row.get(key) for key in ('title','summary','published','source')}})
    history=None
    if state.metadata.get('historical_research_ref'):
        full=store.get_artifact(state.metadata['historical_research_ref']);history={'window':full['window'],'topics':full['topics']}
    style=store.get_artifact(state.metadata['style_detection_ref']) if state.metadata.get('style_detection_ref') else {}
    profile=prompt_profile(state.metadata,template)
    if history and 'monthly_recommendations' in machine:
        machine['monthly_recommendations']['template_rule']=machine['monthly_recommendations'].get('rule')
        machine['monthly_recommendations']['rule']=get_prompt('writer.outlook_field',profile)
        machine['monthly_recommendations']['execution_periods']=history['window']['periods']
    layout=[]
    for block in template.get('blocks',[]):
        if not any(part.get('field') in machine for part in block['parts']):continue
        rendered=''.join(part.get('text',text(fields[part['field']]['value']) if part.get('field') in fields and part['field'] not in {key for key,val in fields.items() if 'human_edit' in val['source_refs']} else '[已人工确认字段]') for part in block['parts'])
        layout.append({'index':block['index'],'kind':block['kind'],'parts':block['parts'],'rendered_text':rendered})
    payload={'instruction':get_prompt(role+'.review',profile),'draft_hash':draft['content_hash'],'fields':list(machine.values()),
        'editable_field_ids':sorted(machine),'allowed_evidence_refs':sorted(set(draft.get('evidence_refs',[]))|{state.fact_ref}),
        'quote_catalog':[{'id':key+':'+str(index),'field_id':key,'text':match.group()} for key,value in machine.items() for index,match in enumerate(re.finditer(r'[^。！？\n]{1,760}[。！？]?',value['text']))],
        'missing_fields':state.metadata.get('missing_fields',[]),
        'readonly_data':[v for v in fields.values() if v['owner']=='data'],'template_layout':layout,
        'confirmed_rules':{**template.get('rules',{}),**({'monthly_recommendations_scope':'future_1_2_months','forecast_periods':history['window']['periods']} if history else {})},'frozen_context':report.summary(),'source_materials':materials,
        'forecast_basis':history,'excluded_human_fields':[key for key,value in fields.items() if 'human_edit' in value['source_refs']],
        'last_repair_validation_error':state.metadata.get('writing_review_run',{}).get('repair_error'),
        'last_repair_field_errors':state.metadata.get('writing_review_run',{}).get('repair_field_errors',[])}
    if role=='content_reviewer':
        payload['style']={'metrics':style.get('metrics',{}),'semantic_candidates':style.get('semantic_candidates',[]),'project_findings':style.get('project_findings',[])}
        payload['skill']={**skill_context(),'application':get_prompt('style.application',profile)}
    return draft,fields,machine,payload,style

async def run_reviewer(deps,task_id,role,phase=None):
    store=deps.store;state=store.get_task(task_id);draft,fields,machine,payload,style=payload_for(store,state,role)
    # format_stage_concluded is the primary gate (set by format_route on both pass and forward);
    # format_passed and format_fallback_hash are retained as defense-in-depth.
    if role=='content_reviewer' and not state.metadata['writing_review_run'].get('format_stage_concluded') and not format_passed(state,draft['content_hash']) and state.metadata['writing_review_run'].get('format_fallback_hash')!=draft['content_hash']:raise ValueError('format_review_required_before_content')
    old=state.metadata.get('review_report',{})
    prior=old.get('reviewers',{}).get(role,{})
    forced=state.metadata['writing_review_run'].pop('retry_reviewer',None)==role
    if not forced and old.get('draft_hash')==draft['content_hash'] and prior.get('status') in ('passed','issues','human_confirmed'):return state
    counts=state.metadata['writing_review_run'].setdefault('stage_rounds',{})
    counts[role]=counts.get(role,0)+1
    state.phase=phase or ('format_review' if role=='format_reviewer' else 'content_review');store.put_task(state,state.revision)
    reply=None;error=None
    try:
        if not machine:
            result={'status':'human_confirmed','summary':'正文已由人工确认，不再交回模型。','issues':[],'semantic_judgments':[],'model_called':False}
        else:
            from pydantic import ValidationError
            for attempt in range(3):
                try:
                    reply=await invoke_agent(role,payload,WritingReviewReply,RunContext(store,task_id,phase=state.phase,model_adapter=deps.model_adapter))
                    allowed=set(draft.get('evidence_refs',[]))|{state.fact_ref}
                    contract_errors=[]
                    quote_catalog={item['id']:item for item in payload['quote_catalog']}
                    for issue in reply.issues:
                        # ① quote 自动定位：quote_id 合法优先取回原句；非法则降级为按 quote 文本定位，不再因拼接/省略号拒绝。
                        if issue.quote_id:
                            anchor=quote_catalog.get(issue.quote_id)
                            if anchor and anchor['field_id']==issue.field_id:issue.quote=anchor['text']
                            else:issue.quote_id=None
                        if issue.field_id not in machine:contract_errors.append('field_id只能选editable_field_ids，不能审查该字段:'+issue.field_id)
                        elif issue.quote and issue.quote not in text(fields[issue.field_id]['value']):
                            catalog_texts=[c['text'] for c in quote_catalog.values() if c['field_id']==issue.field_id]
                            matched=next((c for c in catalog_texts if issue.quote in c or c in issue.quote), None)
                            if matched:issue.quote=matched
                        invalid=set(issue.evidence_refs)-allowed
                        if invalid:contract_errors.append('evidence_refs只能选allowed_evidence_refs；字段名、上下文路径、skill标签不是来源ID，无需引用时用空数组。无效引用:'+','.join(sorted(invalid)))
                    if role=='content_reviewer':
                        # ③ 语义候选自动补全：漏掉的补为阴性、多出的忽略、label 越界收敛到 allowed_labels。
                        candidates={c['candidate_id']:c for c in style.get('semantic_candidates',[])}
                        valid=[];covered=set()
                        for j in reply.semantic_judgments:
                            cand=candidates.get(j.candidate_id)
                            if not cand or j.candidate_id in covered:continue
                            covered.add(j.candidate_id)
                            allowed=cand.get('allowed_labels',[])
                            if allowed and j.label not in allowed:j.label=allowed[-1]
                            valid.append(j)
                        for cid,cand in candidates.items():
                            if cid in covered:continue
                            allowed=cand.get('allowed_labels',[])
                            valid.append(StyleJudgment(candidate_id=cid,label=allowed[-1] if allowed else 'negative',confidence='low',reason='程序自动补全：模型未覆盖该候选，默认判为阴性。'))
                        reply.semantic_judgments=valid
                    if contract_errors:raise ValueError('\n'.join(contract_errors))
                    result={'status':'issues' if reply.issues else 'passed',**reply.model_dump(),'model_called':True}
                    break
                except (ValidationError,ValueError) as exc:
                    errors=['.'.join(map(str,e['loc']))+': '+e['msg'] for e in exc.errors(include_url=False,include_input=False)] if isinstance(exc,ValidationError) else str(exc).split('\n')
                    store.append_event(task_id,{'type':'review_output_correction','reviewer':role,'attempt':attempt+1,'errors':errors})
                    if attempt==2:raise
                    payload['correction_errors']=errors

    except Exception as exc:
        error=type(exc).__name__+': '+str(exc)[:1000]
        result={'status':'error','summary':'模型审查未完成，需重试或最终人工核查。','issues':[],'semantic_judgments':[],'error':error,'model_called':True}
    latest=store.get_task(task_id)
    if store.get_artifact(latest.draft_ref)['content_hash']!=draft['content_hash']:raise ValueError('stale_review_draft')
    supersede(store,latest,role)
    findings=list(result['issues'])
    if role=='content_reviewer':
        for item in style.get('project_findings',[]):
            if not any(i['field_id']==item['field_id'] and (i['quote'] in item['quote'] or item['quote'] in i['quote']) for i in findings):findings.append(item)
    if error:
        latest.review_items.append({'id':uuid.uuid4().hex,'kind':'writing_review','reviewer':role,'draft_hash':draft['content_hash'],'status':'open','blocking':True,
            'question':result['summary'],'details':{'field_id':'__review__','kind':'review_failure','description':error,'suggestion':'重试该稿审核，或在最终人工审核中明确核查。'},'allowed_actions':['confirm']})
    for finding in findings:
        latest.review_items.append({'id':uuid.uuid4().hex,'kind':'writing_review','reviewer':role,'draft_hash':draft['content_hash'],'status':'open',
            'blocking':finding['severity']=='blocking' or finding.get('action')=='revise','question':finding['description'],'details':finding,'allowed_actions':['confirm']})
    report=copy.deepcopy(latest.metadata.get('review_report',{})) if latest.metadata.get('review_report',{}).get('draft_hash')==draft['content_hash'] else {'draft_hash':draft['content_hash'],'reviewers':{}}
    round_no=latest.metadata['writing_review_run']['stage_rounds'][role]
    ref=store.put_artifact(task_id,'writing_review_result',{'reviewer':role,'draft_hash':draft['content_hash'],'round':round_no,**result,'project_findings':style.get('project_findings',[]) if role=='content_reviewer' else []})
    report['reviewers'][role]={**{k:result[k] for k in ('status','summary','model_called')},'draft_hash':draft['content_hash'],'result_ref':ref}
    profile=latest.metadata['writing_review_run']['profile']
    report.update(round=round_no,style_detection_ref=latest.metadata.get('style_detection_ref'),profile=profile,policy_version=review_policy(profile))
    latest.metadata['review_report']=report;latest.review_counts['format' if role=='format_reviewer' else 'content']+=1
    store.put_task(latest,latest.revision)
    store.append_event(task_id,{'type':'writing_review','reviewer':role,'status':result['status'],'round':round_no,'ref':ref,'draft_hash':draft['content_hash'],'issue_count':len(findings),'model_called':result['model_called']})
    return latest

def repairable(store,state,role=None):
    _,_,_,_,machine=document(store,state)
    return [i for i in active_issues(state) if (role is None or i.get('reviewer')==role) and i['details'].get('action')=='revise' and i['details'].get('field_id') in machine and not i['details'].get('writer_declined')]

def normalized_before(value):
    return re.sub(r'\s+','',text(value)).translate(str.maketrans({'“':'"','”':'"','‘':"'",'’':"'"}))

def mark_writer_declined(store,task_id,issue_ids,reason):
    ids=set(issue_ids)
    if not ids:return
    latest=store.get_task(task_id)
    for item in active_issues(latest):
        if item['id'] in ids:
            item['details']['writer_declined']=True
            item['details']['decline_reason']=reason
    latest.metadata['writing_review_run'].pop('repair_error',None)
    store.put_task(latest,latest.revision)
    store.append_event(task_id,{'type':'writer_repair_declined','issue_ids':sorted(ids),'reason':reason})

def review_route(store,task_id):
    state=store.get_task(task_id)
    if state.cancel_requested:return 'finish'
    report=state.metadata.get('review_report',{})
    if report.get('reviewers',{}).get('content_reviewer',{}).get('status')=='error':return 'finish'
    run=state.metadata['writing_review_run']
    if run.get('stage_rounds',{}).get('content_reviewer',0)<5 and run.get('stage_repair_attempts',{}).get('content_reviewer',0)<5 and repairable(store,state,'content_reviewer'):
        run['repair_stage']='content_reviewer';store.put_task(state,state.revision);return 'revise'
    # Content stage done (passed, round/repair budget exhausted, or nothing repairable):
    # run one final format check before handing to human review.
    return 'final_format'

def numbers(value):
    months={name:str(index) for index,name in enumerate(('一','二','三','四','五','六','七','八','九','十','十一','十二'),1)}
    value=re.sub(r'(十二|十一|十|[一二三四五六七八九])(?=月)',lambda m:months[m.group()],text(value))
    return sorted(re.findall(r'\d+(?:\.\d+)?',value.replace(',','')))

async def revise_draft(deps,task_id):
    store=deps.store;state=store.get_task(task_id);draft,template,definitions,fields,machine=document(store,state)
    stage=state.metadata['writing_review_run'].get('repair_stage','content_reviewer')
    issues=repairable(store,state,stage);allowed_fields={i['details']['field_id'] for i in issues}
    profile=prompt_profile(state.metadata,template)
    payload={'instruction':get_prompt('writer.revise',profile),'editable_fields':[machine[k] for k in sorted(allowed_fields)],
        'issues':[{'id':i['id'],**i['details']} for i in issues],'readonly_data':[v for v in fields.values() if v['owner']=='data'],
        'frozen_context':FrozenReport(store,task_id).summary(),'correction_errors':[state.metadata['writing_review_run']['repair_error']] if state.metadata['writing_review_run'].get('repair_error') else [],
        'skill':{**skill_context(),'application':get_prompt('style.application',profile)}}
    from .section_two import role as section_role
    for item in payload['editable_fields']:
        item['required_numbers']=numbers(item['value'])
        if section_role(definitions[item['id']])=='analysis':
            item['value_schema']={**item.get('value_schema',{}),'minLength':300,'maxLength':500}
            item['recommended_length']={'minimum':350,'maximum':440,'counting':'包括标点，留出压缩余量'}
    state.metadata['writing_review_run']['repair_attempts']=state.metadata['writing_review_run'].get('repair_attempts',0)+1
    attempts=state.metadata['writing_review_run'].setdefault('stage_repair_attempts',{})
    attempts[stage]=attempts.get(stage,0)+1
    store.put_task(state,state.revision)
    allowed=set(draft.get('evidence_refs',[]))|{state.fact_ref}
    catalog=SourceCatalog(allowed)
    payload['instruction']+='\n'+get_prompt('writer.source_binding',profile)
    try:
        feedback=payload['correction_errors']
        for attempt in range(3):
            # 校验错误当场反馈给Writer重试，不消耗阶段退修预算；最终失败才记repair_error。
            payload['correction_errors']=feedback
            try:
                bound=await invoke_numbered_writer(catalog,payload,NumberedRevision,RunContext(store,task_id,phase='writing',model_adapter=deps.model_adapter))
                reply=WritingRevisionReply.model_validate(bound)
                if not reply.patches:
                    mark_writer_declined(store,task_id,{i['id'] for i in issues},'Writer认为当前意见无需自动修订，转人工核查。')
                    return False
                if len({p.field_id for p in reply.patches})!=len(reply.patches):raise ValueError('duplicate_repair_target')
                merged=copy.deepcopy(draft['slot_values']);changed=[];field_errors=[];declined=set()
                for patch in reply.patches:
                    key=patch.field_id
                    if key not in allowed_fields:raise ValueError('repair_target_or_before_mismatch')
                    before_value=machine[key]['value']
                    # before仅作定位，空白/引号差异不再拒绝；草稿hash负责防止覆盖并发修改。
                    targeted=[i for i in issues if i['details']['field_id']==key]
                    if not set(patch.issue_ids)<={i['id'] for i in targeted}:raise ValueError('repair_issue_not_available')
                    if patch.after==patch.before or patch.after==before_value:
                        declined.update(i['id'] for i in targeted);continue  # Keep its issue open; do not discard other valid patches.
                    if not set(patch.source_refs)<=allowed:raise ValueError('repair_source_not_available')
                    if not any(i['details']['kind']=='fact' for i in targeted) and numbers(before_value)!=numbers(patch.after):raise ValueError('style_repair_changed_fact_numbers')
                    if re.search(r'若|如果|可能|通常',text(before_value)) and not re.search(r'若|如果|可能|通常|或|风险',text(patch.after)):raise ValueError('repair_removed_judgment_qualifications')
                    if isinstance(before_value,list) and (not isinstance(patch.after,list) or len(before_value)!=len(patch.after)):raise ValueError('repair_changed_list_structure')
                    if section_role(definitions[key])=='analysis' and (not isinstance(patch.after,str) or not 300<=len(patch.after)<=500):
                        field_errors.append({'field_id':key,'error':'研判分析退修后仍须300—500字，当前'+str(len(patch.after))+'字；请控制350—440字，保留事实与判断限定。'})
                        continue
                    merged[key]={'value':patch.after,'source_refs':sorted(set(machine[key]['source_refs'])|set(patch.source_refs))};changed.append(key)
                if not changed:
                    if field_errors:raise ValueError('\n'.join(e['field_id']+': '+e['error'] for e in field_errors))
                    mark_writer_declined(store,task_id,declined or {i['id'] for i in issues},'Writer未给出有效文字改动，转人工核查。')
                    return False
                if template:validate_values(template,{k:merged[k] for k in changed},allowed,writer_only=True)
                latest=store.get_task(task_id)
                if store.get_artifact(latest.draft_ref)['content_hash']!=draft['content_hash']:raise ValueError('stale_review_draft')
                if not template:raise ValueError('legacy_draft_repair_requires_human_fields')
                from .structured_writer import save_draft
                result=save_draft(store,latest,template,merged,allowed,draft.get('chart_refs',{}),latest.metadata.get('writer_issues',[]))
                supersede(store,result)
                result.metadata['writing_review_run']['round']+=1;result.metadata.pop('review_report',None)
                result.metadata['writing_review_run'].pop('repair_error',None)
                result.metadata['writing_review_run']['repair_field_errors']=field_errors
                if declined:
                    for item in active_issues(result):
                        if item['id'] in declined:
                            item['details']['writer_declined']=True;item['details']['decline_reason']='该字段未给出有效文字改动，转人工核查。'
                result.metadata.pop('style_detection_ref',None);store.put_task(result,result.revision)
                ref=store.put_artifact(task_id,'writer_review_repair',{'before_hash':draft['content_hash'],'after_hash':store.get_artifact(result.draft_ref)['content_hash'],**reply.model_dump()})
                store.append_event(task_id,{'type':'writer_review_repair','ref':ref,'fields':changed,'round':result.metadata['writing_review_run']['round'],'stage':stage,'field_errors':field_errors})
                return True
            except ValueError as exc:
                feedback=[str(exc)[:1000]]
                store.append_event(task_id,{'type':'writer_repair_validation_retry','stage':stage,'attempt':attempt+1,'error':feedback[0]})
                if attempt==2:raise
        return False
    except Exception as exc:
        latest=store.get_task(task_id);latest.metadata['writing_review_run']['repair_error']=type(exc).__name__+': '+str(exc)[:1000];store.put_task(latest,latest.revision)
        store.append_event(task_id,{'type':'writer_review_repair_failed','error':str(exc)[:1000]})
        return False
    finally:catalog.audit(store,task_id,'writer_revise',sorted(allowed_fields))

def finish_review(store,task_id):
    state=store.get_task(task_id);state.phase='cancelled' if state.cancel_requested else 'awaiting_final_review'
    state.metadata['writing_review_run']['finished']=True
    state.metadata['writing_review_run']['review_item_order']=[i['id'] for i in active_issues(state)]
    report=state.metadata.get('review_report',{})
    state.metadata['writing_review_run']['blocked_at']=None if review_ready(state,store.get_artifact(state.draft_ref)['content_hash']) else 'final_review' if all(role in report.get('reviewers',{}) for role in ROLES) else 'format_review'
    store.put_task(state,state.revision)
    return state

def after_human_change(store,task_id,previous_hash,changed_fields,resolved_issue_ids=None):
    state=store.get_task(task_id);report=state.metadata.get('review_report')
    if not report or report.get('draft_hash')!=previous_hash:return
    current=store.get_artifact(state.draft_ref)['content_hash']
    for issue in active_issues(state):
        if issue['details'].get('field_id') in changed_fields and (resolved_issue_ids is None or issue['id'] in resolved_issue_ids):issue.update(status='resolved',decision={'action':'human_edit','reason':'人工最终修订，未回模型。'})
    report['model_reviewed_hash']=report.get('model_reviewed_hash',previous_hash);report['draft_hash']=current
    report['human_adjustment']={'fields':list(changed_fields),'previous_hash':previous_hash,'effective_hash':current}
    for result in report['reviewers'].values():result['effective_hash']=current
    store.put_task(state,state.revision)

def resolve_human_review(store,task_id,expected_hash,issue_ids,reason):
    state=store.get_task(task_id)
    if state.phase!='awaiting_final_review':raise ValueError('writing_review_not_at_human_stage')
    draft=store.get_artifact(state.draft_ref)
    if draft['content_hash']!=expected_hash:raise ValueError('stale_draft_hash')
    reason=reason.strip() or '人工已核对，保留当前内容。'
    items={i['id']:i for i in active_issues(state)}
    if not issue_ids or not set(issue_ids)<=set(items):raise ValueError('writing_review_issue_not_available')
    for key in issue_ids:items[key].update(status='resolved',decision={'action':'human_confirm','reason':reason,'draft_hash':expected_hash})
    report=state.metadata['review_report']
    for role,result in report['reviewers'].items():
        if result['status']=='error' and not any(i['reviewer']==role and i['details'].get('kind')=='review_failure' for i in active_issues(state)):result['status']='human_confirmed'
    store.put_task(state,state.revision);store.append_event(task_id,{'type':'human_writing_review','issue_ids':issue_ids,'reason':reason,'draft_hash':expected_hash,'model_called':False})
    return state
