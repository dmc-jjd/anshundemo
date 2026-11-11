"""dump 68265911 模型错误 + 失败调用的原始响应。"""
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
events = get('/api/tasks/' + tid + '/logs')

L = []
def p(*a): L.append(' '.join(str(x) for x in a))

p('task', tid, 'phase', state.get('phase'))

# 模型错误统计
errs = [e for e in events if e.get('type') == 'model_call' and e.get('status') == 'error']
p('')
p('===== model_call error 统计 (%d) =====' % len(errs))
p('按角色:', dict(Counter(e.get('role') for e in errs)))
p('按 error:', dict(Counter(e.get('error') for e in errs)))
p('按 reason:', dict(Counter(e.get('reason') for e in errs)))

# 图节点轮次
nodes = [e for e in events if e.get('type') == 'graph_node']
p('')
p('===== 图节点轮次 =====')
review_nodes = {}
for e in nodes:
    n = e.get('node')
    if n in ('format_review', 'content_review', 'final_format_review', 'revise_draft', 'local_validation', 'style_detection'):
        review_nodes.setdefault(n, []).append(e.get('status'))
for n, sts in review_nodes.items():
    p('  %s: %d 次 %s' % (n, len(sts), Counter(sts)))

# 双审结果
reviews = [e for e in events if e.get('type') == 'writing_review']
p('')
p('===== writing_review 结果 (%d) =====' % len(reviews))
for e in reviews:
    p('  %s 第%s轮 status=%s 意见数=%s' % (e.get('reviewer'), e.get('round'), e.get('status'), e.get('issue_count')))

# 取 1 个失败调用对应的 model_exchange 看原始响应
p('')
p('===== 失败调用原始响应（model_exchange 工件） =====')
seen = set()
for e in events:
    if e.get('type') == 'model_exchange' and e.get('role') in seen:
        continue
    if e.get('type') == 'model_exchange':
        seen.add(e.get('role'))
        try:
            ex = get('/api/artifacts/' + e.get('ref'))
            resp = ex.get('response') or {}
            choices = resp.get('choices') or []
            if choices:
                msg = choices[0].get('message') or {}
                p('  role=%s finish_reason=%s content_len=%d reasoning_content_len=%d' % (
                    e.get('role'), choices[0].get('finish_reason'),
                    len(msg.get('content') or ''), len(msg.get('reasoning_content') or '')))
                p('     content前120字: %r' % (msg.get('content') or '')[:120])
                p('     reasoning_content前120字: %r' % (msg.get('reasoning_content') or '')[:120])
            else:
                p('  role=%s 无 choices: %r' % (e.get('role'), str(resp)[:200]))
        except Exception as exc:
            p('  role=%s fetch err %s' % (e.get('role'), type(exc).__name__))

with open('data/_task_68265911_errors.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(L))
print('WROTE data/_task_68265911_errors.txt  errors=%d' % len(errs))
