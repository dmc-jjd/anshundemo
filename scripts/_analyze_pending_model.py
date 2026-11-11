"""分析数据处理阶段 pending_model 的原因：查最近报告任务的 event_analysis 工件。"""
import json, urllib.request
from collections import Counter

BASE = 'http://127.0.0.1:8899'
def get(p): return json.loads(urllib.request.urlopen(BASE + p, timeout=60).read())

tasks = get('/api/tasks')
L = []
def p(*a): L.append(' '.join(str(x) for x in a))

reports = [t for t in tasks if t.get('kind') == 'report']
p('===== 报告任务（按时间倒序，最多 8 个） =====')
for t in reports[:8]:
    st = get('/api/tasks/' + t['id'])
    p('  %s  phase=%s created=%s' % (t['id'][:12], st.get('phase'), st.get('created_at')))

# 逐个检查 event_analysis 工件
p('')
p('===== event_analysis 详情 =====')
for t in reports[:8]:
    st = get('/api/tasks/' + t['id'])
    ea_ref = st.get('result_refs', {}).get('event_analysis')
    if not ea_ref:
        p('  %s: 无 event_analysis 工件' % t['id'][:12])
        continue
    try:
        ea = get('/api/artifacts/' + ea_ref)
    except Exception as e:
        p('  %s: 工件读取失败 %s' % (t['id'][:12], type(e).__name__))
        continue
    p('  --- %s (phase=%s) ---' % (t['id'][:12], st.get('phase')))
    p('    pending_model=%s' % ea.get('pending_model'))
    p('    failures(%d):' % len(ea.get('failures', [])))
    for f in ea.get('failures', [])[:6]:
        p('      %s' % json.dumps(f, ensure_ascii=False)[:160])
    c = ea.get('counts', {})
    p('    counts=%s' % json.dumps(c, ensure_ascii=False))
    themes = ea.get('theme_groups', [])
    unproc = [g for g in themes if g.get('candidate_theme') == '模型尚未处理']
    p('    theme_groups=%d 其中「模型尚未处理」=%d' % (len(themes), len(unproc)))
    top10 = ea.get('top10', [])
    p('    top10 状态: %s' % Counter(r.get('status') for r in top10))
    p('    merge_ambiguities=%d classification_issues=%d' % (len(ea.get('merge_ambiguities', [])), len(ea.get('classification_issues', []))))

with open('data/_pending_model_analysis.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(L))
print('WROTE data/_pending_model_analysis.txt')
