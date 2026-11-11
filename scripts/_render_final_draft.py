"""渲染终稿全文：读 structured_draft + 模板，按 blocks 替换字段值。"""
import json
from pathlib import Path

ART = Path('data/artifacts')
DRAFT_REF = 'structured_draft-4f1d15abf847c1dd7d99'

draft = json.loads((ART / (DRAFT_REF + '.json')).read_text(encoding='utf-8'))
tmpl_ref = draft.get('structured_template_ref') or draft.get('template_ref')
template = json.loads((ART / (tmpl_ref + '.json')).read_text(encoding='utf-8'))

fields = {f['id']: f for f in template.get('fields', [])}
slot_values = draft.get('slot_values', {})

def value_of(fid):
    v = slot_values.get(fid, {}).get('value')
    return v

def render_value(fid, v):
    if isinstance(v, list):
        # 列表字段：逐条展示
        return '；'.join(str(x) for x in v)
    return str(v)

L = []
def out(s=''):
    L.append(s)

out('===== 终稿全文 =====')
out('(草稿 %s ｜ 模板 %s ｜ fact_ref %s)' % (DRAFT_REF, tmpl_ref, draft.get('fact_ref')))
out('')

for block in template.get('blocks', []):
    kind = block.get('kind')
    if kind == 'table':
        # 表头
        headers = block.get('headers') or []
        out('【表】 ' + ' | '.join(str(h) for h in headers))
        # 找字段
        key = next((p.get('field') for p in block.get('parts', []) if p.get('field')), None)
        rows = value_of(key) if key else None
        if isinstance(rows, list):
            for row in rows:
                cells = row if isinstance(row, list) else [row]
                out('  ' + ' | '.join(str(c) for c in cells))
        else:
            out('  〔数据表格〕 ' + str(rows) if rows else '  〔数据表格为空〕')
        out('')
        continue
    if kind == 'repeat':
        key = block.get('parts', [{}])[0].get('field') if block.get('parts') else None
        vals = value_of(key) if key else None
        out('【列表】' + (fields.get(key, {}).get('display_name') or key or ''))
        if isinstance(vals, list):
            for i, item in enumerate(vals, 1):
                out('  %d. %s' % (i, str(item)))
        else:
            out('  ' + str(vals))
        out('')
        continue
    # 普通段落：拼接 parts
    rendered = ''
    for part in block.get('parts', []):
        if 'text' in part:
            rendered += part['text']
        elif part.get('field'):
            fid = part['field']
            v = value_of(fid)
            rendered += render_value(fid, v) if v is not None else '〔%s〕' % fields.get(fid, {}).get('display_name', fid)
    out(rendered.strip())
    out('')

out('')
out('===== 字段清单（slot_values） =====')
for fid in sorted(slot_values.keys()):
    f = fields.get(fid, {})
    v = slot_values[fid].get('value')
    disp = f.get('display_name', fid)
    owner = f.get('owner', '?')
    vs = v if isinstance(v, str) else (json.dumps(v, ensure_ascii=False) if not isinstance(v, list) else '[%d 条]' % len(v))
    out('- [%s] %s (%s): %s' % (fid, disp, owner, (vs[:200] + '…') if isinstance(vs, str) and len(vs) > 200 else vs))

with open('data/_final_draft_render.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(L))
print('WROTE data/_final_draft_render.txt lines=%d blocks=%d fields=%d slots=%d' % (
    len(L), len(template.get('blocks', [])), len(fields), len(slot_values)))
