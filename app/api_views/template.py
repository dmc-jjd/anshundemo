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


MANUAL_POLICY_VERSION = 'MANUAL-1'
MANUAL_SOURCE = 'manual_definition'


def manual_validation(store, state, candidate_ref, candidate):
    """手工定义草稿 → (合成 validation, 生效候选)；不满足条件返回 (None, None)。

    这是**并列入口**，不是放宽模型研判：只有「草稿确实是这份候选的完整重放」时才合成一条
    `source=manual_definition` / `policy_version=MANUAL-1` 的 validation，之后 confirm 的全部
    校验（candidate_hash / candidate_ref / input_ref / input_hash / review_refs、来源报告、
    业务问题、规则）照旧逐条执行。草稿不完整或不是基于这份候选时不合成，原逻辑原样生效。
    """
    from ..template_draft import current_draft
    from ..template_review import digest
    draft = current_draft(store, state)
    if not draft or draft.get('base_ref') != candidate_ref:
        return None, None
    if [b['index'] for b in draft.get('blocks') or []] != [b['index'] for b in candidate.get('blocks') or []]:
        return None, None
    draft_fields = {field['id'] for field in draft.get('fields') or []}
    removed = {fid for entry in draft.get('selection_log') or []
               for fid in entry.get('removed_fields') or []}
    # 候选的每个字段都必须有着落：仍在草稿里，或被这条手动定义显式改回固定文字。
    if any(field['id'] not in draft_fields and field['id'] not in removed
           for field in candidate.get('fields') or []):
        return None, None
    input_ref = state.metadata.get('template_input_ref')
    if not input_ref:
        return None, None
    from ..structured_template import _schema
    effective = {**candidate, 'blocks': draft['blocks'], 'fields': draft['fields']}
    effective['output_schema'] = _schema(effective['fields'])
    effective['writer_schema'] = _schema(effective['fields'], True)
    validation = {
        'validation': 'passed', 'source': MANUAL_SOURCE,
        'candidate_hash': digest(effective), 'candidate_ref': candidate_ref,
        'policy_version': MANUAL_POLICY_VERSION, 'input_ref': input_ref,
        'input_hash': digest(store.get_artifact(input_ref)),
        'review_refs': [state.metadata.get('manual_template_draft_ref')],
        'manual_log': draft.get('selection_log') or [],
    }
    return validation, effective


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
    manual,effective=manual_validation(store,state,state.metadata['structured_template_ref'],candidate)
    if manual is not None:
        # 生效候选 = 草稿的 blocks/fields（用户看到的就是它）；validation 随之重算。
        candidate=effective
        state.metadata['template_validation_ref']=store.put_artifact(state.id,'template_validation',manual)
    validation_ref=state.metadata.get('template_validation_ref')
    if not validation_ref:return (409,'template_semantic_review_required'),None
    validation=store.get_artifact(validation_ref)
    # 入口来源只决定 policy_version 的取值：手工入口只认本次刚合成的 MANUAL-1，
    # 模型研判入口仍然只认 POLICY_VERSION。
    manual_source=validation.get('source')==MANUAL_SOURCE
    if manual_source and manual is None:return (409,'template_semantic_review_required'),None
    policy=MANUAL_POLICY_VERSION if manual_source else POLICY_VERSION
    if (validation.get('validation')!='passed' or validation.get('candidate_hash')!=digest(candidate)
        or validation.get('candidate_ref')!=req.candidate_ref or validation.get('policy_version')!=policy
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
