"""字段关联界面的隔离 Chromium 验证；不调用客户数据或模型。"""
import base64
import json
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from websockets.sync.client import connect

from app.hotspot_api import starbridge_demo_package
from app.social_hotlist import profile as social_profile


def verify():
    root = Path(__file__).resolve().parents[1]
    evidence = root / 'docs/verification/2026-11-19-writing-contracts'
    evidence.mkdir(parents=True, exist_ok=True)
    app = FastAPI()
    requests = []
    app.get('/api/starbridge/demo-package')(starbridge_demo_package)

    @app.middleware('http')
    async def record(request: Request, call_next):
        requests.append(request.url.path)
        return await call_next(request)

    @app.get('/api/hotspot')
    def hotspots():
        return {'available': True, 'categories': ['演示'], 'items': [{'title': '浏览器验证选题甲', 'summary': '合成热点摘要', 'category': '演示', 'url': '#'}]}

    @app.get('/api/social-hotlist')
    def social(platform: str = 'weibo'):
        return social_profile(platform)

    @app.get('/api/{path:path}')
    def fallback(path: str):
        return []

    app.mount('/static', StaticFiles(directory=root / 'app/static'))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
    worker = threading.Thread(target=server.run, daemon=True)
    worker.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(.05)
    with tempfile.TemporaryDirectory(prefix='starbridge-chrome-') as profile:
        process = subprocess.Popen([
            r'C:/Program Files/Google/Chrome/Application/chrome.exe', '--headless=new',
            '--remote-debugging-port=0', '--no-first-run', '--no-default-browser-check',
            '--disable-background-networking', '--disable-sync', '--disable-extensions',
            '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',
            f'--user-data-dir={profile}', 'about:blank',
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            active = Path(profile) / 'DevToolsActivePort'
            for _ in range(100):
                if active.exists():
                    break
                time.sleep(.1)
            debug_port = active.read_text().splitlines()[0]
            targets = json.load(urllib.request.urlopen(f'http://127.0.0.1:{debug_port}/json'))
            target = next(row for row in targets if row['type'] == 'page')
            with connect(target['webSocketDebuggerUrl'], max_size=8_000_000) as ws:
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

                def evaluate(expression):
                    result = call('Runtime.evaluate', {'expression': expression, 'returnByValue': True, 'awaitPromise': True, 'userGesture': True})
                    if 'exceptionDetails' in result:
                        raise RuntimeError(result['exceptionDetails'])
                    return result.get('result', {}).get('value')

                def wait_for(expression):
                    for _ in range(100):
                        if evaluate(expression):
                            return
                        time.sleep(.1)
                    raise AssertionError((expression, evaluate('({url: location.href, status: document.querySelector("#starbridgeStatus")?.textContent, count: document.querySelectorAll(".starbridge-topic").length, open: document.querySelector(".starbridge-dialog")?.open, body: document.body.innerText.slice(-1500)})'), requests))

                call('Page.enable')
                call('Page.bringToFront')
                call('Emulation.setDeviceMetricsOverride', {'width': 1440, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False})
                call('Page.navigate', {'url': f'http://127.0.0.1:{port}/static/index.html'})
                wait_for('!!document.getElementById("starbridgeOpen") && !!document.querySelector(".starbridge-dialog")')
                wait_for('!!window.WritingGroups')
                evaluate('window.groupFields=[{id:"a",display_name:"风险主题",owner:"writer"},{id:"b",display_name:"风险背景",owner:"writer"}]; window.groupFixture=[{id:"risk",label:"第一关注重点",members:{a:"topic",b:"background"},instruction:"围绕同一个主题",query:{focus:"all",limit:10}}]; document.body.innerHTML="<main id=groupHost></main>"; window.mountGroup=(readonly=false)=>WritingGroups.mount(document.getElementById("groupHost"),{fields:groupFields,groups:groupFixture,readonly,onSave:async groups=>window.savedGroups=groups,onField:f=>window.locatedField=f.id}); mountGroup()')
                assert evaluate('document.querySelectorAll(".writing-group-card").length') == 1
                evaluate('document.querySelector(".writing-group-card>input").value="更新后的主题组";document.querySelector(".writing-group-card>input").dispatchEvent(new Event("input")); [...document.querySelectorAll("button")].find(b=>b.textContent==="保存字段关联").click()')
                wait_for('window.savedGroups?.[0]?.label === "更新后的主题组"')
                evaluate('[...document.querySelectorAll("button")].find(b=>b.textContent==="查看字段").click()')
                assert evaluate('window.locatedField') == 'a'
                evaluate('window.groupFields.push({id:"month",display_name:"标题月份",owner:"data"}); mountGroup()')
                assert evaluate('document.querySelectorAll(".writing-group-members > div").length') == 2
                assert evaluate('document.querySelector(".writing-group-available").open') is False
                evaluate('const candidate=document.querySelector(".writing-group-candidates input[type=checkbox]"); candidate.checked=true;candidate.dispatchEvent(new Event("change"))')
                assert evaluate('document.querySelectorAll(".writing-group-members > div").length') == 3
                evaluate('const member=[...document.querySelectorAll(".writing-group-members > div")].find(r=>r.querySelector("label").textContent==="标题月份").querySelector("input");member.checked=false;member.dispatchEvent(new Event("change"))')
                assert evaluate('document.querySelectorAll(".writing-group-members > div").length') == 2
                evaluate('mountGroup(true)')
                assert evaluate('[...document.querySelectorAll("input,textarea,select")].every(n=>n.disabled)')
                assert evaluate('[...document.querySelectorAll("button")].every(b=>b.textContent!=="保存字段关联")')
                call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 844, 'deviceScaleFactor': 1, 'mobile': True})
                assert evaluate('document.documentElement.scrollWidth <= innerWidth')
                screenshot = call('Page.captureScreenshot', {'format':'png'})
                (evidence / 'group-readonly-mobile.png').write_bytes(base64.b64decode(screenshot['data']))
                report={'editable_groups_saved':True,'field_navigation':True,'confirmed_readonly':True,'mobile_fits':True,'business_model_calls':0}
                (evidence/'browser-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps(report,ensure_ascii=False))
        finally:
            process.terminate()
            process.wait(timeout=15)
            server.should_exit = True
            worker.join(timeout=5)


if __name__ == '__main__':
    verify()
