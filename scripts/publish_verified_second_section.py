"""Merge verified work recommendations; preserve other prose and human edits."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.storage import Store
from app.structured_writer import save_draft
from app.structured_template import validate_values
from app.section_two import POLICY_VERSION,policy_for

def publish(source_root):
    source=Store(source_root);target=Store(ROOT/'data')
    baseline=json.loads((source.root/'baseline.json').read_text(encoding='utf-8'))
    tid=baseline['task_id']
    tested=source.get_task(tid);state=target.get_task(tid)
    if state.phase not in ('facts_frozen','awaiting_final_review'):raise ValueError('当前报告不可编辑')
    if (state.fact_ref,state.template_ref)!=(tested.fact_ref,tested.template_ref):raise ValueError('验证副本与当前事实/模板版本不一致')
    candidate=source.get_artifact(tested.draft_ref);draft=target.get_artifact(state.draft_ref);template=target.get_artifact(state.template_ref)
    fields={f['id']:f for f in template['fields']};keys=('monthly_recommendations',)
    current=draft['slot_values'].get('monthly_recommendations')
    if current!=baseline.get('recommendations') and 'human_edit' not in (current or {}).get('source_refs',[]):raise ValueError('当前建议已有其他更新，不能覆盖')
    for key in keys:
        if key not in candidate['slot_values'] or tested.metadata.get('writer_policy_versions',{}).get(key)!=policy_for(fields[key]):raise ValueError('第二部分尚未通过当前执行约束')
    history_ref=tested.metadata['historical_research_ref'];history=source.get_artifact(history_ref)
    if history['status']!='ready' or history.get('policy_version')!=POLICY_VERSION or len((history.get('candidate_comparison') or {}).get('candidates',[]))<4:raise ValueError('混合风险候选比较与依据核对尚未完成')
    facts=target.get_artifact(state.fact_ref);first=dict(draft['slot_values']);allowed=set(draft['evidence_refs']);imported=[]
    # Source/plan artifacts are immutable and retain the same content hashes.
    with source.connect() as conn:rows=conn.execute('SELECT id,kind FROM artifacts WHERE task_id=?',(tid,)).fetchall()
    for row in rows:
        if row['kind'] not in ('historical_search','historical_page','historical_research','risk_comparison','risk_knowledge','second_section_plan','model_exchange'):continue
        ref=target.put_artifact(tid,row['kind'],source.get_artifact(row['id']))
        if ref!=row['id']:raise ValueError('artifact_identity_changed')
        imported.append(ref);allowed.add(ref)
    updated=[]
    for key in keys:
        if 'human_edit' in first.get(key,{}).get('source_refs',[]):continue
        first[key]=candidate['slot_values'][key];updated.append(key)
    validate_values(template,{key:first[key] for key in updated},allowed,writer_only=True)
    state.metadata['historical_research_ref']=history_ref
    state.metadata.setdefault('writer_policy_versions',{}).update({key:policy_for(fields[key]) for key in updated})
    state.metadata.setdefault('writer_field_prompt_fingerprints',{}).update({key:tested.metadata['writer_field_prompt_fingerprints'][key] for key in updated})
    state=save_draft(target,state,template,first,allowed,draft.get('chart_refs',{}),state.metadata.get('writer_issues',[]))
    assert target.get_artifact(state.fact_ref)==facts
    assert all(first.get(key)==value for key,value in draft['slot_values'].items() if key not in updated)
    target.append_event(tid,{'type':'verified_second_section_imported','source_database':str(source.db),'fields':updated,'history_ref':history_ref,'draft_ref':state.draft_ref,'fact_ref':state.fact_ref})
    # Count real testing requests once, explicitly marked as validation work.
    live=target.events(tid);request_ids={e.get('request_id') for e in live if e['type']=='model_usage'};web_ids={e.get('validation_source_id') for e in live if e['type']=='web_usage'}
    events=source.events(tid,after=baseline['start_seq']);count=0
    imported_events={e.get('validation_source_id') for e in live}
    for e in events:
        if e['type'] not in ('model_usage','web_usage','model_exchange','model_call','risk_candidate_comparison','historical_research_started','historical_validation','historical_research_result'):continue
        source_id=f'{source.root.name}:{e["seq"]}'
        if source_id in imported_events:continue
        if e['type']=='model_usage' and e['request_id'] in request_ids:continue
        if e['type']=='web_usage' and source_id in web_ids:continue
        event={k:v for k,v in e.items() if k not in ('seq','at')}
        event.update(validation_source_id=source_id,source_at=e['at'],source_database=str(source.db),phase='writing_validation')
        target.append_event(tid,event);count+=1
    result={'updated':updated,'history_ref':history_ref,'fact_ref':state.fact_ref,'draft_ref':state.draft_ref,'validation_usage_events_imported':count,'missing':state.metadata['missing_fields']}
    (source.root/'published.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':publish(Path(sys.argv[1]))
