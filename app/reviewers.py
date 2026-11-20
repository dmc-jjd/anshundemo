"""Hash-bound model reviews and bounded writer repairs over immutable facts."""
import copy,json,re,uuid,hashlib
from contextlib import nullcontext
from .agent import get_prompt,prompt_profile
from .state import WritingReviewReply,WritingRevisionReply,StyleJudgment
from .model_client import invoke_agent
from .tool_executor import RunContext
from .structured_template import load_confirmed_template,validate_values
from .frozen_report import FrozenReport
from .style_skill import skill_context,detect_style
from .source_binding import SourceCatalog,NumberedRevision,invoke_numbered_writer
from core.graph.review_loop import STAGE_REVIEW_MAX_ROUNDS

ROLES=('format_reviewer','content_reviewer')
ACTIVE_PHASES={'writing','style_detection','format_review','content_review','final_format_review','revising'}

def text(value):return '\n\n'.join(map(str,value)) if isinstance(value,list) else str(value)

def document(store,state):
    draft=store.get_artifact(state.draft_ref)
    if draft.get('structured_template_ref'):
        template=load_confirmed_template(store,state.template_ref);definitions={f['id']:f for f in template['fields']}
    else:
        from .slot_writer import writer_slot_ids
        writer_ids=writer_slot_ids()
        template={};definitions={key:{'id':key,'owner':'writer' if key in writer_ids else 'data','display_name':key} for key in draft.get('slot_values',{})}
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

def stage_under_budget(run,role):
    """True if this stage can still start another review/repair. Caps reviewer calls at STAGE_REVIEW_MAX_ROUNDS."""
    return run.get('stage_rounds',{}).get(role,0)<STAGE_REVIEW_MAX_ROUNDS and run.get('stage_repair_attempts',{}).get(role,0)<STAGE_REVIEW_MAX_ROUNDS

def _task_package(state,store=None):
    name=getattr(state,'package',None)
    if isinstance(name,str):name=name.strip() or None
    if name:return name
    if store is not None and hasattr(store,'package_of'):
        try:
            name=store.package_of(getattr(state,'id',None))
            if isinstance(name,str) and name.strip():return name.strip()
        except Exception:
            pass
    if store is not None:
        raw=getattr(store,'package',None)
        if callable(raw):
            try:
                name=raw()
                if isinstance(name,str) and name.strip():return name.strip()
            except Exception:
                pass
        elif isinstance(raw,str) and raw.strip():
            return raw.strip()
    return None

def _review_profile(state):
    report=state.metadata.get('review_report',{})
    package=_task_package(state)
    if report.get('profile'):return report['profile'],package
    return prompt_profile(state.metadata,None,package=package),package

def review_ready(state,draft_hash):
    report=state.metadata.get('review_report',{})
    profile,package=_review_profile(state)
    return report.get('draft_hash')==draft_hash and report.get('policy_version')==review_policy(profile,package) and all(report.get('reviewers',{}).get(role,{}).get('status') in ('passed','issues','human_confirmed') for role in ROLES) and not any(i.get('blocking') for i in active_issues(state))

def review_policy(profile,package=None):
    from core.packages.context import package_context
    ctx=package_context(package) if package else nullcontext()
    with ctx:
        return hashlib.sha256(('writing-review-stage-retries-v5'+get_prompt('format_reviewer.review',profile)+get_prompt('content_reviewer.review',profile)+skill_context()['sha256']).encode()).hexdigest()

def format_passed(state,draft_hash):
    report=state.metadata.get('review_report',{})
    result=report.get('reviewers',{}).get('format_reviewer',{})
    profile,package=_review_profile(state)
    return report.get('draft_hash')==draft_hash and report.get('policy_version')==review_policy(profile,package) and result.get('status') in ('passed','issues','human_confirmed') and not any(i.get('blocking') for i in active_issues(state) if i.get('reviewer')=='format_reviewer')

