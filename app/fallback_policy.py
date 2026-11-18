from __future__ import annotations
from .schemas import TaskState

VERSION='package-fallback-v1'
_STEP_ORDER=('import_records','calculate_metrics','filter_positive_scope','filter_neutral_scope','filter_records','filter_warning_scope','filter_union_scope','resolve_locality','group_events','classify_records','cluster_event_themes','discover_topics','select_materials')
_FILTER_STEPS=('filter_warning_scope','filter_union_scope','filter_positive_scope','filter_neutral_scope')
_FILTER_DONE={'filter_warning_scope':'filter_records:warning','filter_positive_scope':'filter_records:positive','filter_neutral_scope':'filter_records:neutral','filter_union_scope':'filter_records:negative_or_warning'}
_GENERIC_GOALS={'calculate_metrics':['metrics'],'filter_positive_scope':['positive_record_scope'],'filter_neutral_scope':['neutral_record_scope'],'filter_records':['negative_record_scope'],'filter_warning_scope':['warning_record_scope'],'filter_union_scope':['negative_or_warning_record_scope'],'group_events':['event_groups'],'cluster_event_themes':['event_categories'],'resolve_locality':['districts'],'select_materials':['top10_candidates']}

def _tool_name(step):
    if step in _FILTER_STEPS or step=='filter_negative_warning_scope':
        return 'filter_records'
    return step

def _package_name(state=None,package=None):
    if package:return package
    if state is not None and getattr(state,'package',None):return state.package
    return None

def _load_manifest(package=None):
    from core.packages import load_package
    return load_package(package).manifest

def _fallback_config(state=None,package=None):
    try:return dict(getattr(_load_manifest(_package_name(state,package)),'fallback',None) or {})
    except Exception:return {}

def event_scope_metadata(package=None):
    """建任务事件范围：通用缺省 + 包内声明的 applies_to / authority。"""
    meta={'event_scope':'negative_or_warning','event_scope_confirmed':True}
    try:cfg=dict(getattr(_load_manifest(package),'event_scope',None) or {})
    except Exception:cfg={}
    if cfg.get('default'):meta['event_scope']=str(cfg['default'])
    if 'confirmed' in cfg:meta['event_scope_confirmed']=bool(cfg['confirmed'])
    if cfg.get('applies_to'):meta['event_scope_applies_to']=str(cfg['applies_to'])
    if cfg.get('authority'):meta['event_scope_authority']=str(cfg['authority'])
    return meta

def _package_features(package=None):
    from .workflow import _FEATURE_SWITCHES
    try:declared=_load_manifest(package).features
    except Exception:return {name:False for name,_ in _FEATURE_SWITCHES.items()}
    return {name:(declared.get(key) or {}).get('enabled') is True for name,key in _FEATURE_SWITCHES.items()}

def _package_allow(package=None):
    try:
        from core.packages import load_package
        return set(load_package(package).tool_policy.allow)
    except Exception:
        return None

def build_fallback_plan(state:TaskState,reason:str,features=None,allow=None,disabled=None)->dict:
    """按包配置生成保底计划。安顺步骤顺序与槽位名来自安顺包；未声明则按 allow/features 生成。"""
    package=_package_name(state)
    cfg=_fallback_config(state,package)
    version=str(cfg.get('version') or VERSION)
    declared=cfg.get('steps')
    if declared:
        steps=[str(s) for s in declared]
    else:
        steps=list(_STEP_ORDER)
        if allow is None:allow=_package_allow(package)
        if allow is not None:
            allowed=set(allow)
            steps=[s for s in steps if _tool_name(s) in allowed]
    if disabled is None:
        if features is None:features=_package_features(package)
        from .workflow import _disabled_steps
        disabled=_disabled_steps(features)
    if disabled:
        steps=[s for s in steps if s not in disabled]
    pending=[]
    for step in steps:
        if step in _FILTER_DONE and _FILTER_DONE[step] in state.result_refs: continue
        if step not in _FILTER_STEPS and step in state.result_refs: continue
        pending.append(step)
    goals={**_GENERIC_GOALS,**(cfg.get('goal_by_step') or {})}
    return {'version':version,'reason':reason,'steps':pending,'goal_by_step':{s:list(goals.get(s,[])) for s in pending},'status':'active','event_scope':state.metadata.get('event_scope'),'event_scope_confirmed':bool(state.metadata.get('event_scope_confirmed'))}
