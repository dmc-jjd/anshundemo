"""Chrome layout regression: actual static UI and synthetic read-only API data."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import urllib.request

from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'docs/verification/2026-11-18-template-fields'


def verify():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    tasks = [{'id': f'layout-task-{i:02}', 'display_name': name, 'kind': 'template',
              'phase': 'template_model_reviewing' if i % 2 else 'template_confirmed'}
             for i, name in enumerate((['龙川县舆情月报V3',
                 '龙川县舆情月报V2 · 2026 年 10 月 · 第10期 · 2026-11-18',
                 'template_version-' + '9825796fbd27c6d305d6' * 5] * 10))]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = self.path.split('?')[0]
            if path.startswith('/api/'):
                value = tasks if path == '/api/tasks' else {'model_configured': False} if path == '/api/status' else []
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
    temp = Path(tempfile.mkdtemp(prefix='v5-template-fields-'))
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
            call('Page.navigate', {'url': f'http://127.0.0.1:{server.server_port}/'})
            for _ in range(100):
                if js('typeof renderDocument === "function" && !!document.querySelector("#dialogBody")'):
                    break
                time.sleep(.1)
            metrics = js(r'''(async()=>{
                const definition={fields:[{id:'year',display_name:'报告年份',semantic:'封面统计年份',owner:'data',rule:'取任务报告统计年份',reason:'年份随任务变化',format:'YYYY',block:2,binding:{metric:'report_year'},sources:[{text:'2026'}]},{id:'rows',display_name:'呈发印发表格',semantic:'动态表格',owner:'data',block:48,sources:[]}],blocks:[{index:2,kind:'paragraph',parts:[{text:'年份：'},{field:'year'}]},{index:22,kind:'paragraph',parts:[{text:'媒体分级固定句'}]},{index:48,kind:'table',headers:['印发'],parts:[{field:'rows'}]}]};
                openDialog('字段与块编号验证');
                templateEditor={id:'synthetic-template',definition,revision:7,candidateRef:'synthetic-ref',confirmed:false,refresh:()=>{}};
                const body=document.querySelector('#dialogBody');body.replaceChildren();renderDocument(definition,body,null,editField);
                const numbers=[...body.querySelectorAll('.template-block-number')].map(e=>e.textContent);
                body.querySelector('[data-field="year"]').click();
                const header=body.querySelector('#fieldInspector h3').textContent;
                const rule=body.querySelector('[aria-label="字段规则"]'),reason=body.querySelector('[aria-label="制定理由"]'),format=body.querySelector('[aria-label="输出格式"]');
                const editable=![rule,reason,format].some(e=>e.disabled);
                rule.value='人工规则';reason.value='人工说明';format.value='整数';
                const oldApi=api;let payload;
                api=async(path,opts)=>{payload=JSON.parse(opts.body);return {revision:8,artifact_ref:'saved-ref',field:{...definition.fields[0],...payload}}};
                body.querySelector('#fieldInspector button').click();
                await new Promise(r=>setTimeout(r,120));api=oldApi;
                const saved=payload.rule==='人工规则'&&payload.reason==='人工说明'&&payload.format==='整数'&&payload.expected_revision===7;
                const text=body.querySelector('[data-block="2"]').firstChild;
                const offset=window.TemplateDraft.canonOffset(text.parentNode,text,2);
                body.querySelector('[data-field="rows"]').click();const tableEditable=body.querySelector('#fieldInspector h3').textContent.includes('块 48');
                templateEditor.confirmed=true;editField(definition.fields[0]);
                const frozen=[...body.querySelectorAll('#fieldInspector input,#fieldInspector textarea,#fieldInspector select')].every(e=>e.disabled);
                const report=document.createElement('div');renderDocument(definition,report,{});
                return {numbers,header,editable,saved,tableEditable,offset,frozen,reportHasNoNumbers:!report.querySelector('.template-block-number')};
            })()''')
            (EVIDENCE / 'result.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
            (EVIDENCE / 'confirmed.png').write_bytes(base64.b64decode(call('Page.captureScreenshot', {'format':'png'})['data']))
            assert metrics['numbers'] == ['块 2','块 22','块 48'], metrics
            assert '块 2' in metrics['header'], metrics
            assert all(metrics[k] for k in ('editable','saved','tableEditable','frozen','reportHasNoNumbers')), metrics
            assert metrics['offset'] == 2, metrics
            print('Chrome: block ids, editable descriptions, save payload, table fields, readonly confirmation, selection offsets, report without labels passed')
    finally:
        process.terminate()
        process.wait(timeout=15)
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    verify()
