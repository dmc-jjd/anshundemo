"""Read-only candidate handoff check. No writes, model calls or template confirmation."""
import argparse
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

AREAS=('history_structure','list_lengths_numbering','optional_sections','data_bindings',
       'field_relations','writer_requests','preview_export','shared_package_compatibility')
FINAL=('verified','not_adopted')
OPEN=('open','awaiting_user','awaiting_implementation','in_progress')

def evaluate(task,view,draft,ledger,root):
    errors=[];actions=[];root=Path(root)
    def error(message):errors.append(message)
    def evidence(row,label):
        paths=row.get('evidence')
        if not isinstance(paths,list) or not paths:
            error(label+': evidence files required');return
        for value in paths:
            if not isinstance(value,str):error(label+': invalid evidence path');continue
            path=Path(value)
            if not path.is_absolute():path=root/path
            if not path.is_file() or path.stat().st_size==0:error(label+': missing or empty evidence '+str(path))
    if task.get('kind')!='template' or task.get('metadata',{}).get('simulation'):
        error('real template task required')
    if task.get('metadata',{}).get('confirmed_template_ref'):
        error('template already confirmed: use confirmed-template verification, do not edit it')
    if task.get('phase')!='awaiting_template_confirmation':error('candidate is not awaiting template confirmation')
    if not ledger:error('review ledger missing: inspect, triage and record actual work first')
    for key,value in [('package',task.get('package')),('task_id',task.get('id')),('candidate_ref',view.get('artifact_ref')),('draft_ref',draft.get('draft_ref'))]:
        if key not in ledger or ledger.get(key)!=value:error('ledger identity is missing or stale: '+key)
    definition=view.get('definition') or {}
    if view.get('model_review_validated') is not True:error('model review validation unavailable')
    fields=definition.get('fields') or []
    writer_ids={f['id'] for f in fields if f.get('owner')=='writer'}
    if not isinstance(definition.get('writer_schema'),dict) or set(definition['writer_schema'].get('properties',{}))!=writer_ids:
        error('writer schema does not match effective writer fields')
    features=(definition.get('rules') or {}).get('features',{})
    if any(type(features.get(k)) is not bool for k in ('dedup','classification','first_warning','top10')):
        error('four processing features require explicit saved choices')
    decisions=ledger.get('feature_decisions')
    if not isinstance(decisions,dict) or any(type(decisions.get(k)) is not bool or decisions.get(k)!=features.get(k) for k in ('dedup','classification','first_warning','top10')):
        error('saved processing features do not match recorded user decisions')
    if 'binding_status' not in draft:error('effective data binding check unavailable')
    elif draft['binding_status'].get('pending'):error('data fields still need bindings')
    statuses=view.get('agent_review_status')
    if not isinstance(statuses,dict):error('agent review status unavailable: verify deployed code before handoff')
    expected={}
    for section,kind in [('opinions','opinion'),('business','business')]:
        for row in (statuses or {}).get(section,{}).get('items',[]):
            expected[(kind,row['id'])]=row
            if row.get('status')!='addressed':error(kind+': current API disposition is '+str(row.get('status')))
            if kind=='business' and not row.get('answer'):error('business decision has no saved user answer: '+row['id'])
    def rows(key):
        values=ledger.get(key)
        if not isinstance(values,list):error('ledger '+key+' must be a list');return []
        valid=[]
        for value in values:
            if not isinstance(value,dict):error('ledger '+key+' row must be an object')
            else:valid.append(value)
        return valid
    seen=set()
    for row in rows('issues'):
        identity=(row.get('kind'),row.get('id'));label='issue '+str(identity)
        if identity in seen:error(label+': duplicate')
        seen.add(identity)
        if identity[0] not in ('opinion','business','finding') or not identity[1]:error(label+': invalid identity')
        if identity[0]!='finding' and identity not in expected:error(label+': obsolete opinion or business question')
        state=row.get('status')
        if state in FINAL:
            if not row.get('decision_basis'):error(label+': decision_basis required')
            evidence(row,label)
        elif state in OPEN:
            error(label+': unresolved '+state)
            action=row.get('next_action') or {}
            if action.get('kind') not in ('ask_user','implement','handoff_extension','verify'):
                error(label+': actionable next_action required')
            elif not action.get('question' if action['kind']=='ask_user' else 'description'):
                error(label+': concrete next_action content required')
            else:actions.append({'issue':identity[1],**action})
        else:error(label+': invalid status')
    for identity in expected:
        if identity not in seen:error('current review item missing from ledger: '+str(identity))
    coverage={}
    for row in rows('coverage'):
        area=row.get('area')
        if area in coverage:error('duplicate coverage: '+str(area))
        coverage[area]=row
    for area in AREAS:
        row=coverage.get(area)
        if not row:error('historical coverage missing: '+area);continue
        if row.get('status') not in ('verified','not_applicable'):error('historical coverage unresolved: '+area)
        if not row.get('reason'):error('coverage reason required: '+area)
        evidence(row,'coverage '+area)
    return {'package':task.get('package'),'task_id':task.get('id'),'candidate_ref':view.get('artifact_ref'),
            'revision':view.get('revision'),'ready_for_user_confirmation':not errors,'errors':errors,'next_actions':actions,
            'limits':'Checks identities, recorded completion and evidence file presence; does not certify the truth of evidence or replace user business review.'}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',required=True)
    parser.add_argument('--task-id',required=True)
    parser.add_argument('--ledger',type=Path,required=True)
    parser.add_argument('--api-base',default='http://127.0.0.1:8765')
    parser.add_argument('--require-ready',action='store_true')
    args=parser.parse_args(argv)
    root=Path(__file__).resolve().parents[4]
    def get(path):
        request=urllib.request.Request(args.api_base.rstrip('/')+path,headers={'X-Report-Package':args.package})
        with urllib.request.urlopen(request,timeout=15) as response:return json.load(response)
    try:
        task=get('/api/tasks/'+args.task_id)
        if task.get('package')!=args.package:raise ValueError('task package mismatch')
        view=get('/api/templates/'+args.task_id+'/definition')
        if task.get('metadata',{}).get('confirmed_template_ref'):
            draft={'draft_ref':None}
        else:draft=get('/api/templates/'+args.task_id+'/draft')
        ledger=json.loads(args.ledger.read_text(encoding='utf-8-sig')) if args.ledger.is_file() else {}
        if not isinstance(ledger,dict):raise ValueError('review ledger must be a JSON object')
        result=evaluate(task,view,draft,ledger,root)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 2 if args.require_ready and not result['ready_for_user_confirmation'] else 0
    except (OSError,ValueError,TypeError,KeyError) as exc:
        print(json.dumps({'ready_for_user_confirmation':False,'error':str(exc)},ensure_ascii=False))
        return 2

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
