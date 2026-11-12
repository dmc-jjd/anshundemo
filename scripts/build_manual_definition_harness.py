"""生成「选区 → 选择题」的前端自测页（真实浏览器里跑真实前端代码，用于 DOM 证据）。

做法：
1. 从运行中的服务取 `/api/templates/{id}/draft`（含定义与选择题清单）；
2. 从 `app/static/app.js` 抽出 `node` / `fieldLabel` / `renderDocument` 三个函数（花括号配平提取）；
3. 复制真实的 `app/static/template-draft.js`；
4. 拼一个自测页：stub 掉 `api/busy/toast`，挂载 TemplateDraft，模拟一次真实文本选区并派发
   mouseup，再点「动态文字」，把提交的 JSON 落到 DOM 里。

随后用 headless Chrome 取 DOM/截图：
    python -m http.server 8768 --directory .demo-data/harness
    chrome --headless --dump-dom --virtual-time-budget=9000 http://127.0.0.1:8768/
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / 'app' / 'static'


def extract_function(source: str, name: str) -> str:
    """按花括号配平抽取函数源码。

    注意：参数默认值里也可能有 `{}`（`attrs={}`），所以函数体的 `{` 必须等**圆括号配平归零**
    之后才算，否则会抽出 `function node(tag,text,attrs={}` 这种半截代码。
    """
    start = source.index('function ' + name + '(')
    paren = 0
    body = None
    for index in range(start, len(source)):
        char = source[index]
        if char == '(':
            paren += 1
        elif char == ')':
            paren -= 1
        elif char == '{' and paren == 0:
            body = index
            break
    if body is None:
        raise SystemExit(f'未找到 {name} 的函数体')
    depth = 0
    for index in range(body, len(source)):
        char = source[index]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise SystemExit(f'未能配平提取 {name}')


def build(base: str, task: str, out: Path) -> dict:
    with urllib.request.urlopen(f'{base}/api/templates/{task}/draft', timeout=30) as response:
        view = json.loads(response.read().decode('utf-8'))
    app_js = (STATIC / 'app.js').read_text(encoding='utf-8')
    functions = '\n'.join(extract_function(app_js, name) for name in ('node', 'fieldLabel', 'renderDocument'))
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(STATIC / 'template-draft.js', out / 'template-draft.js')
    payload = json.dumps(view, ensure_ascii=False)
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>选区→选择题 自测</title>
<style>body{{font-family:"Microsoft YaHei",sans-serif;margin:0;padding:16px;background:#eef2f7}}
#app{{background:#fff;padding:16px;border-radius:8px;max-width:900px}}
.field-chip{{border:1px dashed #b45309;background:#fef3c7;color:#92400e;border-radius:4px;
  padding:0 2px;cursor:pointer;font:inherit}}
#probe{{margin-top:12px;font-size:12px;white-space:pre-wrap;background:#0f172a;color:#e2e8f0;padding:8px;border-radius:6px}}
</style></head><body>
<div id="app"></div><div id="probe">waiting…</div><div id="toast"></div>
<script>
window.__VIEW__ = {payload};
window.__POSTED__ = [];
window.api = async (url, opts) => {{
  if (!opts || !opts.method) return window.__VIEW__;
  window.__POSTED__.push(JSON.parse(opts.body));
  const body = window.__VIEW__;
  return {{ revision: (body.revision||0)+1, has_draft: true, choices: body.choices,
            draft: body.draft, definition: body.definition,
            field: {{id:'block_3_field_999', display_name:'动态文字', owner:'writer'}},
            placeholder: '{{{{block_3_field_999}}}}', preview_chip: '〔动态文字〕',
            selection: {{choice:'text'}}, block: body.definition.blocks[0] }};
}};
window.busy = async (b, fn) => {{ await fn(); }};
window.toast = text => {{ document.getElementById('toast').textContent = text; }};
</script>
<script>{functions}</script>
<script src="template-draft.js"></script>
<script>
(async () => {{
 try {{
  const container = document.getElementById('app');
  await TemplateDraft.mount({{taskId: 'manual-definition-demo', container}});
  const paper = container.querySelector('.report-paper');
  const paragraphs = [...paper.querySelectorAll('p[data-block]')];
  const target = paragraphs.find(p => [...p.childNodes].some(n => n.nodeType === 3 && n.length >= 2));
  const textNode = [...target.childNodes].find(n => n.nodeType === 3 && n.length >= 2);
  const range = document.createRange();
  range.setStart(textNode, 0);
  range.setEnd(textNode, 2);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  target.dispatchEvent(new MouseEvent('mouseup', {{bubbles: true}}));
  await new Promise(resolve => setTimeout(resolve, 120));
  const card = document.querySelector('.td-card');
  const enabled = card ? [...card.querySelectorAll('.td-opt')]
      .filter(option => !option.disabled).map(option => option.textContent.slice(0, 20)) : [];
  const chosen = card && [...card.querySelectorAll('.td-opt')].find(option => !option.disabled);
  const shouldClick = new URLSearchParams(location.search).get('click') === '1';
  if (chosen && shouldClick) chosen.click();
  await new Promise(resolve => setTimeout(resolve, 120));
  document.getElementById('probe').textContent = JSON.stringify({{
    block: target.dataset.block,
    selected: String(selection),
    card_rendered: !!card,
    card_title: card ? card.querySelector('header span').textContent : null,
    quote: card ? card.querySelector('.td-quote').textContent : null,
    enabled_options: enabled,
    posted: window.__POSTED__,
    chips_after: [...chosen ? document.querySelectorAll('.field-chip') : []].length,
    bar: (document.querySelector('.td-bar') || {{}}).textContent || ''
  }}, null, 2);
  document.title = 'ready';
 }} catch (error) {{
  document.getElementById('probe').textContent = 'ERROR: ' + (error && error.stack || error);
 }}
}})();
</script></body></html>
"""
    (out / 'index.html').write_text(html, encoding='utf-8')
    return {'view_keys': sorted(view), 'fields': len(view['definition']['fields']),
            'output': str(out / 'index.html')}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8767')
    parser.add_argument('--task', default='manual-definition-demo')
    parser.add_argument('--out', default='.demo-data/harness')
    args = parser.parse_args()
    result = build(args.base.rstrip('/'), args.task, REPO / args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
