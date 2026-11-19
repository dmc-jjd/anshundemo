"""Enforce a report's confirmed event population independently of model planning."""
from collections import Counter

SCOPE_REFS={'all':'import_records','negative':'filter_records:negative','warning':'filter_records:warning',
            'negative_warning':'filter_records:negative_warning','negative_or_warning':'filter_records:negative_or_warning'}
SCOPED_TOOLS={'group_events','classify_records','cluster_event_themes','discover_topics','propose_keyword_event_candidates'}

class EventScopeError(ValueError):
    def __init__(self,code,message):
        self.code=code
        super().__init__(code+'：'+message)

def enforced(state):
    # Old unscoped standalone tool tasks retain their contract; report creation always snapshots scope.
    return state.kind=='report' and 'event_scope' in state.metadata

def reference(state):
    scope=state.metadata.get('event_scope')
    if state.metadata.get('event_scope_confirmed') is not True or scope not in SCOPE_REFS:
        raise EventScopeError('event_scope_unconfirmed','任务事件统计范围尚未确认。')
    ref=state.result_refs.get(SCOPE_REFS[scope])
    if not ref:raise EventScopeError('event_scope_not_ready','请先生成任务已确认范围的筛选记录，不能改用全量记录。')
    return ref

def population(store,state):
    ref=reference(state)
    records=store.get_artifact(ref)['records']
    if not state.result_refs.get('import_records'):
        raise EventScopeError('event_scope_not_ready','缺少本任务原始记录，无法核对范围。')
    original=store.get_artifact(state.result_refs['import_records'])['records']
    scope=state.metadata['event_scope']
    if scope=='all':expected=original
    else:
        from .tools.records import _scope_matches
        from .tools import vocabulary
        from .task_package import resolve_task_package
        contract=vocabulary.filter_contract(resolve_task_package(state=state,store=store))
        expected=[r for r in original if _scope_matches(r,scope,contract)]
    if len({r['id'] for r in records})!=len(records) or {r['id']:r for r in records}!={r['id']:r for r in expected}:
        raise EventScopeError('event_scope_mismatch','筛选产物与任务确认范围不一致，请按新规则重新处理。')
    return ref,records

def check_records(store,state,records,source_ref=None):
    if not enforced(state):return
    ref,expected=population(store,state)
    if source_ref is not None and source_ref!=ref:
        raise EventScopeError('event_scope_mismatch','输入引用不是任务已确认的事件范围，拒绝使用全量或其他范围记录。')
    if len({r['id'] for r in records})!=len(records) or {r['id']:r for r in records}!={r['id']:r for r in expected}:
        raise EventScopeError('event_scope_mismatch','分析记录超出、遗漏或改写了任务确认范围。')

def check_groups(store,state,local):
    if not enforced(state):return
    ref,_=population(store,state)
    if local.get('source_records_ref')!=ref:
        raise EventScopeError('event_scope_mismatch','归并产物使用了错误的数据范围，请重新处理后再研判。')
    records=store.get_artifact(ref)['records']
    check_records(store,state,records,ref)
    ids=[r['id'] for r in records]
    members=[rid for g in local.get('groups',[]) for rid in g.get('member_ids',[])]
    if Counter(members)!=Counter(ids) or Counter(local.get('all_record_ids',[]))!=Counter(ids):
        raise EventScopeError('event_scope_mismatch','归并成员必须恰好覆盖确认范围，不得新增、遗漏或重复。')

def check_tool(store,state,name,arguments):
    if not enforced(state):return
    if name=='propose_vector_event_neighbors':
        prior=store.get_artifact(arguments['keyword_candidates_ref'])
        supplied=prior.get('records_ref')
    elif name in SCOPED_TOOLS:supplied=arguments.get('records_ref')
    else:return
    ref,records=population(store,state)
    check_records(store,state,records,supplied or '')
