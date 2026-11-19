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
EVIDENCE = ROOT / 'docs/verification/2026-11-19-template-controls'


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
                const numbers=[...body.querySelectorAll('.field-chip')].map(e=>e.textContent);const noBlockMarkers=!body.querySelector('.template-block-number');
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

                const more=structuredClone(definition);more.fields.reverse();
                for(let n=3;n<=60;n++){more.fields.push({id:'f'+n,display_name:'字段'+n,owner:n%2?'data':'writer'});more.blocks.push({index:50+n,kind:'paragraph',parts:[{field:'f'+n}]})}
                const long=document.createElement('div');renderDocument(more,long,null,()=>{});
                const labels=[...long.querySelectorAll('.field-chip')].map(e=>e.dataset.fieldNumber);
                let state={revision:10,artifact_ref:'base',definition:{...definition,source_reports:[]},model_review_validated:true};let updates=0,confirms=0;
                api=async(path,opts)=>{
                  if(path.endsWith('/confirm')){confirms++;return {}}
                  if(opts?.method==='PUT'){updates++;const patch=JSON.parse(opts.body);if(patch.expected_revision!==state.revision)throw Error('stale revision');state={...state,revision:state.revision+1,artifact_ref:'saved',definition:{...state.definition,rules:patch.rules}};return structuredClone(state)}
                  if(path.endsWith('/definition'))return structuredClone(state);
                  if(path==='/api/tasks/controls')return {metadata:{}};
                  return [];
                };
                const draftMount=window.TemplateDraft.mount;window.TemplateDraft.mount=()=>{};
                await openTemplate('controls');
                const ids=['featureDedup','featureClassification','featureFirstWarning','featureTop10'];
                const inputs=()=>ids.map(id=>document.getElementById(id));
                const pendingChoices=inputs().every(el=>el.indeterminate&&!el.checked);
                const confirmButton=[...document.querySelectorAll('#dialogActions button')].find(b=>b.textContent==='确认并保存模板');
                const blockedPending=confirmButton.disabled;
                for(const el of inputs()){el.checked=false;el.indeterminate=false;el.dispatchEvent(new Event('change'))}
                document.getElementById(ids[1]).checked=true;document.getElementById(ids[1]).dispatchEvent(new Event('change'));
                const saveButton=[...document.querySelectorAll('.rule-settings button')].find(b=>b.textContent==='保存处理规则');
                if(saveButton){saveButton.click();await new Promise(r=>setTimeout(r,180))}
                await openTemplate('controls');
                const persisted=inputs().map(el=>el.checked);
                const resolved=inputs().every(el=>!el.indeterminate);
                window.TemplateDraft.mount=draftMount;api=oldApi;
                return {numbers,noBlockMarkers,header,editable,saved,tableEditable,offset,frozen,
                    reportHasNoNumbers:!report.querySelector('[data-field-number]'),labels,pendingChoices,blockedPending,
                    persisted,resolved,updates,confirms};

            })()''')
            (EVIDENCE / 'result.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
            (EVIDENCE / 'confirmed.png').write_bytes(base64.b64decode(call('Page.captureScreenshot', {'format':'png'})['data']))
            assert metrics['numbers'] == ['①〔报告年份〕','②〔呈发印发表格〕'], metrics
            assert metrics['noBlockMarkers'] and metrics['labels']==[str(i) for i in range(1,61)], metrics
            assert metrics['pendingChoices'] and metrics['blockedPending'], metrics
            assert metrics['persisted']==[False,True,False,False] and metrics['resolved'], metrics
            assert metrics['updates']==1 and metrics['confirms']==0, metrics
            assert '块 2' in metrics['header'], metrics
            assert all(metrics[k] for k in ('editable','saved','tableEditable','frozen','reportHasNoNumbers')), metrics
            assert metrics['offset'] == 2, metrics
            print('Chrome: semantic field numbering (60 fields), pending feature choices, save/reopen without confirmation, editable descriptions, selection offsets and readonly passed')
            if '--live-readonly' in sys.argv:
                call('Page.navigate', {'url': 'http://127.0.0.1:8765/'})
                for _ in range(100):
                    if js('typeof openTemplate === "function" && !!document.querySelector("#dialogBody")'):
                        break
                    time.sleep(.1)
                js("""(async()=>{
                    const original=api;api=(url,opts={})=>{if(opts.method&&opts.method!=='GET')throw Error('readonly acceptance');return original(url,{...opts,headers:{...opts.headers,'X-Report-Package':'longchuan_yuebao'}})};
                    await openTemplate('1e09e2eab7db4f7c953da78488c6f631');
                })()""")
                for _ in range(100):
                    if js('document.querySelectorAll("#dialogBody .field-chip").length===58'):
                        break
                    time.sleep(.1)
                live=js("""({revision:templateEditor.revision,
                    numbers:[...document.querySelectorAll('#dialogBody .field-chip')].map(e=>e.dataset.fieldNumber),
                    first:[...document.querySelectorAll('#dialogBody .field-chip')].slice(0,5).map(e=>e.textContent),
                    pending:[...document.querySelectorAll('.rule-settings input[type=checkbox]')].every(e=>e.indeterminate&&!e.checked),
                    featureValues:[...document.querySelectorAll('.rule-settings input[type=checkbox]')].map(e=>e.checked),
                    bindingText:document.querySelector('.td-bar').textContent,
                    confirmed:templateEditor.confirmed,
                    paragraphMarkers:document.querySelectorAll('.template-block-number').length})""")
                assert live['numbers']==[str(i) for i in range(1,59)], live
                assert live['featureValues']==[False,True,False,False] and not live['confirmed'] and live['paragraphMarkers']==0, live
                assert '9个字段已完成自动匹配数据来源' in live['bindingText'] and '待匹配数据来源' not in live['bindingText'], live
                (EVIDENCE/'live-readonly.json').write_text(json.dumps(live,ensure_ascii=False,indent=2),encoding='utf-8')
                call('Emulation.setDeviceMetricsOverride', {'width':1440,'height':1000,'deviceScaleFactor':1,'mobile':False})
                js("document.querySelector('#dialogBody .field-chip').scrollIntoView({block:'start'})")
                (EVIDENCE/'live-template.png').write_bytes(base64.b64decode(call('Page.captureScreenshot',{'format':'png'})['data']))
                js("document.querySelector('.rule-settings').scrollIntoView({block:'start'})")
                (EVIDENCE/'live-rules.png').write_bytes(base64.b64decode(call('Page.captureScreenshot',{'format':'png'})['data']))
                print('Live workbench: 58 semantic fields numbered; saved feature choices and 9 matched data sources; candidate still unconfirmed; readonly acceptance passed')
                if '--chart-previews' in sys.argv:
                    js("document.querySelectorAll('.chart-setting-card details').forEach(e=>e.open=true);document.querySelector('.chart-settings-grid').scrollIntoView({block:'start'})")
                    for _ in range(100):
                        loaded=js("[...document.querySelectorAll('.chart-setting-card details img')].map(e=>({src:e.getAttribute('src'),width:e.naturalWidth,height:e.naturalHeight,complete:e.complete}))")
                        if len(loaded)==3 and all(item['width']>0 for item in loaded):
                            break
                        time.sleep(.1)
                    assert len(loaded)==3 and all(item['width']>0 for item in loaded),loaded
                    output=ROOT/'docs/verification/2026-11-19-source-chart-preview'
                    output.mkdir(exist_ok=True,parents=True)
                    (output/'browser.json').write_text(json.dumps(loaded,ensure_ascii=False,indent=2),encoding='utf-8')
                    (output/'preview.png').write_bytes(base64.b64decode(call('Page.captureScreenshot',{'format':'png'})['data']))
                    print('Live Chrome: all three historical chart images loaded successfully')


    finally:
        process.terminate()
        process.wait(timeout=15)
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    verify()
