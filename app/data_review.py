"""Persist incomplete human review independently from final fact approval."""
UNKNOWN_CATEGORIES={'待人工分类','模型尚未处理'}


def check_members(groups,ids,events=False):
    if not isinstance(groups,list) or not groups:raise ValueError('review_groups_required')
    members=[rid for g in groups for rid in g.get('member_ids',[])]
    if len(members)!=len(set(members)) or set(members)!=set(ids):raise ValueError('review_members_must_cover_records_once')
    if events:
        keys=[g.get('id') for g in groups]
        if any(not key for key in keys) or len(keys)!=len(set(keys)) or any(g.get('representative_id') not in g['member_ids'] for g in groups):
            raise ValueError('invalid_event_group_identity')


def relationship_status(groups,cases,decisions):
    positions={rid:i for i,g in enumerate(groups) for rid in g['member_ids']}
    pending=[];conflicts=[]
    for case in cases:
        action=decisions.get(case['id'])
        if action not in ('same','different'):pending.append(case['id']);continue
        together=positions.get(case['source_id'])==positions.get(case['target_id'])
        if together!=(action=='same'):conflicts.append(case['id'])
    return pending,conflicts


def save_review_draft(store,state,payload,expected_version=None):
    if state.fact_ref:raise ValueError('frozen_facts')
    if state.phase not in ('awaiting_review','analysis_pending','failed'):raise ValueError('invalid_data_review_stage')
    ref=state.result_refs.get('event_analysis')
    if not ref:raise ValueError('event_analysis_required')
    analysis=store.get_artifact(ref)
    existing=store.get_review_draft(state.id,ref)
    base=existing['data'] if existing else {}
    groups=payload.get('groups',base.get('groups',analysis['groups']))
    themes=payload.get('themes',base.get('themes',analysis['theme_groups']))
    check_members(groups,analysis['all_record_ids'],True)
    check_members(themes,analysis['all_record_ids'])
    if any(not str(g.get('candidate_theme','')).strip() for g in themes):raise ValueError('theme_name_required')
    decisions={**base.get('merge_decisions',{}),**payload.get('merge_decisions',{})}
    if any(action not in ('same','different') for action in decisions.values()):raise ValueError('invalid_merge_decision')
    data={'groups':groups,'themes':themes,'merge_decisions':decisions,
          'briefs':{**base.get('briefs',{}),**payload.get('briefs',{})},
          'groups_dirty':bool(payload.get('groups_dirty',base.get('groups_dirty',False)))}
    result=store.put_review_draft(state.id,ref,data,expected_version)
    pending,conflicts=relationship_status(groups,analysis.get('merge_ambiguities',[]),decisions)
    return {**result,'pending_relationships':pending,'conflicting_relationships':conflicts}


def manual_category_changes(themes,original_themes):
    original={rid:g['candidate_theme'] for g in original_themes for rid in g['member_ids']}
    return {rid:g['candidate_theme'] for g in themes if g['candidate_theme'] not in UNKNOWN_CATEGORIES
            for rid in g['member_ids'] if original.get(rid)!=g['candidate_theme']}


