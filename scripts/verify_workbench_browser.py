"""Real Chrome + full application, synthetic stores, no external network/models."""
import asyncio
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request


def verify():
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / 'tests')]
    temp = Path(tempfile.mkdtemp(prefix='v5-workbench-'))
    os.environ.update(REPORT_DEMO_DATA=str(temp / 'data'), REPORT_PACKAGE='anshun_monthly',
                      REPORT_MODEL_KEY='', REPORT_SEARCH_KEY='', REPORT_MODEL_URL='',
                      REPORT_MODEL_NAME='', REPORT_SEARCH_URL='', MPLCONFIGDIR=str(temp / 'mpl'),
                      PYTHONDONTWRITEBYTECODE='1')
    import uvicorn
    from websockets.sync.client import connect
    from app.factory import create_app
    from app.settings import Settings
    from app.schemas import TaskState
    from core.structured_template import _schema
    from test_frozen_writer import fixture
    from app.structured_writer import write_structured_preview
    from app.workflow import Dependencies
    import shutil

    fixture_store, _ = fixture(temp)
    async def model(role, payload):
        return {'selections': []} if 'reference_requests' in payload else {'values': {}}
    asyncio.run(write_structured_preview(Dependencies(fixture_store, model), 'r'))
    state = fixture_store.get_task('r')
    state.phase = 'awaiting_final_review'
    fixture_store.put_task(state, state.revision)
    shutil.copytree(fixture_store.root, temp / 'data/packages/anshun_monthly')
    app = create_app(Settings(temp / 'data'))
    stores = app.state.services.store
    refs = {}
    for package in ('anshun_monthly', 'ruyuan_yuebao'):
        local = stores.store_for(package)
        field = {'id': 'text', 'display_name': '测试正文', 'owner': 'writer', 'kind': 'text',
                 'semantic': '测试', 'value_schema': {'type': 'string', 'minLength': 1}}
        template = {'status': 'confirmed_by_human', 'source_reports': [{'sha256': 'a'}, {'sha256': 'b'}],
                    'comparison_ref': 'fixture', 'fields': [field], 'blocks': [],
                    'output_schema': _schema([field]), 'writer_schema': _schema([field], True)}
        for damage in ('healthy', 'missing', 'unreadable'):
            tid = package + '-' + damage
            ref = local.put_artifact(tid, 'template', dict(template, id=tid))
            local.put_task(TaskState(id=tid, kind='template', package=package, phase='template_confirmed',
                                    metadata={'confirmed_template_ref': ref, 'template_name': tid}))
            refs[tid] = ref
            path = local.files / (ref + '.json')
            if damage == 'missing':
                path.unlink()
            elif damage == 'unreadable':
                path.write_text('{bad', encoding='utf-8')

    original_connect = socket.socket.connect
    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            raise RuntimeError('external network forbidden')
        return original_connect(sock, address)
    socket.socket.connect = local_only
    evidence = root / 'docs/verification/2026-11-18-optimization/browser'
    evidence.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
    worker = threading.Thread(target=server.run, daemon=True)
    worker.start()
    for _ in range(100):
        if server.started: break
        time.sleep(.05)
    process = subprocess.Popen([
        r'C:/Program Files/Google/Chrome/Application/chrome.exe', '--headless=new',
        '--remote-debugging-port=0', '--no-first-run', '--no-default-browser-check',
        '--disable-background-networking', '--disable-sync', '--disable-extensions',
        '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',
        f'--user-data-dir={temp / "chrome"}', 'about:blank',
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    checks = {}
    try:
        active = temp / 'chrome/DevToolsActivePort'
        for _ in range(100):
            if active.exists(): break
            time.sleep(.1)
        debug = active.read_text().splitlines()[0]
        targets = json.load(urllib.request.urlopen(f'http://127.0.0.1:{debug}/json'))
        with connect(next(t for t in targets if t['type'] == 'page')['webSocketDebuggerUrl'], max_size=8_000_000) as ws:
            seq = 0
            def call(method, params=None):
                nonlocal seq
                seq += 1
                ws.send(json.dumps({'id': seq, 'method': method, 'params': params or {}}))
                while True:
                    result = json.loads(ws.recv(timeout=15))
                    if result.get('id') == seq:
                        if 'error' in result: raise RuntimeError(result['error'])
                        return result.get('result', {})
            def js(expression):
                result = call('Runtime.evaluate', {'expression': expression, 'returnByValue': True, 'awaitPromise': True})
                if 'exceptionDetails' in result: raise RuntimeError(result['exceptionDetails'])
                return result.get('result', {}).get('value')
            def wait(expression):
                for _ in range(100):
                    if js(expression): return
                    time.sleep(.1)
                raise AssertionError((expression, js('document.body.innerText.slice(-1600)')))
            def click(text):
                js(f'[...document.querySelectorAll("button")].find(b=>b.textContent.trim()==={json.dumps(text)}).click()')
            def shot(name):
                (evidence / name).write_bytes(base64.b64decode(call('Page.captureScreenshot', {'format': 'png'})['data']))
            call('Page.enable')
            call('Emulation.setDeviceMetricsOverride', {'width': 1440, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False})
            call('Page.navigate', {'url': f'http://127.0.0.1:{port}/'})
            wait('document.querySelector("#reportPackage")?.options.length >= 2')
            js('document.querySelector("[data-go=report]").click()')
            wait('document.querySelector("#reportTemplate").options.length > 1')
            selected = js('[...document.querySelector("#reportTemplate").options].map(o=>o.textContent)')
            assert not any('ruyuan_yuebao' in text for text in selected), selected
            checks['initial_package_templates_isolated'] = True
            js('document.querySelector("#reportPackage").value="ruyuan_yuebao"; document.querySelector("#reportPackage").dispatchEvent(new Event("change"))')
            wait('[...document.querySelector("#reportTemplate").options].some(o=>o.textContent.includes("ruyuan_yuebao-healthy"))')
            selected = js('[...document.querySelector("#reportTemplate").options].map(o=>o.textContent)')
            assert not any('anshun_monthly' in text for text in selected), selected
            assert not any('missing' in text or 'unreadable' in text for text in selected), selected
            checks['package_change_and_healthy_selection'] = True
            shot('report-package-selection.png')
            js('document.querySelector("[data-go=template]").click()')
            wait('document.querySelector("#templateLibrary").textContent.includes("文件缺失")')
            assert js('document.querySelector("#templateLibrary").textContent.includes("文件不可读")')
            assert js('[...document.querySelectorAll("#templateLibrary tr")].filter(r=>/文件缺失|文件不可读/.test(r.textContent)).every(r=>[...r.querySelectorAll("button")].find(b=>b.textContent.includes("查看模板"))?.disabled)')
            checks['unavailable_rows_manageable_not_previewable'] = True
            # Delay only delivery of a real API response, never substitute data.
            js('window.__originalFetch=window.fetch; window.__delayedA=0; window.fetch=async(...args)=>{const r=await window.__originalFetch(...args);if(args[0]==="/api/templates"&&new Headers(args[1]?.headers).get("X-Report-Package")==="anshun_monthly"){window.__delayedA++;await new Promise(resolve=>setTimeout(resolve,1200))}return r};document.querySelector("#templatePackage").value="anshun_monthly";document.querySelector("#templatePackage").dispatchEvent(new Event("change"))')
            wait('window.__delayedA>0')
            js('document.querySelector("#templatePackage").value="ruyuan_yuebao";document.querySelector("#templatePackage").dispatchEvent(new Event("change"))')
            wait('document.querySelector("#templateLibrary").textContent.includes("ruyuan_yuebao-healthy")')
            time.sleep(1.5)
            assert not js('document.querySelector("#templateLibrary").textContent.includes("anshun_monthly-healthy")')
            checks['stale_management_response_discarded'] = True
            js('window.fetch=window.__originalFetch')
            shot('unavailable-template-rows.png')
            js('document.querySelector("[data-go=tasks]").click()')
            wait('document.querySelector("#taskList").textContent.includes("r")')
            js('[...document.querySelectorAll("#taskList button")].find(b=>b.lastElementChild.textContent==="r").click()')
            wait('[...document.querySelectorAll("#taskActions button")].some(b=>b.textContent.includes("查看报告"))')
            click('查看报告与缺失项')
            wait('!!document.querySelector("textarea[aria-label=w1]")')
            js('document.querySelector("textarea[aria-label=w1]").value="浏览器人工补充测试正文"; document.querySelector("textarea[aria-label=w2]").value="浏览器人工确认测试内容"')
            click('保存人工补充')
            wait('document.querySelector("#dialogBody").textContent.includes("浏览器人工补充测试正文")')
            shot('manual-edit-saved.png')
            call('Page.reload')
            wait('!!document.querySelector("#taskList") && typeof refresh==="function"')
            js('document.querySelector("[data-go=tasks]").click()')
            wait('[...document.querySelectorAll("#taskList button")].some(b=>b.lastElementChild.textContent==="r")')
            js('[...document.querySelectorAll("#taskList button")].find(b=>b.lastElementChild.textContent==="r").click()')
            wait('[...document.querySelectorAll("#taskActions button")].some(b=>b.textContent.includes("查看报告"))')
            click('查看报告与缺失项')
            wait('document.querySelector("#dialogBody").textContent.includes("浏览器人工补充测试正文")')
            checks['human_edit_persists_after_reload'] = True
            # Real API rejection rendered through the production UI error path.
            js('document.querySelector("#reviewDialog").close()')
            # A disabled preview cannot be clicked. Exercise a stale page's real
            # preview request through the same production error presentation.
            js('busy(document.querySelector("#startReport"),()=>api("/api/templates/anshun_monthly-missing/definition"))')
            wait('document.querySelector("#toast").textContent.includes("模板文件缺失")')
            checks['ui_rejection_message'] = js('document.querySelector("#toast").textContent')
            (evidence / 'result.json').write_text(json.dumps({'synthetic': True, 'full_application': True, 'checks': checks, 'temporary_root': str(temp)}, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(checks, ensure_ascii=False))
    finally:
        process.terminate()
        process.wait(timeout=15)
        server.should_exit = True
        worker.join(timeout=10)
        socket.socket.connect = original_connect


if __name__ == '__main__':
    verify()
