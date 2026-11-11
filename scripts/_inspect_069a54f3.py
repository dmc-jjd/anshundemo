"""拉取 069a54f3 任务的状态 + 全量事件 + event_analysis 工件，dump 分析。"""
import json, urllib.request

BASE = 'http://127.0.0.1:8899'

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=120) as r:
        return json.load(r)

tasks = get('/api/tasks')
tid = next((t['id'] for t in tasks if t['id'].startswith('069a54f3')), None)
if not tid:
    print('NOT_FOUND'); raise SystemExit(1)

state = get('/api/tasks/' + tid)
events = get('/api/tasks/' + tid + '/logs')

# event_analysis 工件
ea = None
if state.get('result_refs', {}).get('event_analysis'):
    try:
        ea = get('/api/artifacts/' + state['result_refs']['event_analysis'])
    except Exception as e:
        ea = {'fetch_error': str(e)}

L = []
def p(*a): L.append(' '.join(str(x) for x in a))

p('===== 任务 =====')
p('id', state['id'])
p('kind', state.get('kind'), 'phase', state.get('phase'), 'revision', state.get('revision'))
p('template_ref', state.get('template_ref'))
p('fact_ref', state.get('fact_ref'), '(冻结事实)')
p('mode', state.get('metadata', {}).get('mode'), 'analysis_pending', state.get('metadata', {}).get('analysis_pending'),
  'analysis_stage', state.get('metadata', {}).get('analysis_stage'))
p('result_refs keys:', sorted(state.get('result_refs', {}).keys()))
p('')
p('===== 事件日志（共 %d 条，倒序最近的在前展示关键类） =====' % len(events))
names = {'import_records':'导入明细','calculate_metrics':'计算统计','filter_records':'筛选记录','group_events':'自动归并事件',
         'cluster_event_themes':'生成分类','resolve_locality':'识别属地','classify_records':'读取源分类','discover_topics':'发现选题',
         'propose_keyword_event_candidates':'关键词事件候选','propose_vector_event_neighbors':'向量近邻候选'}
for e in events:
    t = e.get('type')
    if t in ('tool_start', 'tool_result'):
        tool = names.get(e.get('tool'), e.get('tool'))
        if t == 'tool_start':
            p('  tool_start  %s' % tool)
        else:
            p('  tool_result %s  status=%s  error_code=%s' % (tool, e.get('status'), e.get('error_code')))
    elif t == 'event_analysis_progress':
        p('  [分析进度] stage=%s completed=%s' % (e.get('stage'), e.get('completed')))
    elif t == 'model_call':
        p('  [模型] %-18s status=%s error=%s elapsed=%s' % (e.get('role'), e.get('status'), e.get('error'), e.get('elapsed_ms')))
    elif t == 'model_request_error':
        p('  [模型请求错误] %-18s status_code=%s error=%s' % (e.get('role'), e.get('status_code'), e.get('error')))
    elif t == 'fallback_started' or t == 'fallback_step_result':
        p('  [保底] %s %s' % (t, json.dumps({k: v for k, v in e.items() if k not in ('type','seq','at')}, ensure_ascii=False)[:200]))
    elif t == 'phase':
        p('  [阶段] phase=%s' % e.get('phase'))

p('')
p('===== event_analysis 工件 =====')
if ea and 'fetch_error' not in ea:
    p('source_key', ea.get('source_key'))
    p('failures (%d):' % len(ea.get('failures', [])))
    for f in ea.get('failures', []):
        p('   -', f)
    c = ea.get('counts', {})
    p('counts:', json.dumps(c, ensure_ascii=False))
    p('merge_ambiguities(人工待判合并) %d 条' % len(ea.get('merge_ambiguities', [])))
    p('classification_issues(人工待判分类) %d 条' % len(ea.get('classification_issues', [])))
    for x in ea.get('classification_issues', [])[:10]:
        p('   分类待判: event=%s reason=%s' % (x.get('event_id'), x.get('reason')))
    p('theme_groups:')
    for g in ea.get('theme_groups', []):
        p('   %s -> %d 条记录' % (g.get('candidate_theme'), len(g.get('member_ids', []))))
    p('top10:')
    for row in ea.get('top10', []):
        p('   #%s status=%s 负警=%s summary=%s' % (row.get('rank'), row.get('status'), row.get('negative_warning_count'), (row.get('summary') or '')[:40]))
    p('pending_model', ea.get('pending_model'))
else:
    p(str(ea))

with open('data/_task_069a54f3_analysis.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(L))
print('WROTE data/_task_069a54f3_analysis.txt  events=%d  phase=%s' % (len(events), state.get('phase')))
