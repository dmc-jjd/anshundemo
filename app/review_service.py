"""Visible review documents and stage gates shared by the API and UI."""
from .structured_template import load_confirmed_template

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
    state=store.get_task(task_id)
    if 'group_events' not in state.result_refs:return {'legacy':True,'message':'此历史任务使用旧的逐项确认流程。请按新规则重新处理后查看整体数据。'}
    analysis=store.get_artifact(state.result_refs['event_analysis']) if state.result_refs.get('event_analysis') else None
    events=store.get_artifact(state.result_refs['confirmed_event_groups']) if state.fact_ref else analysis or store.get_artifact(state.result_refs['group_events'])
    themes=store.get_artifact(state.result_refs['confirmed_theme_groups']) if state.fact_ref else {'groups':analysis['theme_groups']} if analysis else store.get_artifact(state.result_refs['cluster_event_themes'])
    automatic=store.get_artifact(state.result_refs['group_events'])
    source=store.get_artifact(state.result_refs['filter_records:negative_or_warning'])['records']
    draft=store.get_review_draft(task_id,state.result_refs.get('event_analysis')) if analysis and not state.fact_ref else None
    review_draft=draft['data'] if draft else None
    return {'legacy':False,'revision':state.revision,'frozen':bool(state.fact_ref),'analysis_pending':state.metadata.get('analysis_pending',not bool(analysis)),
        'analysis_ref':state.result_refs.get('event_analysis'),'review_draft':review_draft,
        'draft_version':draft['version'] if draft else 0,'draft_saved_at':draft['updated_at'] if draft else None,
        'human_relationship_history':automatic.get('human_relationship_decisions',[]),
        'human_merge_decisions':analysis.get('human_merge_decisions',{}) if analysis else {},
        'merge_ambiguities':analysis.get('merge_ambiguities',[]) if analysis and not state.fact_ref else [],
        'classification_issues':analysis.get('classification_issues',[]) if analysis and not state.fact_ref else [],
        'analysis_counts':({**analysis.get('counts',{}),'human_merge_cases':0,'human_classification_events':0,'human_classification_records':0} if state.fact_ref and analysis else analysis.get('counts',{}) if analysis else {}),
        'top10':store.get_artifact(state.fact_ref).get('top10',[]) if state.fact_ref else analysis.get('top10',[]) if analysis else [],
        'metrics':store.get_artifact(state.fact_ref)['metrics'] if state.fact_ref else store.get_artifact(state.result_refs['calculate_metrics']),
        'event_groups':events['groups'],'themes':themes['groups'],'method':automatic['method'],
        'records':{r['id']:{'title':r['title'],'summary':r.get('summary','')[:600],'source':r.get('source',''),
                           'published':r.get('published',''),'url':r.get('url','')} for r in source},
        'review_item':next((x for x in state.review_items if x['kind']=='data_review' and x['status']=='open'),None)}

def draft_view(store,task_id):
    state=store.get_task(task_id)
    if not state.draft_ref:raise ValueError('draft_missing')
    draft=store.get_artifact(state.draft_ref)
    definition=load_confirmed_template(store,state.template_ref) if draft.get('structured_template_ref') else None
    if definition:
        from .chart_spec import with_styles,styles_for
        definition=with_styles(definition,styles_for(definition,state.metadata.get('chart_styles')))
    from .reviewers import review_ready,active_issues
    ready=review_ready(state,draft['content_hash'])
    pending={}
    for field_id,ref in state.metadata.get('writer_pending_sources',{}).items():
        if field_id not in state.metadata.get('missing_fields',[]):continue
        item=store.get_artifact(ref)
        if item.get('fact_ref')==state.fact_ref and item.get('template_ref')==state.template_ref:pending[field_id]=item
    return {'draft':draft,'definition':definition,'missing':state.metadata.get('missing_fields',[]),
            'pending_sources':pending,
            'issues':state.metadata.get('writer_issues',[]),'pending_charts':state.metadata.get('pending_charts',0),
            'report_parameters':state.metadata.get('report_parameters',{}),
            'writing_review':state.metadata.get('review_report'),'review_issues':active_issues(state),'review_ready':ready,
            'can_approve':state.phase=='awaiting_final_review' and not state.metadata.get('preview_only') and ready}
