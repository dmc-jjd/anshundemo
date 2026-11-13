def _template_name(template_ref, templates_by_id):
    """模板库里有 name 就用 name；取不到就退回 template_ref 本身，绝不拼出 None。"""
    item = (templates_by_id or {}).get(template_ref) or {}
    return str(item.get('name') or template_ref or '').strip()


def _month_text(report_month):
    parts = str(report_month or '').split('-')
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return f'{int(parts[0])} 年 {int(parts[1])} 月'
    return str(report_month or '').strip()


def _first_present(metadata, keys):
    """顶层 metadata 优先；旧任务只在 report_parameters 存档里，故回退读存档。"""
    parameters = metadata.get('report_parameters') or {}
    for key in keys:
        for source in (metadata, parameters):
            value = source.get(key)
            if value not in (None, ''): return value
    return None


def display_name(state, templates_by_id):
    """`/api/tasks` 的派生显示名（单一事实源）：模板名 · 报告月份 · 第N期 · 成文日期。

    纯派生：不写进 `TaskState`、不参与任何门禁哈希；缺哪个字段就省掉那一段。
    """
    metadata = state.metadata or {}
    if state.kind == 'report':
        issue = _first_present(metadata, ('report_issue', 'issue_number'))
        report_date = _first_present(metadata, ('report_date', 'publication_date'))
        segments = [
            _template_name(state.template_ref, templates_by_id),
            _month_text(metadata.get('report_month')),
            f'第{issue}期' if issue not in (None, '') else '',
            str(report_date) if report_date not in (None, '') else '',
        ]
        return ' · '.join(text for text in segments if text) or '报告任务'
    if state.kind == 'template':
        count = len(state.input_refs or []) or len(metadata.get('paths') or [])
        segments = ['模板比对', f'{count} 份报告' if count else '', str(state.created_at or '')[:10]]
        return ' · '.join(text for text in segments if text)
    return f'任务 {str(state.id)[:8]}'


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
