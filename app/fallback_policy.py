from __future__ import annotations
from .schemas import TaskState

VERSION='anshun-colored-fallback-v1'
def build_fallback_plan(state:TaskState,reason:str)->dict:
    steps=['import_records','calculate_metrics','filter_positive_scope','filter_neutral_scope','filter_records','filter_warning_scope','filter_union_scope','resolve_locality','group_events','classify_records','cluster_event_themes','discover_topics','select_materials']
    pending=[]
    for step in steps:
        if step=='filter_warning_scope' and 'filter_records:warning' in state.result_refs: continue
        if step=='filter_positive_scope' and 'filter_records:positive' in state.result_refs: continue
        if step=='filter_neutral_scope' and 'filter_records:neutral' in state.result_refs: continue
        if step=='filter_union_scope' and 'filter_records:negative_or_warning' in state.result_refs: continue
        if step not in ('filter_warning_scope','filter_union_scope','filter_positive_scope','filter_neutral_scope') and step in state.result_refs: continue
        pending.append(step)
    goals={'calculate_metrics':['B17_sentiment_peak','B26_platform'],'filter_positive_scope':['positive_record_scope'],'filter_neutral_scope':['neutral_record_scope'],'filter_records':['negative_record_scope'],'filter_warning_scope':['warning_record_scope'],'filter_union_scope':['B30_categories_districts_top10'],'group_events':['B30_event_groups'],'cluster_event_themes':['B30_categories'],'resolve_locality':['B30_districts'],'select_materials':['B30_top10_candidates']}
    return {'version':VERSION,'reason':reason,'steps':pending,'goal_by_step':{s:goals.get(s,[]) for s in pending},'status':'active','event_scope':state.metadata.get('event_scope'),'event_scope_confirmed':bool(state.metadata.get('event_scope_confirmed'))}