def format_route(store,task_id):
    state=store.get_task(task_id)
    if state.cancel_requested:return 'finish'
    draft=store.get_artifact(state.draft_ref)
    run=state.metadata['writing_review_run']
    if format_passed(state,draft['content_hash']):
        run['format_stage_concluded']=True;store.put_task(state,state.revision);return 'content'
    result=state.metadata.get('review_report',{}).get('reviewers',{}).get('format_reviewer',{})
    if result.get('status')!='error' and stage_under_budget(run,'format_reviewer') and repairable(store,state,'format_reviewer'):
        run['repair_stage']='format_reviewer';store.put_task(state,state.revision);return 'revise'
    # Forward the draft to content review, preserving every format finding. This never
    # converts an unresolved format review into a pass. `reason` distinguishes an actual
    # repair-budget limit from a writer decline or a reviewer error.
    if result.get('status')=='error':reason='error'
    elif not stage_under_budget(run,'format_reviewer'):reason='limit'
    else:reason='declined'
    run['format_limit_reached']=True;run['format_fallback_hash']=draft['content_hash'];run['format_stage_concluded']=True;run['format_forward_reason']=reason
    store.put_task(state,state.revision)
    store.append_event(task_id,{'type':'format_review_forwarded_to_content','draft_hash':draft['content_hash'],'status':result.get('status'),'reason':reason,'round':run['round'],'unresolved_format_issues':[i['id'] for i in active_issues(state) if i.get('reviewer')=='format_reviewer']})
    return 'content'

