"""dump b1c09b5b 模板任务状态 + 异常批 + 事件。"""
import json, urllib.request

BASE = 'http://127.0.0.1:8899'
tasks = json.loads(urllib.request.urlopen(BASE + '/api/tasks', timeout=30).read())
tid = next((t['id'] for t in tasks if t['id'].startswith('b1c09b5b')), None)
if not tid:
    print('NOT_FOUND'); raise SystemExit(1)

def get(p):
    return json.loads(urllib.request.urlopen(BASE + p, timeout=60).read())

state = get('/api/tasks/' + tid)
L = []
def p(*a): L.append(' '.join(str(x) for x in a))
p('id', state['id'], 'kind', state.get('kind'), 'phase', state.get('phase'), 'revision', state.get('revision'))
p('template_error:', json.dumps(state.get('metadata', {}).get('template_error'), ensure_ascii=False))
batches = state.get('metadata', {}).get('template_batches', {})
p('template_batches count:', len(batches))
for k, b in batches.items():
    p('  batch key=%s status=%s targets=%s rounds=%d' % (k[:30], b.get('status'), len(b.get('targets', [])), len(b.get('rounds', []))))
    for r in b.get('rounds', []):
        p('     round %s status=%s errors=%d' % (r.get('number'), r.get('status'), len(r.get('errors', []))))
        for e in r.get('errors', [])[:3]:
            p('        err:', json.dumps(e, ensure_ascii=False)[:160])
review_items = [i for i in state.get('review_items', []) if i.get('kind') == 'template_exception']
p('template_exception review_items:', json.dumps(review_items, ensure_ascii=False)[:500])

try:
    exc = get('/api/templates/' + tid + '/exceptions')
    p('')
    p('===== /api/templates/{id}/exceptions =====')
    p('revision', exc.get('revision'), 'phase', exc.get('phase'), 'maximum_rounds', exc.get('maximum_rounds'))
    p('available_bindings:', json.dumps(exc.get('available_bindings'), ensure_ascii=False)[:300])
    for b in exc.get('batches', []):
        p('  batch id=%s targets=%d rounds=%d candidate_keys=%s' % (b.get('id'), len(b.get('targets', [])), len(b.get('rounds', [])), list((b.get('candidate') or {}).keys())))
        c = b.get('candidate') or {}
        p('    candidate has blocks=%d fields=%d' % (len(c.get('blocks', [])), len(c.get('fields', []))))
except Exception as e:
    p('exceptions fetch error:', type(e).__name__, str(e)[:200])

events = get('/api/tasks/' + tid + '/logs')
p('')
p('===== 关键事件 =====')
for e in events:
    t = e.get('type')
    if t in ('template_round_started', 'template_round_passed', 'template_validation_error', 'template_human_correction', 'phase'):
        p('  %s %s' % (t, json.dumps({k: v for k, v in e.items() if k not in ('type','seq','at')}, ensure_ascii=False)[:220]))

with open('data/_task_b1c09b5b.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(L))
print('WROTE data/_task_b1c09b5b.txt  phase=%s' % state.get('phase'))
