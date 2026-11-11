import hashlib
from pathlib import Path


def apply_definition_patch(store, state, req):
    """模板定义补丁。返回 (error, result)：error=(status,detail) 由路由函数转成 HTTP 错误。"""
    from ..structured_template import revise_candidate
    if state.revision!=req.expected_revision: return (409,'stale_template_revision'),None
    if state.metadata.get('confirmed_template_ref'): return (409,'immutable_confirmed_template'),None
    ref=state.metadata.get('structured_template_ref')
    if not ref: return (404,'structured_template_missing'),None
    if not state.metadata.get('template_validation_ref'):return (409,'template_semantic_review_required'),None
    if any(set(patch)-{'display_name'} for patch in req.fields.values()):return (422,'semantic_changes_require_model_review'),None
    try:
        candidate=revise_candidate(store.get_artifact(ref),req.fields)
        if req.chart_styles is not None:
            from ..chart_spec import with_styles
            candidate=with_styles(candidate,req.chart_styles)
        if req.rules is not None:
            from ..review_service import check_rules
            candidate['rules']=check_rules(req.rules)
    except ValueError as exc: return (422,str(exc)),None
    state.metadata['structured_template_ref']=store.put_artifact(state.id,'structured_template_candidate',candidate)
    from ..template_review import digest
    validation=store.get_artifact(state.metadata['template_validation_ref'])
    validation.update(candidate_ref=state.metadata['structured_template_ref'],candidate_hash=digest(candidate))
    state.metadata['template_validation_ref']=store.put_artifact(state.id,'template_validation',validation)
    store.put_task(state,state.revision)
    return None,None


def confirm_candidate(store, state, req):
    """人工确认模板候选。返回 (error, state)：已确认过则原样返回 state。"""
    if state.kind!='template': return (422,'not_template_task'),None
    if state.revision!=req.expected_revision: return (409,'stale_task_revision'),None
    if state.metadata.get('confirmed_template_ref'):return None,state
    if state.phase!='awaiting_template_confirmation':return (409,'template_semantic_review_required'),None
    if not state.metadata.get('comparison_ref'): return (409,'comparison_missing'),None
    if not state.metadata.get('structured_template_ref'): return (409,'structured_template_missing'),None
    if req.candidate_ref!=state.metadata['structured_template_ref']:return (409,'stale_template_candidate'),None
    candidate=store.get_artifact(state.metadata['structured_template_ref'])
    from ..template_review import digest,POLICY_VERSION
    validation_ref=state.metadata.get('template_validation_ref')
    if not validation_ref:return (409,'template_semantic_review_required'),None
    validation=store.get_artifact(validation_ref)
    if (validation.get('validation')!='passed' or validation.get('candidate_hash')!=digest(candidate)
        or validation.get('candidate_ref')!=req.candidate_ref or validation.get('policy_version')!=POLICY_VERSION
        or validation.get('input_ref')!=state.metadata.get('template_input_ref')
        or validation.get('input_hash')!=digest(store.get_artifact(validation['input_ref']))
        or not validation.get('review_refs')):return (409,'template_semantic_review_required'),None
    if any(hashlib.sha256(Path(s['path']).read_bytes()).hexdigest()!=s['sha256'] for s in candidate['source_reports']):
        return (409,'template_source_changed'),None
    for item in state.review_items:
        if item['kind']=='template_business_question' and item['status']!='resolved':
            answer=req.resolutions.get(item['id'],'').strip()
            if not answer:return (409,'unresolved_template_review'),None
            item.update(status='resolved',decision={'action':'confirm','answer':answer,'reason':req.reason})
    if any(x['blocking'] and x['status']!='resolved' and x['kind']!='template_candidate' for x in state.review_items): return (409,'unresolved_template_review'),None
    from ..structured_template import apply_top10_rule
    candidate=apply_top10_rule(candidate)
    from ..review_service import check_rules
    try:candidate['rules']=check_rules(req.rules or candidate.get('rules'))
    except (ValueError,TypeError) as exc:return (422,str(exc)),None
    for item in state.review_items:
        if item['kind']=='template_candidate':item.update(status='resolved',decision={'action':'confirm','reason':req.reason})
    business_decisions=[{'question':i['question'],'answer':i.get('decision',{}).get('answer') or i.get('decision',{}).get('payload',{}).get('answer','')} for i in state.review_items if i['kind']=='template_business_question']
    ref=store.put_artifact(state.id,'template_version',{**candidate,'version':1,'status':'confirmed_by_human','model_analysis':state.metadata.get('model_analysis'),'source_file_ids':state.input_refs,'human_reason':req.reason,'template_validation_ref':validation_ref,'human_resolutions':req.resolutions,'business_decisions':business_decisions})
    state.metadata['confirmed_template_ref']=ref; state.phase='template_confirmed'; store.put_task(state,state.revision)
    store.append_event(state.id,{'type':'template_confirmed','template_ref':ref,'reason':req.reason})
    return None,state
