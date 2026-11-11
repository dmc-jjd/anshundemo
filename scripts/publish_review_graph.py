"""Publish a verified graph trial only when the live baseline is unchanged."""
import copy,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.storage import Store
from app.structured_template import validate_values
from app.reviewers import ROLES,review_policy

def publish(root):
    source=Store(root);target=Store(ROOT/'data');baseline=json.loads((root/'baseline.json').read_text(encoding='utf-8'))
    tid=baseline['task_id'];tested=source.get_task(tid);state=target.get_task(tid)
    if state.revision!=baseline['revision'] or state.draft_ref!=baseline['draft_ref']:raise ValueError('live_task_changed_preserve_user_work')
    if state.phase!='awaiting_final_review' or tested.phase!='awaiting_final_review':raise ValueError('task_not_at_human_review')
    if (state.fact_ref,state.template_ref)!=(tested.fact_ref,tested.template_ref):raise ValueError('facts_or_template_changed')
    draft=source.get_artifact(tested.draft_ref);template=target.get_artifact(state.template_ref)
    protected={f['id'] for f in template['fields'] if f['owner']=='data'}|{k for k,v in baseline['slot_values'].items() if 'human_edit' in v['source_refs']}
    if any(draft['slot_values'][k]!=baseline['slot_values'][k] for k in protected):raise ValueError('protected_value_changed')
    validate_values(template,draft['slot_values'],set(draft['evidence_refs']))
    report=tested.metadata['review_report']
    if report['draft_hash']!=draft['content_hash'] or report['policy_version']!=review_policy(report['profile']):raise ValueError('trial_review_is_stale')
    if not all(report['reviewers'].get(role,{}).get('model_called') for role in ROLES):raise ValueError('real_dual_review_required')
    with target.connect() as conn:known={row['id'] for row in conn.execute('SELECT id FROM artifacts')}
    with source.connect() as conn:rows=conn.execute('SELECT id,kind FROM artifacts WHERE task_id=?',(tid,)).fetchall()
    imported=[]
    for row in rows:
        if row['id'] in known:continue
        ref=target.put_artifact(tid,row['kind'],source.get_artifact(row['id']))
        if ref!=row['id']:raise ValueError('artifact_identity_changed')
        imported.append(ref)
    backup=ROOT/'backups'/('before-verified-review-'+root.name+'-rev'+str(state.revision)+'.json')
    backup.write_text(json.dumps(state.model_dump(),ensure_ascii=False,indent=2),encoding='utf-8')
    for key in ('writer_policy_versions','writer_field_prompt_fingerprints','writer_prompt_profile_applied','writer_prompt_fingerprint',
                'structured_writer_version','historical_research_ref','writer_issues','missing_fields','pending_charts','preview_only',
                'review_report','writing_review_run','style_detection_ref'):
        if key in tested.metadata:state.metadata[key]=copy.deepcopy(tested.metadata[key])
    state.metadata.pop('approval_hash',None);state.metadata.pop('writing_error',None)
    state.metadata['writing_review_required']=True
    state.metadata['verified_review_source']={'database':str(source.db),'draft_hash':draft['content_hash'],'baseline_revision':baseline['revision']}
    state.review_items=[i for i in state.review_items if i['kind']!='writing_review']+[copy.deepcopy(i) for i in tested.review_items if i['kind']=='writing_review']
    state.review_counts=copy.deepcopy(tested.review_counts);state.draft_ref=tested.draft_ref
    target.put_task(state,baseline['revision'])
    ids={e.get('validation_source_id') for e in target.events(tid)};events=0
    for event in source.events(tid,after=baseline['start_seq']):
        if event['type'] in ('phase','tool_start','tool_result'):continue
        source_id=root.name+':'+str(event['seq'])
        if source_id in ids:continue
        target.append_event(tid,{**{k:v for k,v in event.items() if k not in ('seq','at')},'validation_source_id':source_id,'source_at':event['at'],'source_database':str(source.db),'phase':'writing_validation'})
        events+=1
    target.append_event(tid,{'type':'verified_review_graph_imported','draft_ref':state.draft_ref,'fact_ref':state.fact_ref,'source_database':str(source.db),'protected_fields_unchanged':True})
    result={'task_id':tid,'draft_ref':state.draft_ref,'fact_ref':state.fact_ref,'missing':state.metadata['missing_fields'],'review_items':sum(i['kind']=='writing_review' and i['status']=='open' for i in state.review_items),'blocking_items':sum(i['kind']=='writing_review' and i['status']=='open' and i['blocking'] for i in state.review_items),'artifacts':len(imported),'events':events,'original_task_backup':str(backup)}
    (root/'published.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':publish(Path(sys.argv[1]).resolve())
