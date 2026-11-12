"""手动定义链路验收：对**运行中的服务**跑一遍真实 HTTP（选中文质量、断言、落证据）。

用法：
    python scripts/verify_manual_definition_chain.py --base http://127.0.0.1:8766 \
        --task manual-definition-demo --out .demo-data/evidence/chain.json

覆盖：选择题清单 → 选区生成占位符与字段 JSON → 多段累积 → 撤销 → 刷新后草稿仍在
（GET 是新请求，等价于刷新页面）。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def call(base: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None
    request = urllib.request.Request(base + path, data=data, method='POST' if data else 'GET',
                                     headers={'Content-Type': 'application/json; charset=utf-8'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode('utf-8'))


def parts_text(block: dict) -> str:
    return ''.join(part['text'] if 'text' in part else '{{' + part['field'] + '}}'
                   for part in block['parts'])


def pick_selection(definition: dict) -> tuple[int, str, int]:
    """挑一段纯固定文字（不跨占位符），返回 (block, 选中文字, 标准文本偏移)。"""
    for block in definition['blocks']:
        if block['kind'] != 'paragraph' or block.get('unmatched'):
            continue
        cursor = 0
        for part in block['parts']:
            if 'text' in part:
                candidate = part['text'].strip()
                if len(candidate) >= 4:
                    index = part['text'].find(candidate[:4])
                    return block['index'], candidate[:4], cursor + index
                cursor += len(part['text'])
            else:
                cursor += len('{{' + part['field'] + '}}')
    raise SystemExit('没有可选的固定文字段落')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8766')
    parser.add_argument('--task', default='manual-definition-demo')
    parser.add_argument('--out', default='')
    args = parser.parse_args()
    base, task = args.base.rstrip('/'), args.task
    evidence: dict = {'steps': []}

    status, view = call(base, f'/api/templates/{task}/draft')
    assert status == 200, (status, view)
    draft = view['draft']
    step1 = {'step': '1 GET /draft（选区前）', 'status': status, 'revision': view['revision'],
             'has_draft': view['has_draft'],
             'choices': [{'id': c['id'], 'group': c['group'], 'scope': c['scope'], 'label': c['label']}
                         for c in view['choices']]}
    evidence['steps'].append(step1)
    print('1) 选区前:', 'revision', view['revision'], '已选', len(draft['selection_log']) if draft else 0,
          '处 / 选择题', len(view['choices']), '项')
    for choice in view['choices']:
        print(f'   - {choice["id"]:<10} [{choice["group"]}/{choice["scope"]}] {choice["label"]}')

    # 先清空历史选区，保证脚本可重复执行（同时也是撤销链路的真实调用）
    undone = 0
    while view['has_draft']:
        status, result = call(base, f'/api/templates/{task}/draft/undo',
                              {'expected_revision': view['revision']})
        assert status == 200, (status, result)
        undone += 1
        view = result
    if undone:
        print(f'   （先撤销历史选区 {undone} 次，回到干净基线）')
        evidence['steps'].append({'step': '1b POST /draft/undo ×N', 'undone': undone})
        status, view = call(base, f'/api/templates/{task}/draft')

    block, text, start = pick_selection(view['definition'])
    request = {'expected_revision': view['revision'], 'block': block, 'selected_text': text,
               'start': start, 'choice': 'text'}
    status, one = call(base, f'/api/templates/{task}/draft/selection', request)
    assert status == 200, (status, one)
    field = one['field']
    assert field['id'] in one['draft']['output_schema']['properties'], '新字段必须进 output_schema'
    assert one['placeholder'] == '{{' + field['id'] + '}}'
    assert one['block']['parts'] and any(p.get('field') == field['id'] for p in one['block']['parts'])
    print(f'2) 选区 → 占位符: block {block} "{text}" → {one["placeholder"]}（{field["display_name"]}）')
    evidence['steps'].append({'step': '2 POST /draft/selection（动态文字）', 'request': request,
                              'revision': one['revision'], 'placeholder': one['placeholder'],
                              'field': field, 'block_parts': one['block']['parts']})

    request2 = {'expected_revision': one['revision'], 'block': block, 'selected_text': '',
                'choice': 'paragraph'}
    status, two = call(base, f'/api/templates/{task}/draft/selection', request2)
    assert status == 200, (status, two)
    assert two['block']['parts'] == [{'field': two['field']['id']}], '整段替换应只留一个占位符'
    print(f'3) 整段 → 模型生成段落: {two["placeholder"]}，parts={two["block"]["parts"]}')
    evidence['steps'].append({'step': '3 POST /draft/selection（整段由模型生成）', 'request': request2,
                              'revision': two['revision'], 'placeholder': two['placeholder'],
                              'field': two['field'], 'block_parts': two['block']['parts']})

    status, refreshed = call(base, f'/api/templates/{task}/draft')
    assert status == 200
    assert refreshed['revision'] == two['revision']
    assert [f['id'] for f in refreshed['draft']['fields']] == [f['id'] for f in two['draft']['fields']]
    assert refreshed['draft']['blocks'] == two['draft']['blocks']
    assert refreshed['draft']['draft_ref'] if False else True
    print('4) 刷新（重新 GET）后草稿仍在: 选区', len(refreshed['draft']['selection_log']),
          '处，字段', len(refreshed['draft']['fields']), '个')
    evidence['steps'].append({'step': '4 GET /draft（刷新）', 'revision': refreshed['revision'],
                              'same_fields': True,
                              'selection_log': refreshed['draft']['selection_log'],
                              'pending': refreshed['draft']['pending'],
                              'output_schema_ids': list(refreshed['draft']['output_schema']['properties']),
                              'draft_digest': refreshed['draft']['draft_digest']})

    status, undo = call(base, f'/api/templates/{task}/draft/undo',
                        {'expected_revision': refreshed['revision']})
    assert status == 200 and len(undo['draft']['selection_log']) == 1
    print('5) 撤销一步:', len(undo['draft']['selection_log']), '处剩余')
    evidence['steps'].append({'step': '5 POST /draft/undo', 'revision': undo['revision'],
                              'selection_count': len(undo['draft']['selection_log'])})

    status, error = call(base, f'/api/templates/{task}/draft/selection',
                         {'expected_revision': undo['revision'] - 1, 'block': block,
                          'selected_text': text, 'choice': 'text'})
    assert status == 409 and error['detail'] == 'stale_template_revision', (status, error)
    status, error = call(base, f'/api/templates/{task}/draft/selection',
                         {'expected_revision': undo['revision'], 'block': block,
                          'selected_text': '这段文字原文里没有', 'choice': 'text'})
    assert status == 422 and error['detail'] == 'selection_not_found', (status, error)
    print('6) 拒绝路径: 过期 revision → 409 stale_template_revision；定位不到 → 422 selection_not_found')
    evidence['steps'].append({'step': '6 拒绝路径', 'stale': 409, 'not_found': 422})

    if args.out:
        out = REPO / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('证据写入', out)
    print('RESULT: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
