"""抓前端自测页的 DOM 与截图（headless Chrome），落成证据文件。

    python scripts/capture_manual_definition_evidence.py --url http://127.0.0.1:8768/ \
        --out .demo-data/evidence

先探测静态服务是否活着，再分别：
- 不带 click=1：截图（浮层选择题保持打开）
- 带 click=1：--dump-dom（走完提交流程，把请求体写进 #probe）
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHROME = Path(r'C:\Program Files\Google\Chrome\Application\chrome.exe')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8768/')
    parser.add_argument('--out', default='.demo-data/evidence')
    args = parser.parse_args()
    out = REPO / args.out
    out.mkdir(parents=True, exist_ok=True)

    with urllib.request.urlopen(args.url, timeout=15) as response:
        page = response.read().decode('utf-8')
    print('静态服务 OK，页面字节数', len(page))

    profile = REPO / '.demo-data' / 'chrome-capture'
    screenshot = out / 'selection-card.png'
    shot = subprocess.run(
        [str(CHROME), '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
         f'--user-data-dir={profile}', '--window-size=1200,980', '--virtual-time-budget=10000',
         f'--screenshot={screenshot}', args.url],
        capture_output=True, text=True, timeout=180)
    print('截图:', screenshot, screenshot.exists(), screenshot.stat().st_size if screenshot.exists() else 0)

    dump = subprocess.run(
        [str(CHROME), '--headless=new', '--disable-gpu', '--no-first-run',
         f'--user-data-dir={profile}b', '--virtual-time-budget=10000', '--dump-dom',
         args.url + ('&' if '?' in args.url else '?') + 'click=1'],
        capture_output=True, text=True, encoding='utf-8', timeout=180)
    dom = dump.stdout or ''
    (out / 'harness-dom.html').write_text(dom, encoding='utf-8')
    print('DOM 字节数', len(dom), '| 含 .td-card:', 'td-card' in dom, '| 含 .td-bar:', 'td-bar' in dom)

    probe = re.search(r'<div id="probe">(.*?)</div>', dom, re.S)
    raw = probe.group(1) if probe else ''
    text = (raw.replace('&quot;', '"').replace('&amp;', '&')
               .replace('&lt;', '<').replace('&gt;', '>'))
    (out / 'harness-probe.txt').write_text(text, encoding='utf-8')
    try:
        parsed = json.loads(text)
        print(json.dumps(parsed, ensure_ascii=False, indent=2))
        card = re.search(r'<div class="td-card".*?</div>\s*</div>\s*</div>', dom, re.S)
        if card:
            (out / 'card-dom.html').write_text(card.group(0), encoding='utf-8')
        return 0
    except json.JSONDecodeError:
        print('probe 解析失败，原样输出：')
        print(text[:2000])
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
