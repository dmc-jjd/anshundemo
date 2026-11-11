"""抓取本次重跑完整事件时间线（seq>6375），输出精简时序。"""
import json, urllib.request

BASE = 'http://127.0.0.1:8899'
TASK = 'd2511637eb694125a92616d2a276bd08'

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=90) as r:
        return json.load(r)

events = get('/api/tasks/' + TASK + '/events?after=6375&limit=200')

L = []
def p(*a):
    L.append(' '.join(str(x) for x in a))

p('===== 本次重跑完整事件时间线 (seq 6376+, 共 %d 条) =====' % len(events))

names = {
    'validate_input': '校验输入', 'write_draft': '按模板写作', 'local_validation': '本地校验',
    'style_detection': '文风识别', 'format_review': '格式审核', 'content_review': '内容审核',
    'revise_draft': '退修改写', 'final_format_review': '最终格式校验', 'await_final_review': '进入人工终审',
}

for e in events:
    seq = e['seq']; typ = e['type']
    if typ == 'graph_node':
        name = names.get(e.get('node'), e.get('node'))
        p('#%-4d [图节点] %s %s' % (seq, name, e.get('status')))
    elif typ == 'model_call':
        u = e.get('usage', {})
        p('#%-4d [模型] %-16s %s  %dms  prompt=%s compl=%s total=%s' % (
            seq, e.get('role'), e.get('status'), e.get('elapsed_ms'),
            u.get('prompt_tokens'), u.get('completion_tokens'), u.get('total_tokens')))
    elif typ == 'model_exchange':
        p('#%-4d [模型交换] %s ref=%s turn=%s' % (seq, e.get('role'), e.get('ref'), e.get('turn')))
    elif typ == 'writing_review':
        p('#%-4d [双审] %s 第%s轮 status=%s 意见数=%s' % (
            seq, {'format_reviewer': '格式审核', 'content_reviewer': '内容审核'}.get(e.get('reviewer'), e.get('reviewer')),
            e.get('round'), e.get('status'), e.get('issue_count')))
    elif typ == 'writer_review_repair':
        p('#%-4d [退修] stage=%s fields=%s round=%s field_errors=%s' % (
            seq, e.get('stage'), e.get('fields'), e.get('round'), len(e.get('field_errors') or [])))
    elif typ == 'writer_repair_declined':
        p('#%-4d [Writer拒绝退修] issue_ids=%s' % (seq, e.get('issue_ids')))
    elif typ == 'format_review_forwarded_to_content':
        p('#%-4d [格式转内容] reason=%s 未解决格式意见=%s' % (seq, e.get('reason'), len(e.get('unresolved_format_issues') or [])))
    elif typ == 'review_output_correction':
        p('#%-4d [输出纠偏] %s attempt=%s' % (seq, e.get('reviewer'), e.get('attempt')))
    elif typ == 'writer_repair_validation_retry':
        p('#%-4d [退修校验重试] stage=%s attempt=%s' % (seq, e.get('stage'), e.get('attempt')))
    elif typ == 'writing_local_validation':
        p('#%-4d [本地校验结果] missing=%s' % (seq, e.get('missing')))
    elif typ == 'model_usage':
        pass  # 与 model_exchange 重复，略过
    else:
        p('#%-4d [%s] %s' % (seq, typ, json.dumps({k: v for k, v in e.items() if k not in ('type', 'seq', 'at')}, ensure_ascii=False)[:140]))

# 统计
total_tokens = sum(e.get('usage', {}).get('total_tokens', 0) for e in events if e['type'] == 'model_call')
calls = [e for e in events if e['type'] == 'model_call']
p('')
p('===== 本次重跑模型调用统计 =====')
p('model_call 次数=%d 合计 tokens=%d' % (len(calls), total_tokens))
for e in calls:
    u = e.get('usage', {})
    p('  %-16s %s  total=%s' % (e.get('role'), e.get('phase', ''), u.get('total_tokens')))

with open('data/_dual_review_timeline.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(L))
print('WROTE data/_dual_review_timeline.txt lines=%d events=%d calls=%d tokens=%d' % (len(L), len(events), len(calls), total_tokens))
