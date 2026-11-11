"""从 replay 结果 JSON 提取精简双审摘要，写 UTF-8 文本。"""
import json

with open('data/_dual_review_replay_result.json', encoding='utf-8') as f:
    d = json.load(f)

L = []
def p(*a):
    L.append(' '.join(str(x) for x in a))

def trunc(s, n=180):
    s = str(s)
    return s if len(s) <= n else s[:n] + '…'

before = d['task_before']
after = d['task_after']

p('===== 任务 =====')
p('task_id', d['task_id'])
p('before_phase', before['phase'], 'rev', before['revision'])
p('after_phase', after['phase'], 'rev', after['revision'])
p('before_draft_ref', before.get('draft_ref'))
p('after_draft_ref', after.get('draft_ref'))
p('trigger', d.get('trigger', {}).get('phase') if d.get('trigger') else None, 'error', d.get('trigger_error'))

p('')
p('===== phase 流转 (本次重跑) =====')
for t in d['phase_transitions']:
    p('+%ss -> %s (rev %s)' % (t['elapsed_s'], t['phase'], t['revision']))

p('')
p('===== 新事件日志 (共 %d 条) =====' % len(d['new_events']))
for e in d['new_events']:
    seq = e['seq']; typ = e['type']
    if typ == 'graph_node':
        p('#%d graph_node[%s] %s=%s phase=%s' % (seq, e.get('graph'), e.get('node'), e.get('status'), e.get('phase', '')))
    elif typ == 'writing_review':
        p('#%d writing_review reviewer=%s status=%s round=%s issue_count=%s model_called=%s' % (
            seq, e.get('reviewer'), e.get('status'), e.get('round'), e.get('issue_count'), e.get('model_called')))
    elif typ == 'format_review_forwarded_to_content':
        p('#%d format_forwarded reason=%s status=%s round=%s unresolved_format_issues=%s' % (
            seq, e.get('reason'), e.get('status'), e.get('round'), e.get('unresolved_format_issues')))
    elif typ == 'writer_review_repair':
        p('#%d writer_repair stage=%s fields=%s round=%s field_errors=%s' % (
            seq, e.get('stage'), e.get('fields'), e.get('round'), e.get('field_errors')))
    elif typ == 'writer_repair_validation_retry':
        p('#%d repair_validation_retry stage=%s attempt=%s error=%s' % (seq, e.get('stage'), e.get('attempt'), trunc(e.get('error'), 120)))
    elif typ == 'writer_repair_declined':
        p('#%d writer_repair_declined issue_ids=%s reason=%s' % (seq, e.get('issue_ids'), trunc(e.get('reason'), 120)))
    elif typ == 'review_output_correction':
        p('#%d review_output_correction reviewer=%s attempt=%s errors=%s' % (seq, e.get('reviewer'), e.get('attempt'), trunc(e.get('errors'), 120)))
    elif typ == 'writer_review_repair_failed':
        p('#%d writer_repair_failed error=%s' % (seq, trunc(e.get('error'), 160)))
    elif typ == 'writing_local_validation':
        p('#%d writing_local_validation missing=%s' % (seq, e.get('missing')))
    else:
        p('#%d %s %s' % (seq, typ, trunc(json.dumps({k: v for k, v in e.items() if k not in ('type', 'seq', 'at')}, ensure_ascii=False), 200)))

p('')
p('===== review_report (终态) =====')
rr = after.get('metadata', {}).get('review_report', {})
p(json.dumps(rr, ensure_ascii=False, indent=2))

p('')
p('===== writing_review_run (本轮 bookkeeping) =====')
run = after.get('metadata', {}).get('writing_review_run', {})
keep = {k: v for k, v in run.items() if k not in ('style_refs', 'review_item_order', 'id')}
p(json.dumps(keep, ensure_ascii=False, indent=2))

p('')
p('===== review_counts =====')
p(json.dumps(after.get('review_counts', {}), ensure_ascii=False))

p('')
p('===== 双审意见 (writing_review items) =====')
items = after.get('review_items', [])
wr = [i for i in items if i.get('kind') == 'writing_review']
p('count=%d (open=%d resolved=%d superseded=%d)' % (
    len(wr),
    sum(1 for i in wr if i.get('status') == 'open'),
    sum(1 for i in wr if i.get('status') == 'resolved'),
    sum(1 for i in wr if i.get('status') == 'superseded')))
for i in wr:
    det = i.get('details', {})
    p('- [%s] reviewer=%s status=%s blocking=%s field=%s severity=%s action=%s' % (
        i.get('status'), i.get('reviewer'), i.get('status'), i.get('blocking'),
        det.get('field_id'), det.get('severity'), det.get('action')))
    p('    question: %s' % trunc(i.get('question'), 240))

p('')
p('===== 缺失字段 / 待补 =====')
p('missing_fields', after.get('metadata', {}).get('missing_fields'))
p('writer_issues count', len(after.get('metadata', {}).get('writer_issues', [])))
p('preview_only', after.get('metadata', {}).get('preview_only'))

with open('data/_dual_review_summary.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(L))
print('WROTE data/_dual_review_summary.txt  lines=%d' % len(L))
