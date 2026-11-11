"""dump 模板 27c9375d 完整字段 + 块结构。"""
import json, urllib.request

BASE = 'http://127.0.0.1:8899'
tasks = json.loads(urllib.request.urlopen(BASE + '/api/tasks', timeout=30).read())
tid = next((t['id'] for t in tasks if t['id'].startswith('68265911')), None)
state = json.loads(urllib.request.urlopen(BASE + '/api/tasks/' + tid, timeout=60).read())
tmpl = json.loads(urllib.request.urlopen(BASE + '/api/artifacts/' + state['template_ref'], timeout=60).read())

L = []
def p(*a): L.append(' '.join(str(x) for x in a))

p('template_ref', state['template_ref'], 'status', tmpl.get('status'), 'version', tmpl.get('version'))
p('template keys:', sorted(tmpl.keys()))
p('rules:', json.dumps(tmpl.get('rules'), ensure_ascii=False))
p('')
p('===== 全部字段 (%d) =====' % len(tmpl.get('fields', [])))
for f in tmpl.get('fields', []):
    p('  [%s] %s | owner=%s kind=%s binding=%s | schema=%s' % (
        f.get('id'), f.get('display_name'), f.get('owner'), f.get('kind'),
        json.dumps(f.get('binding'), ensure_ascii=False)[:60],
        json.dumps(f.get('value_schema'), ensure_ascii=False)[:80]))
    if f.get('rule'):
        p('       rule=%s' % f['rule'][:120])
    if f.get('format'):
        p('       format=%s' % f['format'][:120])

p('')
p('===== 块结构 (%d) =====' % len(tmpl.get('blocks', [])))
for b in tmpl.get('blocks', []):
    parts = []
    for part in b.get('parts', []):
        if 'field' in part: parts.append('{{%s}}' % part.get('field'))
        else: parts.append(repr((part.get('text') or '')[:20]))
    p('  block %s kind=%s parts=%s' % (b.get('index'), b.get('kind'), ' '.join(parts)))
    if b.get('kind') == 'table':
        p('       headers=%s' % json.dumps(b.get('headers'), ensure_ascii=False))

with open('data/_template_27c9375d.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(L))
print('WROTE data/_template_27c9375d.txt')
