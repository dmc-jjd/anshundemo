def resume_plan(store, state):
    """`/resume` 的阶段判定：返回 (error, plan)。

    error=(status,detail) 由路由函数转成 HTTP 错误。
    plan = {'graph': 'template'|'report'|'draft'|None, 'review_only': bool,
            'respond': 'state'|'fresh'|'preview'}
      - `respond=='state'` 返回上面就地更新过的任务；`'fresh'` 重新读到最新状态；
        `'preview'` 交给 `preview_draft`。
    **图的实际启动（`background_tasks.add_task`）与 `preview_draft` 的直接调用留在
    `app/main.py`**（RISK-11：那里若改成重发 HTTP 或复制一份逻辑，行为会悄悄变）。
    """
    if state.phase=='paused':
        from ..reviewers import ACTIVE_PHASES
        previous=state.metadata.pop('paused_from_phase',state.phase)
        state.metadata.pop('paused_at',None)
        template_active={'queued','processing','template_parsing','template_local_ready','template_model_reviewing','template_review_failed','failed'}
        report_active={'queued','processing','analyzing','analysis_pending','failed'}
        graph,review_only=None,False
        if state.kind=='template' and previous in template_active:
            state.phase='queued';store.put_task(state,state.revision,allow_resume=True)
            graph='template'
        elif state.kind=='report' and not state.fact_ref and previous in report_active:
            state.phase='queued';store.put_task(state,state.revision,allow_resume=True)
            graph='report'
        elif state.kind=='report' and previous in ACTIVE_PHASES:
            state.phase=previous;store.put_task(state,state.revision,allow_resume=True)
            graph='draft';review_only=state.metadata.get('writing_review_run',{}).get('review_only',False)
        else:
            state.phase=previous;store.put_task(state,state.revision,allow_resume=True)
        store.append_event(state.id,{'type':'task_resumed','to_phase':state.phase})
        return None,{'graph':graph,'review_only':review_only,'respond':'state'}
    if state.kind=='template' and not state.metadata.get('confirmed_template_ref'):
        if state.phase not in ('template_review_failed','awaiting_template_confirmation','awaiting_review','failed'):
            return (409,'template_analysis_in_progress'),None
        state.phase='queued';store.put_task(state,state.revision)
        return None,{'graph':'template','review_only':False,'respond':'state'}
    if state.kind=='report' and state.phase=='facts_frozen':
        return None,{'graph':None,'review_only':False,'respond':'preview'}
    if state.kind=='report' and state.result_refs.get('event_analysis') and state.phase=='awaiting_review':
        return None,{'graph':None,'review_only':False,'respond':'state'}
    if state.kind=='report' and not state.fact_ref and state.phase in ('awaiting_review','failed','analysis_pending'):
        state.phase='queued';store.put_task(state,state.revision)
        return None,{'graph':'report','review_only':False,'respond':'fresh'}
    return None,{'graph':None,'review_only':False,'respond':'fresh'}