def begin_run(store,task_id,review_only=False):
    state=store.get_task(task_id)
    state.metadata['writing_review_required']=True
    profile=prompt_profile(state.metadata,store.get_artifact(state.template_ref), package=_task_package(state))
    prior=state.metadata.get('writing_review_run',{})
    same=review_only and state.draft_ref and state.metadata.get('review_report',{}).get('draft_hash')==store.get_artifact(state.draft_ref)['content_hash'] and state.metadata.get('review_report',{}).get('policy_version')==review_policy(profile)
    if not same:
        supersede(store,state);state.metadata.pop('review_report',None)
    state.metadata['writing_review_run']={**(prior if same else {}),'id':prior.get('id',uuid.uuid4().hex) if same else uuid.uuid4().hex,
        'round':prior.get('round',1) if same else 1,'repair_attempts':prior.get('repair_attempts',0) if same else 0,
        'stage_repair_attempts':prior.get('stage_repair_attempts',{}) if same else {},'stage_rounds':prior.get('stage_rounds',{}) if same else {},
        'review_only':review_only,'finished':False,'style_refs':prior.get('style_refs',[]) if same else [],'profile':profile}
    # Reset per-run routing transient flags; re-runs must start the format→content→final_format sequence fresh.
    # Stage budget is enforced by stage_under_budget (STAGE_REVIEW_MAX_ROUNDS reviewer calls per stage).
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
    profile=prompt_profile(state.metadata,template, package=_task_package(state))
    if history and 'monthly_recommendations' in machine:
        machine['monthly_recommendations']['template_rule']=machine['monthly_recommendations'].get('rule')
        machine['monthly_recommendations']['rule']=get_prompt('writer.outlook_field',profile)
        machine['monthly_recommendations']['execution_periods']=history['window']['periods']
    layout=[]
    from core.structured_template import block_is_omitted
    omitted={p['field'] for b in template.get('blocks',[]) if block_is_omitted(b,draft['slot_values']) for p in b['parts'] if p.get('field')}
    machine={k:v for k,v in machine.items() if k not in omitted}
    for block in template.get('blocks',[]):
        if block_is_omitted(block,draft['slot_values']):continue
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
    from core.writing_contracts import group_context
    payload['writing_groups']=group_context(list(fields),report.writing_contract,draft.get('slot_values',{}))
    payload['instruction']+='\n逐组核查 writing_groups：主题、背景、条目必须同题；案例事实、分析、建议必须对应同一案例，建议落到报告客户；背景不得重复全月统计。机构家数与报道条数分开，按契约计算定义审核，不以旧模板账号口径替代。逻辑串题需报 logic，不能仅当文风问题。'
    if role=='content_reviewer':
        payload['style']={'metrics':style.get('metrics',{}),'semantic_candidates':style.get('semantic_candidates',[]),'project_findings':style.get('project_findings',[])}
        payload['skill']={**skill_context(),'application':get_prompt('style.application',profile)}
    from .writing_pipeline.category_coverage import context_for
    payload['field_statistics']={f['id']:context_for(report,f) for f in template.get('fields',[]) if f.get('category_coverage_scope')}
    payload['scoped_writing_contexts']=[{'members':g['members'],'context':report.scoped_summary(g['context_scope'],g.get('count_unit','events')) if g.get('include_statistics',True) else {'report_parameters':report.parameters()}} for g in report.writing_contract.get('groups',[]) if g.get('context_scope')]
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
    report.update(round=round_no,style_detection_ref=latest.metadata.get('style_detection_ref'),profile=profile,policy_version=review_policy(profile, _task_package(state)))
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
    if stage_under_budget(run,'content_reviewer') and repairable(store,state,'content_reviewer'):
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
    profile=prompt_profile(state.metadata,template, package=_task_package(state, store))
    payload={'instruction':get_prompt('writer.revise',profile),'editable_fields':[machine[k] for k in sorted(allowed_fields)],
        'issues':[{'id':i['id'],**i['details']} for i in issues],'readonly_data':[v for v in fields.values() if v['owner']=='data'],
        'frozen_context':FrozenReport(store,task_id).summary(),'correction_errors':[state.metadata['writing_review_run']['repair_error']] if state.metadata['writing_review_run'].get('repair_error') else [],
        'skill':{**skill_context(),'application':get_prompt('style.application',profile)}}
    from core.writing_contracts import group_context,repair_allowed
    frozen_report=FrozenReport(store,task_id)
    contract=frozen_report.writing_contract
    payload['writing_groups']=group_context(list(allowed_fields),contract,draft.get('slot_values',{}))
    payload['instruction']+='\n关联组退修必须参照 writing_groups 的整组正文及共同案例。仅改 editable_fields，不改程序数据或人工字段。修正 logic/fact 可替换机器引错案例带入的日期数字，但必须使用给定来源；文风修改仍须保留数字。列表可在字段 schema 允许的条数内调整，不删空。'
    from .section_two import role as section_role, analysis_length_limits
    package=_task_package(state, store)
    for item in payload['editable_fields']:
        targets=[i['details'] for i in issues if i['details']['field_id']==item['id']]
        logical=repair_allowed(item['id'],targets,contract,definitions[item['id']],item.get('source_refs'))
        item['repair_mode']='logic_replacement' if logical else 'minimal_edit'
        item['required_numbers']=[] if logical else numbers(item['value'])
        if logical:item['number_rule']='仅可保留或改用给定来源支持的数字；不得改动 readonly_data。允许在字段 schema 内调整列表条数。'
        minimum,maximum=analysis_length_limits(package, definitions.get(item['id']))
        if section_role(definitions[item['id']], package=package)=='analysis' and (minimum is not None or maximum is not None):
            schema={**item.get('value_schema',{})}
            if minimum is not None: schema['minLength']=minimum
            if maximum is not None: schema['maxLength']=maximum
            item['value_schema']=schema
            if minimum==300 and maximum==500:
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
                    logical=repair_allowed(key,[i['details'] for i in targeted],contract,definitions[key],patch.source_refs)
                    if logical:
                        added=set(numbers(patch.after))-set(numbers(before_value))
                        source_text=[]
                        for ref in patch.source_refs:
                            if ref in frozen_report.by_id:
                                row=frozen_report.by_id[ref]
                                source_text.extend(str(row.get(k) or '') for k in ('title','summary','published'))
                            elif ref.startswith('historical_page-'):
                                page=store.get_artifact(ref)
                                if not page.get('read_error'):
                                    source_text.extend(str(page.get(k) or '') for k in ('title','content','published_at'))
                        supported=set(numbers(' '.join(source_text)))
                        if added-supported:raise ValueError('logic_repair_new_numbers_require_record_evidence')
                    if not logical and not any(i['details']['kind']=='fact' for i in targeted) and numbers(before_value)!=numbers(patch.after):raise ValueError('style_repair_changed_fact_numbers')
                    if re.search(r'若|如果|可能|通常',text(before_value)) and not re.search(r'若|如果|可能|通常|或|风险',text(patch.after)):raise ValueError('repair_removed_judgment_qualifications')
                    if isinstance(before_value,list) and (not isinstance(patch.after,list) or (not logical and len(before_value)!=len(patch.after))):raise ValueError('repair_changed_list_structure')
                    minimum,maximum=analysis_length_limits(package, definitions.get(key))
                    too_short=minimum is not None and (not isinstance(patch.after,str) or len(patch.after)<minimum)
                    too_long=maximum is not None and isinstance(patch.after,str) and len(patch.after)>maximum
                    if section_role(definitions[key], package=package)=='analysis' and (too_short or too_long):
                        lo='' if minimum is None else str(minimum)
                        hi='' if maximum is None else str(maximum)
                        field_errors.append({'field_id':key,'error':'分析段退修后须控制'+lo+'—'+hi+'字，当前'+str(len(patch.after) if isinstance(patch.after,str) else 0)+'字；请按包内定义压缩或补全，保留事实与判断限定。'})
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
