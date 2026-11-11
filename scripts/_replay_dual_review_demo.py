"""一次性演示：对历史任务重跑双审流程，dump phase 流转 + 新事件 + 终态到 JSON。"""
import json, time, urllib.request, urllib.error

BASE = 'http://127.0.0.1:8899'
TASK = 'd2511637eb694125a92616d2a276bd08'

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=90) as r:
        return json.load(r)

def post(path, payload=None):
    data = json.dumps(payload or {}).encode() if payload is not None else b'{}'
    req = urllib.request.Request(BASE + path, method='POST', data=data,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)

task_before = get('/api/tasks/' + TASK)
events_before = get('/api/tasks/' + TASK + '/events?limit=1')
max_seq_before = events_before[0]['seq'] if events_before else 0

trigger_error = None
try:
    trigger = post('/api/tasks/' + TASK + '/preview-draft')
except urllib.error.HTTPError as e:
    trigger_error = {'status': e.code, 'body': e.read().decode('utf-8', 'replace')}

transitions = []
start = time.time()
last_phase = None
deadline = time.time() + 900
final_phase = None
while time.time() < deadline:
    try:
        t = get('/api/tasks/' + TASK)
    except Exception as e:
        time.sleep(2)
        continue
    if t['phase'] != last_phase:
        last_phase = t['phase']
        transitions.append({'elapsed_s': round(time.time() - start, 1), 'phase': last_phase, 'revision': t['revision']})
    final_phase = t['phase']
    if final_phase in ('awaiting_final_review', 'cancelled', 'failed', 'facts_frozen'):
        break
    time.sleep(2)

# 让收尾事件落盘
time.sleep(2)
task_after = get('/api/tasks/' + TASK)
new_events = get('/api/tasks/' + TASK + '/events?after=' + str(max_seq_before))

out = {
    'task_id': TASK,
    'max_seq_before': max_seq_before,
    'task_before': task_before,
    'trigger': trigger if not trigger_error else None,
    'trigger_error': trigger_error,
    'phase_transitions': transitions,
    'task_after': task_after,
    'new_events': new_events,
}
path = 'data/_dual_review_replay_result.json'
with open(path, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2, default=str)
print('DONE final_phase=%s new_events=%d transitions=%d' % (final_phase, len(new_events), len(transitions)))
