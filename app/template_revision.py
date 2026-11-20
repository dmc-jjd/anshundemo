"""Derive an editable candidate from a confirmed template without running models."""
import copy
import hashlib
import uuid
from pathlib import Path
from core.schemas import TaskState
from core.structured_template import load_confirmed_template
from .template_review import digest

REVISION_POLICY='CONFIRMED-REVISION-1'

def derive(store,source_id,expected_revision,name,reason,request_key):
    source=store.get_task(source_id)
    if source.kind!='template' or not source.metadata.get('confirmed_template_ref'):raise ValueError('confirmed_template_required')
    ref=source.metadata['confirmed_template_ref'];template=load_confirmed_template(store,ref)
    for report in template['source_reports']:
        if hashlib.sha256(Path(report['path']).read_bytes()).hexdigest()!=report['sha256']:raise ValueError('template_source_changed')
    if not name.strip() or not reason.strip() or not request_key.strip():raise ValueError('revision_name_reason_key_required')
    task=TaskState(id=uuid.uuid4().hex,package=source.package,kind='template',phase='awaiting_template_confirmation',input_refs=list(source.input_refs))
    key='template_revision:'+source_id+':'+request_key
    with store._artifact_transaction() as (conn,created):
        prior=conn.execute('SELECT value FROM idempotency WHERE key=?',(key,)).fetchone()
        if prior:
            row=conn.execute('SELECT state FROM tasks WHERE id=?',(prior['value'],)).fetchone()
            if row:return TaskState.model_validate_json(row['state'])
            raise ValueError('revision_idempotency_target_missing')
        row=conn.execute('SELECT revision FROM tasks WHERE id=?',(source_id,)).fetchone()
        if not row or row['revision']!=expected_revision:raise ValueError('stale_template_revision')
        candidate=copy.deepcopy(template)
        for k in ('version','human_reason','human_resolutions','business_decisions','template_validation_ref'):candidate.pop(k,None)
        candidate.update(status='candidate',name=name.strip(),revision_source={'task_id':source_id,'template_ref':ref,'template_hash':digest(template),'reason':reason.strip()})
        meta={k:copy.deepcopy(source.metadata[k]) for k in ('comparison_ref','template_input_ref') if source.metadata.get(k)}
        if not all(k in meta for k in ('comparison_ref','template_input_ref')):raise ValueError('revision_source_evidence_missing')
        meta['template_name']=name.strip();meta['revision_source']=candidate['revision_source']
        meta['structured_template_ref']=store._put_artifact(conn,created,task.id,'structured_template_candidate',candidate)
        validation={'source':'confirmed_template_revision','policy_version':REVISION_POLICY,'validation':'passed',
                    'candidate_ref':meta['structured_template_ref'],'candidate_hash':digest(candidate),'input_ref':meta['template_input_ref'],
                    'input_hash':digest(store.get_artifact(meta['template_input_ref'])),'review_refs':[ref],
                    'note':'从人工确认模板派生；本次未重新调用模型，仍须人工审阅确认。'}
        meta['template_validation_ref']=store._put_artifact(conn,created,task.id,'template_validation',validation)
        task.metadata=meta
        conn.execute('INSERT INTO tasks VALUES(?,?,?)',(task.id,task.model_dump_json(),task.revision))
        conn.execute('INSERT INTO idempotency VALUES(?,?)',(key,task.id))
    return task

def valid_revision_source(store,state,candidate):
    source=state.metadata.get('revision_source') or {}
    if candidate.get('revision_source')!=source:return False
    try:
        old=store.get_task(source['task_id'])
        template=load_confirmed_template(store,source['template_ref'])
        return (old.metadata.get('confirmed_template_ref')==source['template_ref'] and digest(template)==source['template_hash']
                and candidate.get('source_reports')==template.get('source_reports')
                and state.metadata.get('template_input_ref')==old.metadata.get('template_input_ref'))
    except (KeyError,ValueError):return False
