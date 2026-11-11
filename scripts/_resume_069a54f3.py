"""触发 069a54f3 resume，轮询至闭环（awaiting_review）或再次卡住（analysis_pending）。"""
import json, time, urllib.request, urllib.error

BASE = 'http://127.0.0.1:8899'
TASK = '069a54f39c3a42faad7457f24b64aac3'

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=90) as r:
        return json.load(r)

def post(path):
    req = urllib.request.Request(BASE + path, method='POST', data=b'{}', headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)

before = get('/api/tasks/' + TASK)
max_seq = (get('/api/tasks/' + TASK + '/events?limit=1') or [{}])[0].get('seq', 0)

try:
    post('/api/tasks/' + TASK + '/resume')
except urllib.error.HTTPError as e:
    print('RESUME_HTTP_ERROR', e.code, e.read().decode('utf-8', 'replace')[:200]); raise SystemExit(1)

start = time.time()
transitions = []
last = None
final = None
deadline = time.time() + 1500
while time.time() < deadline:
    t = get('/api/tasks/' + TASK)
    if t['phase'] != last:
        last = t['phase']
        transitions.append((round(time.time()-start), last, t['revision']))
    final = t['phase']
    if final in ('awaiting_review', 'analysis_pending', 'failed', 'cancelled'):
        break
    time.sleep(4)

time.sleep(2)
t = get('/api/tasks/' + TASK)
events = get('/api/tasks/' + TASK + '/logs')
new_events = [e for e in events if e.get('seq', 0) > max_seq]
urlerrs = [e for e in new_events if e.get('type') == 'model_request_error']
model_errors = [e for e in new_events if e.get('type') == 'model_call' and e.get('status') == 'error']
progress = [e for e in new_events if e.get('type') == 'event_analysis_progress']

ea = None
if t.get('result_refs', {}).get('event_analysis'):
    try:
        ea = get('/api/artifacts/' + t['result_refs']['event_analysis'])
    except Exception:
        pass

print('phase_transitions:', transitions)
print('final_phase:', final, 'revision:', t.get('revision'))
print('new_events:', len(new_events), 'urlerrors:', len(urlerrs), 'model_errors:', len(model_errors))
print('progress:', [(p.get('stage'), p.get('completed')) for p in progress])
if urlerrs:
    for e in urlerrs[:5]:
        print('  URLError:', e.get('role'), e.get('error'))
if model_errors:
    for e in model_errors[:5]:
        print('  model_error:', e.get('role'), e.get('error'))
if ea:
    print('event_analysis.pending_model:', ea.get('pending_model'))
    print('event_analysis.failures:', ea.get('failures'))
    c = ea.get('counts', {})
    print('counts:', json.dumps(c, ensure_ascii=False))
    print('top10_status:', [r.get('status') for r in ea.get('top10', [])])
print('DONE final=', final)
