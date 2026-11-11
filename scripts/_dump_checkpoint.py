"""dump fc49316f 的 checkpoint 与 event_analysis，看 briefs/classes/remaining。"""
import json, urllib.request

BASE = 'http://127.0.0.1:8899'
def get(p): return json.loads(urllib.request.urlopen(BASE + p, timeout=60).read())

tasks = get('/api/tasks')
tid = next((t['id'] for t in tasks if t['id'].startswith('fc49316f')), None)
st = get('/api/tasks/' + tid)

L = []
def p(*a): L.append(' '.join(str(x) for x in a))

cp_ref = st.get('result_refs', {}).get('event_analysis_checkpoint')
p('checkpoint_ref', cp_ref)
cp = get('/api/artifacts/' + cp_ref)
p('checkpoint keys:', sorted(cp.keys()))
p('briefs count:', len(cp.get('briefs', {})))
p('briefs status:', json.dumps({k: v.get('status') for k, v in list(cp.get('briefs', {}).items())[:15]}, ensure_ascii=False))
p('classes count:', len(cp.get('classes', {})))
status_counter = {}
for v in cp.get('classes', {}).values():
    s = v.get('status'); status_counter[s] = status_counter.get(s, 0) + 1
p('classes status 分布:', status_counter)
p('merges count:', len(cp.get('merges', {})))
p('merge_snapshot remaining:', len(cp.get('merge_snapshot', {}).get('remaining', [])))
p('top10_consolidations count:', len(cp.get('top10_consolidations', {})))

# event_analysis 最终工件
ea_ref = st.get('result_refs', {}).get('event_analysis')
ea = get('/api/artifacts/' + ea_ref)
p('')
p('event_analysis.pending_model:', ea.get('pending_model'))
p('event_analysis.failures:', json.dumps(ea.get('failures', []), ensure_ascii=False))
p('event_analysis.theme 模型尚未处理:', sum(1 for g in ea.get('theme_groups', []) if g.get('candidate_theme') == '模型尚未处理'))
p('event_analysis.top10 status:', json.dumps([r.get('status') for r in ea.get('top10', [])], ensure_ascii=False))

# 对比 checkpoint classes 覆盖 vs final_groups
groups = ea.get('groups', [])
unclassified = [g['id'] for g in groups if g['id'] not in cp.get('classes', {}) and g['id'] not in ea.get('classification_reasons', {})]
p('')
p('final_groups count:', len(groups))
p('groups 无 classes 且无 reason 的数量:', len(unclassified))

with open('data/_fc49316f_checkpoint.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(L))
print('WROTE data/_fc49316f_checkpoint.txt')
