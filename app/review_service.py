"""Visible review documents and stage gates shared by the API and UI."""
from .structured_template import load_confirmed_template
from .api_views.writing import draft_content_hash,DRAFT_SCHEMA_OUTDATED_DETAIL

def check_rules(rules):
    if not isinstance(rules,dict):raise ValueError('template_rules_required')
    threshold=float(rules.get('event_threshold',.65))
    if not 0<threshold<=1:raise ValueError('invalid_event_threshold')
    if rules.get('first_warning_scope') not in ('negative_or_warning','warning'):raise ValueError('first_warning_scope_required')
    if rules.get('ranking')!='negative_warning_member_count':raise ValueError('ranking_rule_required')
    return {'event_threshold':threshold,'first_warning_scope':rules['first_warning_scope'],
            'ranking':'negative_warning_member_count','top10_scope':'negative_and_warning',
            'top10_unit':'deduplicated_event','top10_display':'serious_concise_summary','summary_min_chars':15,'summary_max_chars':35}

def review_data(store,task_id):
    from .structured_template import template_feature_switches
    state=store.get_task(task_id)
    features=template_feature_switches(state,store)
    # legacy 只留给**旧 schema**的逐项确认任务：它们没有 features 开关（去重恒为开），
    # 却也没有 group_events。用户主动关掉去重是新流程的合法状态，必须返回有效结构
    # （空数组 + 可确认路径），不能退化成「请按新规则重新处理」（QA2 B2）。
    if 'group_events' not in state.result_refs and features['dedup']:
        return {'legacy':True,'message':'此历史任务使用旧的逐项确认流程。请按新规则重新处理后查看整体数据。'}
    analysis=store.get_artifact(state.result_refs['event_analysis']) if state.result_refs.get('event_analysis') else None
    semantic=store.get_artifact(state.result_refs['semantic_classification']) if state.result_refs.get('semantic_classification') else None
    automatic=store.get_artifact(state.result_refs['group_events']) if state.result_refs.get('group_events') else None
    events=(store.get_artifact(state.result_refs['confirmed_event_groups']) if state.fact_ref
            else analysis or automatic or {'groups':[]})
    themes=(store.get_artifact(state.result_refs['confirmed_theme_groups']) if state.fact_ref
            else {'groups':analysis['theme_groups']} if analysis and analysis.get('theme_groups')
            else store.get_artifact(state.result_refs['cluster_event_themes']) if state.result_refs.get('cluster_event_themes')
            else {'groups':[]})
    source=store.get_artifact(state.result_refs['filter_records:negative_or_warning'])['records']
    draft=store.get_review_draft(task_id,state.result_refs.get('event_analysis')) if analysis and not state.fact_ref else None
    review_draft=draft['data'] if draft else None
    return {'legacy':False,'revision':state.revision,'frozen':bool(state.fact_ref),'analysis_pending':state.metadata.get('analysis_pending',features['dedup'] and not bool(analysis)),
        'analysis_ref':state.result_refs.get('event_analysis'),'review_draft':review_draft,
        'draft_version':draft['version'] if draft else 0,'draft_saved_at':draft['updated_at'] if draft else None,
        'human_relationship_history':automatic.get('human_relationship_decisions',[]) if automatic else [],
        'human_merge_decisions':analysis.get('human_merge_decisions',{}) if analysis else {},
        'merge_ambiguities':analysis.get('merge_ambiguities',[]) if analysis and not state.fact_ref else [],
        'classification_issues':(analysis or semantic or {}).get('classification_issues',[]) if not state.fact_ref else [],
        'classification_counts':(analysis or semantic or {}).get('classification_counts',{}),
        'classification_method':analysis.get('classification_method',{}) if analysis else (semantic or {}).get('method',{}),
        'analysis_counts':({**analysis.get('counts',{}),'human_merge_cases':0,'human_classification_events':0,'human_classification_records':0} if state.fact_ref and analysis else analysis.get('counts',{}) if analysis else {}),
        'top10':store.get_artifact(state.fact_ref).get('top10',[]) if state.fact_ref else analysis.get('top10',[]) if analysis else [],
        'metrics':store.get_artifact(state.fact_ref)['metrics'] if state.fact_ref else store.get_artifact(state.result_refs['calculate_metrics']),
        'event_groups':events['groups'],'themes':themes['groups'],
        # 没有 group_events（去重关）就没有归并方法可展示；给一个带 disabled 标记的占位，
        # 审核页据此说明「本期不产出归并事件」，而不是读到 undefined 报错。
        'method':automatic['method'] if automatic else {'threshold':state.metadata.get('event_threshold',.65),'disabled':True},
        'records':{r['id']:{'title':r['title'],'summary':r.get('summary','')[:600],'source':r.get('source',''),
                           'published':r.get('published',''),'url':r.get('url','')} for r in source},
        'review_item':next((x for x in state.review_items if x['kind']=='data_review' and x['status']=='open'),None)}

def draft_view(store,task_id):
    state=store.get_task(task_id)
    if not state.draft_ref:raise ValueError('draft_missing')
    draft=store.get_artifact(state.draft_ref)
    content_hash=draft_content_hash(store,state,draft)
    definition=load_confirmed_template(store,state.template_ref) if draft.get('structured_template_ref') else None
    if definition:
        from .chart_spec import with_styles,styles_for
        definition=with_styles(definition,styles_for(definition,state.metadata.get('chart_styles')))
    from .reviewers import review_ready,active_issues
    ready=bool(content_hash) and review_ready(state,content_hash)
    pending={}
    missing=list(state.metadata.get('missing_fields',[]) or [])
    pending_charts=int(state.metadata.get('pending_charts') or 0)
    preview_only=bool(state.metadata.get('preview_only'))
    if definition:
        from .structured_writer import preview_status
        status=preview_status(definition, draft.get('slot_values'), draft.get('chart_refs'))
        missing=status['missing_fields']
        pending_charts=status['pending_charts']
        preview_only=status['preview_only']
    for field_id,ref in state.metadata.get('writer_pending_sources',{}).items():
        if field_id not in missing:continue
        item=store.get_artifact(ref)
        if item.get('fact_ref')==state.fact_ref and item.get('template_ref')==state.template_ref:pending[field_id]=item
    return {'draft':draft,'definition':definition,'missing':missing,
            'draft_hash':content_hash,'draft_schema_outdated':content_hash is None,
            'detail':None if content_hash else DRAFT_SCHEMA_OUTDATED_DETAIL,
            'pending_sources':pending,
            'issues':state.metadata.get('writer_issues',[]),'pending_charts':pending_charts,
            'preview_only':preview_only,
            'report_parameters':state.metadata.get('report_parameters',{}),
            'writing_review':state.metadata.get('review_report'),'review_issues':active_issues(state),'review_ready':ready,
            'can_approve':state.phase=='awaiting_final_review' and not preview_only and ready}
