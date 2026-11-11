"""查 fc49316f 任务事件日志：phase 流转 + 模型错误 + 分析进度。"""
import json, urllib.request
from collections import Counter

BASE = 'http://127.0.0.1:8899'
def get(p): return json.loads(urllib.request.urlopen(BASE + p, timeout=60).read())

tasks = get('/api/tasks')
tid = next((t['id'] for t in tasks if t['id'].startswith('fc49316f')), None)
if not tid:
    print('NOT_FOUND'); raise SystemExit(1)

events = get('/api/tasks/' + tid + '/logs')
L = []
def p(*a): L.append(' '.join(str(x) for x in a))

p('task', tid)
p('')
p('===== phase 流转 =====')
for e in events:
    if e.get('type') == 'phase':
        p('  phase -> %s' % e.get('phase'))

p('')
p('===== 模型错误 =====')
errs = [e for e in events if e.get('type') == 'model_call' and e.get('status') == 'error']
p('model_call error 次数:', len(errs), dict(Counter(e.get('role') for e in errs)))
for e in errs:
    p('  role=%s error=%s reason=%s' % (e.get('role'), e.get('error'), e.get('reason')))

p('')
p('===== 分析进度（event_analysis_progress） =====')
prog = [e for e in events if e.get('type') == 'event_analysis_progress']
for e in prog:
    p('  stage=%s completed=%s' % (e.get('stage'), e.get('completed')))

p('')
p('===== 纠偏/重试事件 =====')
for e in events:
    t = e.get('type')
    if t in ('classification_output_correction', 'review_output_correction', 'writer_repair_validation_retry'):
        p('  %s %s' % (t, json.dumps({k: v for k, v in e.items() if k not in ('type','seq','at')}, ensure_ascii=False)[:200]))

with open('data/_fc49316f_events.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(L))
print('WROTE data/_fc49316f_events.txt  events=%d' % len(events))
