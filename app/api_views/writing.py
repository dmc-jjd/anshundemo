import hashlib,re

DRAFT_SCHEMA_OUTDATED_DETAIL='draft_schema_outdated: 该草稿由旧版本生成，缺少内容指纹，请重新生成草稿后再审核'


def draft_content_hash(store, state, draft):
    """草稿内容指纹（乐观并发基线）。旧结构草稿缺 content_hash 时返回 None 并留 draft_schema_outdated 审计事件：并发校验被跳过，但不许静默。"""
    value=draft.get('content_hash')
    if value is not None:return value
    ref=state.draft_ref
    if not any(e.get('type')=='draft_schema_outdated' and e.get('artifact')==ref for e in store.events(state.id)):
        store.append_event(state.id,{'type':'draft_schema_outdated','artifact':ref,'missing':['content_hash'],
            'reason':'legacy_draft_without_content_fingerprint'})
    return None


def assemble_review_view(store, state):
    """写作评审视图的组装（纯读）。draft_ref 缺失属于 HTTP 语义，判断留在路由函数里。"""
    from ..reviewers import active_issues,review_ready
    from ..writing_review import excerpt_locations
    draft=store.get_artifact(state.draft_ref)
    content_hash=draft_content_hash(store,state,draft)
    detection=store.get_artifact(state.metadata['style_detection_ref']) if state.metadata.get('style_detection_ref') else None
    run=state.metadata.get('writing_review_run',{})
    report=state.metadata.get('review_report',{})
    review_hashes={content_hash,report.get('model_reviewed_hash')}|{r.get('draft_hash') for r in report.get('reviewers',{}).values()}
    order=list(run.get('review_item_order',[])) or [i['id'] for i in state.review_items if i.get('kind')=='writing_review' and i.get('status')!='superseded' and i.get('draft_hash') in review_hashes]
    for issue in active_issues(state):
        if issue['id'] not in order:order.append(issue['id'])
    issues=[{**i,'number':order.index(i['id'])+1,'locations':excerpt_locations(draft,i)} for i in active_issues(state)]
    by_id={i['id']:i for i in state.review_items if i.get('kind')=='writing_review'}
    resolved_issues=[{**by_id[key],'number':order.index(key)+1,'locations':excerpt_locations(draft,by_id[key])}
        for key in run.get('review_item_order',[]) if key in by_id and by_id[key].get('status')=='resolved']
    history=[{'ref':ref,**store.get_artifact(ref)} for ref in run.get('style_refs',[])]
    hashes={item['draft_hash'] for item in history}
    repairs=[]
    for event in store.events(state.id):
        if event['type']=='writer_review_repair':
            patch=store.get_artifact(event['ref'])
            if patch['before_hash'] in hashes or patch['after_hash'] in hashes:repairs.append({'ref':event['ref'],**patch})
    return {'draft_hash':content_hash,'draft_schema_outdated':content_hash is None,
        'detail':None if content_hash else DRAFT_SCHEMA_OUTDATED_DETAIL,'report':state.metadata.get('review_report'),
        'run':run,'issues':issues,'resolved_issues':resolved_issues,'style_history':history,'repairs':repairs,
        'style':detection,'ready':bool(content_hash) and review_ready(state,content_hash),
        'graph_nodes':[e for e in store.events(state.id) if e['type']=='graph_node'][-48:]}


def apply_slot_values(store, state, req):
    """人工填槽。返回 (error, result)：error=(status,detail) 由路由函数转成 HTTP 错误。"""
    if not state.draft_ref:return (409,'draft_missing'),None
    from ..template_engine import is_slot_template
    if not is_slot_template(state.template_ref, getattr(state,'package',None)):
        from ..writing_review import edit_structured
        try:return None,edit_structured(store,state.id,req.values,req.expected_hash)
        except (ValueError,KeyError) as exc:return (409,str(exc)),None
    from ..slot_writer import writer_slot_ids
    if state.phase not in ('awaiting_final_review','facts_frozen'):return (409,'report_not_editable_in_current_phase'),None
    writer_ids=writer_slot_ids()
    for slot_id,value in req.values.items():
        if slot_id not in writer_ids: return (422,'unknown_writer_slot:'+slot_id),None
        if not isinstance(value,str):return (422,'invalid_slot_value:'+slot_id),None
        if not value.strip() or re.search(r'\{\{|\}\}',value): return (422,'invalid_slot_value:'+slot_id),None
    draft=store.get_artifact(state.draft_ref)
    previous_hash=draft_content_hash(store,state,draft)
    if previous_hash is None:return (409,DRAFT_SCHEMA_OUTDATED_DETAIL),None
    if req.expected_hash and req.expected_hash!=previous_hash:return (409,'stale_draft_hash'),None
    for slot_id,value in req.values.items():
        draft['slot_values'][slot_id]={'value':value.strip(),'source_refs':['human_edit']}
    from ..schemas import DraftVersion
    version=DraftVersion.model_validate(draft)
    version.content_hash=hashlib.sha256(version.model_dump_json(exclude={'content_hash'}).encode()).hexdigest()
    state.draft_ref=store.put_artifact(state.id,'human_filled_draft',version.model_dump())
    remaining=[x for x in state.metadata.get('writer_issues',[]) if x.get('slot_id') not in req.values]
    state.metadata['writer_issues']=remaining
    state.metadata['missing_fields']=[x['slot_id'] for x in remaining]
    state.metadata['preview_only']=bool(remaining)
    store.put_task(state,state.revision)
    from ..reviewers import after_human_change
    after_human_change(store,state.id,previous_hash,set(req.values))
    store.append_event(state.id,{'type':'human_slot_values','filled':sorted(req.values)})
    return None,{'draft_ref':state.draft_ref,'missing':state.metadata['missing_fields'],'preview_only':state.metadata['preview_only']}
