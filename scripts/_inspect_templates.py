"""列出所有「3份报告」结构化模板 + 创建时间 + 内容特征对比。"""
import json, urllib.request

BASE = 'http://127.0.0.1:8899'
def get(p):
    return json.loads(urllib.request.urlopen(BASE + p, timeout=60).read())

tasks = get('/api/tasks')
L = []
def p(*a): L.append(' '.join(str(x) for x in a))

p('===== 全部任务中的模板任务 =====')
tmpl_tasks = [t for t in tasks if t.get('kind') == 'template']
p('模板任务数:', len(tmpl_tasks))

# 找到所有 confirmed 模板，按 source_reports 数量分类
confirmed = []
for t in tmpl_tasks:
    ref = None
    # 从 /api/tasks/{id} 拿完整 state 才能读到 metadata.confirmed_template_ref
    st = get('/api/tasks/' + t['id'])
    ref = st.get('metadata', {}).get('confirmed_template_ref')
    if not ref:
        continue
    try:
        art = get('/api/artifacts/' + ref)
    except Exception as e:
        continue
    n = len(art.get('source_reports', []))
    confirmed.append({'task_id': t['id'], 'created_at': st.get('created_at'), 'phase': st.get('phase'),
                      'ref': ref, 'n_sources': n, 'art': art})

p('')
p('===== confirmed 模板（按来源报告数） =====')
for c in confirmed:
    p('  来源数=%d  task=%s created=%s ref=%s version=%s' % (c['n_sources'], c['task_id'][:12], c['created_at'], c['ref'], c['art'].get('version')))

p('')
p('===== 「3份报告」模板详情与差异 =====')
three = [c for c in confirmed if c['n_sources'] == 3]
p('共 %d 个' % len(three))
for i, c in enumerate(three):
    art = c['art']
    fields = art.get('fields', [])
    blocks = art.get('blocks', [])
    rules = art.get('rules', {})
    p('')
    p('--- 模板 #%d ---' % (i + 1))
    p('  task_id      = %s' % c['task_id'])
    p('  created_at   = %s' % c['created_at'])
    p('  ref          = %s' % c['ref'])
    p('  version      = %s   status=%s' % (art.get('version'), art.get('status')))
    p('  fields       = %d 个' % len(fields))
    p('  blocks       = %d 个' % len(blocks))
    p('  rules        = %s' % json.dumps(rules, ensure_ascii=False))
    p('  human_reason = %s' % (art.get('human_reason') or '')[:120])
    src_names = [s.get('name') or s.get('path') for s in art.get('source_reports', [])]
    p('  来源报告文件 = %s' % json.dumps(src_names, ensure_ascii=False)[:300])
    p('  field ids    = %s' % json.dumps([f.get('id') for f in fields], ensure_ascii=False))
    p('  block indexes= %s' % json.dumps([b.get('index') for b in blocks], ensure_ascii=False))

with open('data/_templates_3reports.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(L))
print('WROTE data/_templates_3reports.txt  confirmed=%d three=%d' % (len(confirmed), len(three)))
