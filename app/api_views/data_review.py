from ..storage import ConflictError


def apply_event_settings(store, state, req):
    """校验并落地事件设置。返回 (error, result)：error=(status,detail) 由路由函数转成 HTTP 错误。"""
    if state.fact_ref:return (409,'frozen_facts'),None
    if state.phase not in ('awaiting_review','analysis_pending','failed'):return (409,'analysis_in_progress'),None
    if state.revision!=req.expected_revision:return (409,'stale_decision'),None
    if req.threshold is None and req.groups is None:return (422,'event_settings_required'),None
    if req.groups is None:
        if req.threshold is not None:
            state.metadata['human_review_final']=False
            state.metadata['event_threshold']=req.threshold
            state.result_refs.pop('group_events',None)
        for key in ('event_analysis','event_analysis_checkpoint','confirmed_event_groups','confirmed_theme_groups'):
            state.result_refs.pop(key,None)
        for item in state.review_items:
            if item['kind']=='data_review':item.update(status='superseded',blocking=False)
        state.metadata['reprocess_events']=True;state.metadata['analysis_pending']=True;state.phase='queued'
        store.put_task(state,state.revision)
        store.append_event(state.id,{'type':'event_rules_changed','threshold':state.metadata.get('event_threshold',.65),'human_adjusted':req.groups is not None})
        return None,{'state':state,'run_graph':True}
    local=store.get_artifact(state.result_refs['group_events'])
    ids=[rid for group in req.groups for rid in group.get('member_ids',[])]
    if len(ids)!=len(set(ids)) or set(ids)!=set(local['all_record_ids']):return (422,'review_members_must_cover_records_once'),None
    group_ids=[g.get('id') for g in req.groups]
    if any(not key for key in group_ids) or len(group_ids)!=len(set(group_ids)) or any(g.get('representative_id') not in g['member_ids'] for g in req.groups):
        return (422,'invalid_event_group_identity'),None
    prior=store.get_artifact(state.result_refs['event_analysis']) if state.result_refs.get('event_analysis') else {}
    from ..data_review import save_review_draft,apply_human_review
    draft_payload={'groups':req.groups,'merge_decisions':req.merge_decisions,'briefs':req.briefs,'groups_dirty':True}
    if req.themes is not None:draft_payload['themes']=req.themes
    try:saved=save_review_draft(store,state,draft_payload,req.draft_version)
    except (ValueError,ConflictError) as exc:return (409,str(exc)),None
    draft=store.get_artifact(saved['data_ref'])
    req.merge_decisions=draft['merge_decisions']
    pending=saved['pending_relationships'];conflicts=saved['conflicting_relationships']
    if pending or conflicts:
        return (409,f'已保存 {len(req.merge_decisions)} 项人工判断。仍有 {len(pending)} 项未判断、{len(conflicts)} 项与当前分组冲突；数据尚未锁定，可继续处理或刷新后恢复草稿。'),None
    apply_human_review(store,state,draft)
    return None,{'state':state,'run_graph':False}
