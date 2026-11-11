"""Local final fallbacks for the writing stage. Never invokes a model."""
from datetime import date
from .schemas import DraftVersion
from .structured_template import load_confirmed_template,validate_values
from .structured_writer import save_draft,data_values
from .frozen_report import FrozenReport

def edit_structured(store,task_id,values,expected_hash,parameters=None,resolved_issue_ids=None):
    state=store.get_task(task_id)
    if state.phase not in ('awaiting_final_review','facts_frozen'):raise ValueError('report_not_editable_in_current_phase')
    if not state.fact_ref or not state.draft_ref:raise ValueError('frozen_draft_required')
    draft=store.get_artifact(state.draft_ref)
    if not expected_hash or draft['content_hash']!=expected_hash:raise ValueError('stale_draft_hash')
    template=load_confirmed_template(store,state.template_ref);fields={f['id']:f for f in template['fields']}
    merged=dict(draft['slot_values']);allowed=set(draft['evidence_refs'])|{'human_edit'}
    for key,value in values.items():
        if key not in fields or fields[key]['owner']!='writer':raise ValueError('only_writer_fields_can_be_edited:'+key)
        answer={'value':value.strip() if isinstance(value,str) else value,'source_refs':['human_edit']}
        try:validate_values(template,{key:answer},allowed,writer_only=True)
        except Exception as exc:raise ValueError(str(exc)[:700]) from exc
        merged[key]=answer
    issues=state.metadata.get('writer_issues',[])
    if parameters is not None:
        if set(parameters)-{'issue_number','publication_date'}:raise ValueError('unknown_report_parameter')
        if 'publication_date' in parameters:date.fromisoformat(parameters['publication_date'])
        if 'issue_number' in parameters and (not str(parameters['issue_number']).isdigit() or int(parameters['issue_number'])<1):raise ValueError('invalid_issue_number')
        state.metadata.setdefault('report_parameters',{}).update(parameters)
        parameter_ref=store.put_artifact(task_id,'report_parameters',{'fact_ref':state.fact_ref,'parameters':state.metadata['report_parameters'],'source':'human_provided'})
        state.metadata['report_parameters_ref']=parameter_ref;allowed.add(parameter_ref)
        store.put_task(state,state.revision)
        report=FrozenReport(store,task_id)
        calculated,data_issues=data_values(template,report)
        merged.update(calculated)
        issues=[x for x in issues if x.get('field_id') not in {f['id'] for f in fields.values() if f['owner']=='data'}]+data_issues
    state=store.get_task(task_id)
    result=save_draft(store,state,template,merged,allowed,draft.get('chart_refs',{}),issues)
    from .reviewers import after_human_change
    after_human_change(store,task_id,expected_hash,set(values),resolved_issue_ids)
    store.append_event(task_id,{'type':'human_writing_correction','fields':list(values),'parameters':parameters,'previous_hash':expected_hash,'draft_ref':result.draft_ref})
    return {'draft_ref':result.draft_ref,'missing':result.metadata['missing_fields'],'preview_only':result.metadata['preview_only']}


def excerpt_locations(draft,issue):
    """Exact source locations; never guess which repeated quote to overwrite."""
    quote=issue.get('details',{}).get('quote','')
    value=draft.get('slot_values',{}).get(issue.get('details',{}).get('field_id'),{}).get('value')
    if not quote:return []
    paragraphs=[(None,value)] if isinstance(value,str) else list(enumerate(value)) if isinstance(value,list) else []
    locations=[]
    for index,paragraph in paragraphs:
        if not isinstance(paragraph,str):continue
        start=0
        while (at:=paragraph.find(quote,start))>=0:
            locations.append({'paragraph_index':index,'start':at,'end':at+len(quote)})
            start=at+len(quote)
    return locations


def edit_review_excerpt(store,task_id,issue_id,expected_hash,replacement,location=None):
    from .reviewers import active_issues
    state=store.get_task(task_id)
    if state.phase!='awaiting_final_review':raise ValueError('writing_review_not_at_human_stage')
    draft=store.get_artifact(state.draft_ref)
    if draft['content_hash']!=expected_hash:raise ValueError('stale_draft_hash')
    issue=next((i for i in active_issues(state) if i['id']==issue_id),None)
    if not issue:raise ValueError('writing_review_issue_not_available')
    field_id=issue['details']['field_id'];locations=excerpt_locations(draft,issue)
    if not locations:raise ValueError('review_excerpt_not_found')
    if location is None:
        if len(locations)!=1:raise ValueError('review_excerpt_location_required')
        location=locations[0]
    if location not in locations:raise ValueError('review_excerpt_location_changed')
    if not replacement.strip():raise ValueError('review_excerpt_empty')
    before=issue['details']['quote']
    if replacement==before:raise ValueError('review_excerpt_unchanged_use_retain')
    value=draft['slot_values'][field_id]['value'];index=location['paragraph_index']
    paragraph=value if index is None else value[index]
    revised=paragraph[:location['start']]+replacement+paragraph[location['end']:]
    if index is not None:
        revised_value=list(value);revised_value[index]=revised
    else:revised_value=revised
    result=edit_structured(store,task_id,{field_id:revised_value},expected_hash,resolved_issue_ids={issue_id})
    store.append_event(task_id,{'type':'human_review_excerpt_edit','issue_id':issue_id,'field_id':field_id,
        'location':location,'before':before,'after':replacement,'previous_hash':expected_hash,'draft_ref':result['draft_ref'],'model_called':False})
    return result
