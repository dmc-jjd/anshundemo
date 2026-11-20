"""Evidence-backed agent notes; never confirms a template or resolves user decisions."""
import copy
import hashlib
import json
from datetime import datetime, timezone

def _hash(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def _fingerprint(definition):
    return _hash({key:definition.get(key) for key in ('fields','blocks','rules','writer_schema')})

def status_for(definition,questions,metadata):
    fingerprint=_fingerprint(definition)
    saved=metadata.get('agent_review_dispositions',{})
    result={}
    sources=[('opinions','opinion',definition.get('human_review_items') or []),('business','business',questions)]
    for section,kind,items in sources:
        rows=[]
        for index,item in enumerate(items):
            identity=_hash(item) if kind=='opinion' else item['id']
            record=saved.get(kind+':'+identity,{})
            current=record.get('definition_hash')==fingerprint
            state=record.get('status','pending') if current else ('stale' if record else 'pending')
            rows.append({'id':identity,'index':index,'status':state,'note':record.get('note',''),
                         'evidence':record.get('evidence',''),'answer':record.get('answer','') if current else '',
                         'updated_at':record.get('updated_at')})
        result[section]={'total':len(rows),'addressed':sum(row['status']=='addressed' for row in rows),'items':rows}
    return result

def normalize_review_targets(definition):
    """Keep model advice locatable after a dynamic field replaces legacy slots."""
    fields={f['id']:f for f in definition.get('fields',[])}
    dynamic=next((f for f in fields.values() if f.get('category_coverage_scope')),None)
    if not dynamic:return definition
    for item in definition.get('human_review_items') or []:
        if item.get('field_id') in fields:continue
        if item.get('field_id') in ('b27_item','b28_item') or '类别' in str(item.get('message','')):
            item['legacy_field_id']=item.get('field_id');item['field_id']=dynamic['id'];item['target_block']=dynamic.get('block')
    return definition

def record_dispositions(definition,questions,metadata,entries):
    available=status_for(definition,questions,metadata)
    allowed={('opinion',row['id']) for row in available['opinions']['items']}|{('business',row['id']) for row in available['business']['items']}
    saved=copy.deepcopy(metadata.get('agent_review_dispositions',{}))
    for entry in entries:
        if (entry['kind'],entry['id']) not in allowed:raise ValueError('unknown_review_disposition')
        if entry['status'] not in ('addressed','pending','needs_user'):raise ValueError('invalid_review_disposition_status')
        if not entry.get('note','').strip():raise ValueError('review_disposition_note_required')
        if entry['status']=='addressed' and not entry.get('evidence','').strip():raise ValueError('review_disposition_evidence_required')
        saved[entry['kind']+':'+entry['id']]={**entry,'definition_hash':_fingerprint(definition),'updated_at':datetime.now(timezone.utc).isoformat()}
    metadata['agent_review_dispositions']=saved

def rebase_addressed_dispositions(definition,metadata):
    """Keep completed agent opinions completed when a user edits the candidate draft."""
    saved=metadata.get('agent_review_dispositions') or {}
    if not saved:return
    fingerprint=_fingerprint(definition)
    for key,record in saved.items():
        if isinstance(record,dict) and record.get('kind')=='opinion' and record.get('status')=='addressed':
            record['definition_hash']=fingerprint