def apply_human_review(store,state,draft,baseline_ref=None):
    """Human decisions end adjudication. Recompute derived data without models."""
    from collections import defaultdict
    from .event_analysis import negative_ranking
    from .schemas import now
    import uuid
    baseline_ref=baseline_ref or state.result_refs['event_analysis']
    original=store.get_artifact(baseline_ref)
    groups=draft['groups'];themes=draft['themes'];decisions=draft['merge_decisions']
    check_members(groups,original['all_record_ids'],True);check_members(themes,original['all_record_ids'])
    pending,conflicts=relationship_status(groups,original.get('merge_ambiguities',[]),decisions)
    if pending or conflicts:raise ValueError('merge_ambiguity_unresolved')
    category_by_record={rid:t['candidate_theme'] for t in themes for rid in t['member_ids']}
    grouped=defaultdict(list);issues=[]
    for group in groups:
        known={category_by_record[rid] for rid in group['member_ids']}-UNKNOWN_CATEGORIES
        if len(known)==1:category=next(iter(known))
        else:
            category='待人工分类'
            if known:reason='人工合并后原有分类存在冲突：'+'、'.join(sorted(known))+'。请选择该事件的最终分类。'
            else:
                prior=next((item for item in original.get('classification_issues',[]) if set(item['member_ids'])&set(group['member_ids'])),None)
                reason=(prior.get('reason') if prior else '尚无已确认的事件分类')+'；请人工选择最终分类，不再返回模型。'
            issues.append({'event_id':group['id'],'member_ids':group['member_ids'],'reason':reason})
        grouped[category].extend(group['member_ids'])
    new_themes=[{'candidate_theme':name,'member_ids':members} for name,members in grouped.items()]
    records=store.get_artifact(state.result_refs['filter_records:negative_or_warning'])['records']
    ranking=negative_ranking(groups,records)
    old_briefs={row['fingerprint']:row for row in original.get('top10',[])}
    old_briefs.update(draft.get('briefs',{}));top10=[]
    for rank,row in enumerate(ranking,1):
        brief=old_briefs.get(row['fingerprint'])
        valid=brief and brief.get('status')=='complete' and 15<=len(brief.get('summary','').strip())<=35 and brief.get('source_refs') and set(brief['source_refs'])<=set(row['negative_ids'])
        if valid:top10.append({**row,'rank':rank,'status':'complete','summary':brief['summary'],'source_refs':brief['source_refs']})
        else:top10.append({**row,'rank':rank,'status':'uncertain','summary':'','source_refs':[],
            'reason':(brief.get('reason') if brief else None) or '人工调整后此事件缺少已确认的15—35字梗概，请人工补充；不会返回模型重写。'})
    local=store.get_artifact(state.result_refs['group_events'])
    history=[{'id':case['id'],'source_id':case['source_id'],'target_id':case['target_id'],'decision':decisions[case['id']]} for case in original.get('merge_ambiguities',[])]
    local={**local,'groups':groups,'borderline_candidates':[],'human_relationship_decisions':history,
           'method':{**local['method'],'human_adjusted':True}}
    group_ref=store.put_artifact(state.id,'human_confirmed_groups',local)
    result={**original,'source_key':group_ref,'baseline_analysis_ref':baseline_ref,'groups':groups,'theme_groups':new_themes,'top10':top10,
            'classification_issues':issues,'human_merge_decisions':decisions,'human_review_applied':True,
            'human_relationship_decisions':history,'pending_model':False,'failures':[],
            'counts':{**original.get('counts',{}),'final_event_groups':len(groups),'human_merge_cases':0,
                      'human_classification_events':len(issues),'human_classification_records':sum(len(i['member_ids']) for i in issues),
                      'human_summary_cases':sum(row['status']!='complete' for row in top10)}}
    ref=store.put_artifact(state.id,'human_reviewed_event_analysis',result)
    state.result_refs.update(group_events=group_ref,event_analysis=ref)
    state.metadata.update(analysis_pending=False,analysis_stage='human_review_applied',reprocess_events=False,
                          human_review_final=True,human_review_applied_at=now())
    state.phase='awaiting_review';state.cancel_requested=False
    for item in state.review_items:
        if item['kind']=='data_review':item.update(status='superseded',blocking=False)
    state.review_items.append({'id':uuid.uuid4().hex,'kind':'data_review','question':'事件关系人工研判已生效，请完成剩余分类和梗概后确认数据。','blocking':True,'status':'open','allowed_actions':['confirm','modify','defer'],
        'details':{'event_ref':ref,'analysis_ref':ref,'metrics_ref':state.result_refs['calculate_metrics'],'cluster_ref':state.result_refs['cluster_event_themes']}})
    store.put_task(state,state.revision)
    store.put_review_draft(state.id,ref,{'groups':groups,'themes':new_themes,'merge_decisions':decisions,
        'briefs':draft.get('briefs',{}),'groups_dirty':False})
    store.append_event(state.id,{'type':'human_review_applied','judgments':len(history),'groups':len(groups),
        'pending_categories':len(issues),'pending_summaries':sum(row['status']!='complete' for row in top10),'model_called':False})
    return result
