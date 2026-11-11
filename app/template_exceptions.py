"""Read and validate human corrections without bypassing template checks."""
from pathlib import Path
from .template_validation import collect_errors
from .timing import stamp


def exception_view(store,state):
    ref=state.metadata.get('template_input_ref')
    if not ref:raise ValueError('template_input_missing')
    packet=store.get_artifact(ref);batches=[]
    for key,batch in state.metadata.get('template_batches',{}).items():
        if batch['status']!='human_required':continue
        rounds=[{**entry,'response':store.get_artifact(entry['response_ref']) if entry.get('response_ref') else None}
                for entry in batch['rounds']]
        raw=next((r['response'] for r in reversed(rounds) if r['response'] is not None),None)
        batches.append({'id':key,'targets':batch['targets'],'rounds':rounds,'candidate':raw})
    return {'revision':state.revision,'phase':state.phase,'input_ref':ref,'maximum_rounds':3,'batches':batches,'available_bindings':packet['available_bindings'],
            'sources':[{'id':d['id'],'name':Path(d['path']).name,'blocks':d['blocks']} for d in packet['source_reports']]}


def correct_batch(store,state,key,raw,reason):
    batch=state.metadata.get('template_batches',{}).get(key)
    if state.phase!='template_manual_review' or not batch or batch['status']!='human_required':
        raise ValueError('template_exception_not_open')
    if not reason.strip():raise ValueError('template_correction_reason_required')
    packet=store.get_artifact(state.metadata['template_input_ref'])
    issues=collect_errors(raw,packet,state.metadata['comparison_ref'],None if key=='all' else batch['targets'])
    if issues:return issues
    ref=store.put_artifact(state.id,'template_human_correction',raw)
    batch.update(status='human_corrected',human_correction={'response_ref':ref,'reason':reason,'at':stamp(),'actor':'local-operator'})
    state.metadata['template_review_checkpoints'][key]=ref
    pending=any(b['status']=='human_required' for b in state.metadata['template_batches'].values())
    state.phase='template_manual_review' if pending else 'queued'
    if not pending:
        state.review_items=[i for i in state.review_items if i['kind']!='template_exception']
        state.metadata.pop('template_error',None)
    store.put_task(state,state.revision)
    store.append_event(state.id,{'type':'template_human_correction','batch':key,'response_ref':ref,'reason':reason})
    return []
