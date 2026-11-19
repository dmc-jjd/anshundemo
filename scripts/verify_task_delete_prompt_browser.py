"""Chrome layout regression: actual static UI and synthetic read-only API data."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'docs/verification/2026-11-19-task-delete-prompts'


def verify():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    tasks = [{'id': f'layout-task-{i:02}', 'display_name': name, 'kind': 'template',
              'phase': 'template_model_reviewing' if i % 2 else 'template_confirmed'}
             for i, name in enumerate((['龙川县舆情月报V3',
                 '龙川县舆情月报V2 · 2026 年 10 月 · 第10期 · 2026-11-18',
                 'template_version-' + '9825796fbd27c6d305d6' * 5] * 10))]

    deleted = []
    prompt_data = {'package': 'test', 'generated_at': None, 'files_updated_at': '2026-11-19T02:00:00Z',
                   'templates': [{'template_ref': 'template_version-new', 'name': '新确认模板', 'status': 'pending', 'note': '提示词尚未更新'},
                                 {'template_ref': 'template_version-old', 'name': '旧模板', 'status': 'unrecorded'}]}

    class Handler(BaseHTTPRequestHandler):
        def do_DELETE(self):
            task_id = self.path.rsplit('/', 1)[-1]
            deleted.append(task_id)
            tasks[:] = [t for t in tasks if t['id'] != task_id]
            raw = b'{"ok": true, "hard": true}'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

        def do_GET(self):
            path = self.path.split('?')[0]
            if path.startswith('/api/'):
                value = prompt_data if path == '/api/prompt-status' else tasks if path == '/api/tasks' else {'model_configured': False} if path == '/api/status' else []
                raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
                mime = 'application/json; charset=utf-8'
            else:
                relative = 'index.html' if path == '/' else path.removeprefix('/static/')
                file = (ROOT / 'app/static' / relative).resolve()
                if not file.is_relative_to((ROOT / 'app/static').resolve()) or not file.is_file():
                    self.send_error(404)
                    return
                raw = file.read_bytes()
                mime = {'.css': 'text/css', '.js': 'text/javascript', '.mjs': 'text/javascript',
                        '.html': 'text/html; charset=utf-8'}.get(file.suffix, 'application/octet-stream')
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    temp = Path(tempfile.mkdtemp(prefix='v5-task-layout-'))
    process = subprocess.Popen([
        r'C:/Program Files/Google/Chrome/Application/chrome.exe', '--headless=new',
        '--remote-debugging-port=0', '--no-first-run', '--no-default-browser-check',
        '--disable-background-networking', '--disable-sync', '--disable-extensions',
        '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',
        f'--user-data-dir={temp}', 'about:blank'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    results = []
    try:
        for _ in range(100):
            if (temp / 'DevToolsActivePort').exists():
                break
            time.sleep(.1)
        port = (temp / 'DevToolsActivePort').read_text().splitlines()[0]
        targets = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json'))
        with connect(next(t for t in targets if t['type'] == 'page')['webSocketDebuggerUrl'], max_size=8_000_000) as ws:
            seq = 0

            def call(method, params=None):
                nonlocal seq
                seq += 1
                ws.send(json.dumps({'id': seq, 'method': method, 'params': params or {}}))
                while True:
                    result = json.loads(ws.recv(timeout=15))
                    if result.get('id') == seq:
                        if 'error' in result:
                            raise RuntimeError(result['error'])
                        return result.get('result', {})

            def js(expression):
                result = call('Runtime.evaluate', {'expression': expression, 'returnByValue': True, 'awaitPromise': True})
                if 'exceptionDetails' in result:
                    raise RuntimeError(result['exceptionDetails'])
                return result.get('result', {}).get('value')

            call('Page.enable')
            if '--live-readonly' in sys.argv:
                call('Page.addScriptToEvaluateOnNewDocument', {'source': "const realFetch=window.fetch;window.fetch=(u,o={})=>{if(!['GET','HEAD'].includes((o.method||'GET').toUpperCase()))throw Error('Read-only verification');return realFetch(u,o)};"})
                call('Emulation.setDeviceMetricsOverride', {'width': 1440, 'height': 1100, 'deviceScaleFactor': 1, 'mobile': False})
                call('Page.navigate', {'url': 'http://127.0.0.1:8765/'})
                for _ in range(100):
                    if js('typeof loadPromptStatus === "function" && !!document.querySelector("#promptStatus")'):break
                    time.sleep(.1)
                js("(async()=>{await loadPackages();document.querySelector('#templatePackage').value='longchuan_yuebao';await tab('template');await loadPromptStatus('longchuan_yuebao')})()")
                for _ in range(100):
                    text = js("document.querySelector('#promptStatus').textContent")
                    if 'template_version-49d0abb1aab9c13aa117' in text:break
                    time.sleep(.1)
                assert '待适配' in text and '适配记录缺失' in text and 'template_version-49d0abb1aab9c13aa117' in text, text
                assert js("!document.querySelector('#templateLibrary').textContent.includes('可用于成稿')")
                (EVIDENCE / 'live-card.png').write_bytes(base64.b64decode(call('Page.captureScreenshot', {'format': 'png'})['data']))
                (EVIDENCE / 'live-browser.json').write_text(json.dumps({'read_only': True, 'prompt_card': text}, ensure_ascii=False, indent=2), encoding='utf-8')
                print('Live Chrome: prompt card and confirmed-template wording verified; all writes blocked')
                return
            for width, height in [(1440, 1000), (1100, 780), (390, 844)]:
                call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': False})
                call('Page.navigate', {'url': f'http://127.0.0.1:{server.server_port}/'})
                for _ in range(100):
                    if js('typeof refresh === "function" && !!document.querySelector("#taskList")'):
                        break
                    time.sleep(.1)
                js('document.querySelectorAll(".tab").forEach(e=>e.classList.remove("active"));document.querySelector("#tasks").classList.add("active");refresh()')
                metrics = js('''(()=>{const l=document.querySelector('#taskList'),rows=[...l.children],r=l.getBoundingClientRect();return {count:rows.length,heights:rows.map(e=>e.getBoundingClientRect().height),widths:rows.map(e=>e.getBoundingClientRect().width),scrollHeight:l.scrollHeight,clientHeight:l.clientHeight,overflow:getComputedStyle(l).overflowY,x:r.x+r.width/2,y:r.y+Math.min(r.height/2,180),overlap:rows.some((e,i)=>i&&e.getBoundingClientRect().top<rows[i-1].getBoundingClientRect().bottom),horizontalOverflow:l.scrollWidth>l.clientWidth}})()''')
                call('Input.dispatchMouseEvent', {'type': 'mouseWheel', 'x': metrics['x'], 'y': metrics['y'], 'deltaX': 0, 'deltaY': 500})
                time.sleep(.2)
                metrics['wheelScrollTop'] = js('document.querySelector("#taskList").scrollTop')
                js('document.querySelector("#taskList").scrollTop=100000')
                metrics['lastReachable'] = js('''(()=>{const l=document.querySelector('#taskList'),a=l.getBoundingClientRect(),b=l.lastElementChild.getBoundingClientRect();return b.bottom<=a.bottom+1&&b.top>=a.top})()''')
                metrics['refreshPreservesScroll'] = js('''(async()=>{const l=document.querySelector('#taskList'),top=l.scrollTop;await refresh();return Math.abs(l.scrollTop-top)<1})()''')
                metrics['fullTitleAvailable'] = js('''[...document.querySelector('#taskList').children].every(e=>e.title.includes(e.querySelector('strong').textContent))''')
                js('document.querySelector("#taskList").focus()')
                call('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'Home', 'code': 'Home', 'windowsVirtualKeyCode': 36})
                call('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'Home', 'code': 'Home', 'windowsVirtualKeyCode': 36})
                time.sleep(.2)
                metrics['keyboardScrollsToTop'] = js('document.querySelector("#taskList").scrollTop===0')
                (EVIDENCE / f'{width}.png').write_bytes(base64.b64decode(call('Page.captureScreenshot', {'format': 'png'})['data']))
                metrics['viewport'] = [width, height]
                results.append(metrics)
            js("window.confirm=()=>false;selected=null;document.querySelector('.task-delete').click()")
            time.sleep(.1)
            assert deleted == [] and js('selected===null')
            first_id = tasks[0]['id']
            js("window.confirm=()=>true;selected=" + json.dumps(first_id) + ";deleteWorkbenchTask(" + json.dumps(tasks[0]) + ",document.querySelector('.task-delete'))")
            assert deleted == [first_id] and js('selected===null && document.querySelectorAll(".task-row").length===29')
            js("document.querySelectorAll('.tab').forEach(e=>e.classList.remove('active'));document.querySelector('#template').classList.add('active');loadPromptStatus('')")
            assert js("document.querySelector('#promptStatus').textContent.includes('待适配') && document.querySelector('#promptStatus').textContent.includes('适配记录缺失') && document.querySelector('#promptStatus').textContent.includes('template_version-new')")
            (EVIDENCE / 'prompt-card.png').write_bytes(base64.b64decode(call('Page.captureScreenshot', {'format': 'png'})['data']))
            (EVIDENCE / 'deletion.json').write_text(json.dumps({'cancel_sent_no_delete': True, 'confirmed_delete': deleted, 'selection_cleared': True, 'prompt_states_rendered': True}), encoding='utf-8')
            (EVIDENCE / 'result.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
            for result in results:
                assert result['count'] == 30, result
                assert len(set(result['heights'])) == 1 and min(result['heights']) >= 90, result
                assert len(set(result['widths'])) == 1, result
                assert result['scrollHeight'] > result['clientHeight'], result
                assert result['overflow'] in ('auto', 'scroll'), result
                assert result['wheelScrollTop'] > 0 and result['lastReachable'], result
                assert result['refreshPreservesScroll'] and result['fullTitleAvailable'] and result['keyboardScrollsToTop'], result
                assert not result['overlap'] and not result['horizontalOverflow'], result
            print('Chrome: 3 viewports; equal cards, wheel scrolling, last task reachable; synthetic APIs only')
    finally:
        process.terminate()
        process.wait(timeout=15)
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    verify()
