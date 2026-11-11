from ..schemas import DraftVersion


def approval_gate(store, state, req, *, validate_draft, export_docx):
    """`/approve` 的全部审批门禁：返回 (error, state)。

    error=(status,detail) 由路由函数转成 HTTP 错误；校验通过时返回就地更新后的 state。
    `validate_draft` / `export_docx` 是 `app/main.py` 的模块级注入属性（monkeypatch 目标），
    **由路由函数体在调用时求值后作参数传入**——本层不导入 main，否则注入在 import 期被绑死。
    两条调用的先后关系（validate → 未解决阻塞项 → export → review_ready）与原文逐条一致。
    """
    from ..reviewers import ACTIVE_PHASES,review_ready
    if state.phase in ACTIVE_PHASES:return (409,'writing_in_progress'),None
    if not state.fact_ref:return (409,'data_review_required'),None
    if not state.draft_ref:return (409,'draft_missing'),None
    if state.metadata.get('preview_only'):return (409,'preview_cannot_be_approved'),None
    draft=store.get_artifact(state.draft_ref)
    if state.template_ref=='anshun-monthly-colored':
        from ..slot_writer import WRITER_SLOT_IDS
        unfilled=[slot_id for slot_id in sorted(WRITER_SLOT_IDS) if not (draft.get('slot_values',{}).get(slot_id) or {}).get('value')]
        if unfilled:return (409,'writer_slots_unfilled:'+','.join(unfilled)),None
    if req.draft_hash!=draft['content_hash']:return (409,'stale_draft'),None
    problems=validate_draft(DraftVersion.model_validate(draft),store.get_artifact(draft['fact_ref']))
    if any(problem.severity=='blocking' for problem in problems):return (409,'draft_validation_failed'),None
    if any(item['blocking'] and item['status']!='resolved' for item in state.review_items):return (409,'unresolved_blockers'),None
    if draft.get('structured_template_ref'):
        try:export_docx(draft,store.get_artifact(state.fact_ref),None,'final',[],local_store=store)
        except (ValueError,KeyError) as exc:return (409,'report_incomplete:'+str(exc)),None
    if not review_ready(state,draft['content_hash']):return (409,'writing_review_required'),None
    state.metadata['approval_hash']=req.draft_hash;state.phase='approved';store.put_task(state,state.revision)
    store.append_event(state.id,{'type':'final_approval','draft_hash':req.draft_hash})
    return None,state
