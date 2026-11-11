"""dump 68265911 报告任务：状态 + 模板字段(b26/b35/b40) + 草稿值 + 失败日志。"""
import json, urllib.request
from collections import Counter

BASE = 'http://127.0.0.1:8899'
tasks = json.loads(urllib.request.urlopen(BASE + '/api/tasks', timeout=30).read())
tid = next((t['id'] for t in tasks if t['id'].startswith('68265911')), None)
if not tid:
    print('NOT_FOUND'); raise SystemExit(1)

def get(p):
    return json.loads(urllib.request.urlopen(BASE + p, timeout=90).read())

state = get('/api/tasks/' + tid)
L = []
def p(*a): L.append(' '.join(str(x) for x in a))

p('===== 任务 =====')
p('id', state['id'], 'kind', state.get('kind'), 'phase', state.get('phase'), 'revision', state.get('revision'))
p('template_ref', state.get('template_ref'), 'draft_ref', state.get('draft_ref'))
p('missing_fields:', state.get('metadata', {}).get('missing_fields'))
p('preview_only:', state.get('metadata', {}).get('preview_only'))
wi = state.get('metadata', {}).get('writer_issues', [])
p('writer_issues (%d):' % len(wi))
for i in wi:
    p('  -', json.dumps(i, ensure_ascii=False)[:300])

# 模板
tmpl_ref = state.get('template_ref')
if tmpl_ref:
    try:
        tmpl = get('/api/artifacts/' + tmpl_ref)
        p('')
        p('===== 模板字段 (b26/b35/b40) =====')
        for f in tmpl.get('fields', []):
            fid = f.get('id', '')
            if fid.startswith(('b26_', 'b35_', 'b40_')):
                p('  [%s] name=%s owner=%s kind=%s binding=%s' % (fid, f.get('display_name'), f.get('owner'), f.get('kind'), json.dumps(f.get('binding'), ensure_ascii=False)))
                p('       value_schema=%s' % json.dumps(f.get('value_schema'), ensure_ascii=False)[:200])
    except Exception as e:
        p('template fetch error:', type(e).__name__, str(e)[:200])

# 草稿
draft_ref = state.get('draft_ref')
if draft_ref:
    try:
        draft = get('/api/artifacts/' + draft_ref)
        p('')
        p('===== 草稿 slot_values (b26/b35/b40) =====')
        sv = draft.get('slot_values', {})
        for k in sorted(sv):
            if k.startswith(('b26_', 'b35_', 'b40_')):
                v = sv[k].get('value')
                vs = json.dumps(v, ensure_ascii=False)
                p('  [%s] %s' % (k, vs[:240]))
    except Exception as e:
        p('draft fetch error:', type(e).__name__, str(e)[:200])

# 事件
p('')
p('===== 事件日志分析 =====')
events = get('/api/tasks/' + tid + '/logs')
errs = [e for e in events if e.get('type') == 'model_call' and e.get('status') == 'error']
p('model_call error 次数:', len(errs))
role_counter = Counter(e.get('role') for e in errs)
p('按角色:', dict(role_counter))
reason_counter = Counter(e.get('reason') for e in errs)
p('按原因:', dict(reason_counter))
p('错误样例（按角色）:')
seen = set()
for e in errs:
    key = e.get('role')
    if key in seen: continue
    seen.add(key)
    p('  role=%s error=%s reason=%s' % (e.get('role'), e.get('error'), e.get('reason')))

corr = [e for e in events if e.get('type') in ('writer_repair_validation_retry', 'review_output_correction', 'classification_output_correction')]
p('纠偏/校验重试事件 (%d):' % len(corr))
for e in corr[-12:]:
    p('  %s %s' % (e.get('type'), json.dumps({k: v for k, v in e.items() if k not in ('type','seq','at')}, ensure_ascii=False)[:180]))

swr = [e for e in events if e.get('type') == 'structured_writer_result']
if swr:
    last = swr[-1]
    p('最近 structured_writer_result: filled=%d missing=%d' % (len(last.get('filled', [])), len(last.get('missing', []))))
    p('  missing:', last.get('missing'))

with open('data/_task_68265911.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(L))
print('WROTE data/_task_68265911.txt  phase=%s' % state.get('phase'))
