"""隔离演示服务上的真实 Chromium 验证；不调用客户数据或模型。"""
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
    evidence = root / 'docs/verification/2026-11-18-starbridge'
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
                    result = call('Runtime.evaluate', {'expression': expression, 'returnByValue': True, 'awaitPromise': True})
                    if 'exceptionDetails' in result:
                        raise RuntimeError(result['exceptionDetails'])
                    return result.get('result', {}).get('value')

                def wait_for(expression):
                    for _ in range(100):
                        if evaluate(expression):
                            return
                        time.sleep(.1)
                    raise AssertionError((expression, evaluate('({url: location.href, status: document.querySelector("#starbridgeStatus")?.textContent, count: document.querySelectorAll(".starbridge-topic").length, open: document.querySelector("dialog")?.open, body: document.body.innerText.slice(-1500)})'), requests))

                call('Page.enable')
                call('Emulation.setDeviceMetricsOverride', {'width': 1440, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False})
                call('Page.navigate', {'url': f'http://127.0.0.1:{port}/static/index.html'})
                wait_for('!!document.getElementById("starbridgeOpen") && !!document.querySelector(".starbridge-dialog")')
                for platform in ('douyin', 'toutiao', 'weibo', 'baidu'):
                    evaluate(f'document.querySelector("#socialPanel [data-platform={platform}]").click()')
                    wait_for(f'document.querySelectorAll("#socialBody li").length === 20 && document.querySelector("#socialBody .social-topic-title").textContent === {json.dumps(social_profile(platform)["items"][0]["title"])}')
                    assert evaluate('document.querySelector("#socialMeta").textContent.includes("非实时")')
                    assert evaluate('document.querySelectorAll("#socialBody .social-heat").length') == 20
                screenshot = call('Page.captureScreenshot', {'format': 'png'})
                (evidence / 'social-screenshot-demo.png').write_bytes(base64.b64decode(screenshot['data']))
                # 回归已有会话场景：不能只验证空白浏览器的首次渲染。
                evaluate('localStorage.setItem("kn-chat-sessions-v1", JSON.stringify({version:1,activeId:"history-fixture",sessions:[{id:"history-fixture",title:"已有会话",createdAt:Date.now(),updatedAt:Date.now(),messages:[{role:"user",text:"历史合成问题"},{role:"ai",text:"历史合成回答"}]}]}))')
                evaluate('document.getElementById("starbridgeOpen").click()')
                wait_for('document.querySelectorAll(".starbridge-topic").length === 81')
                assert evaluate('document.querySelector("#starbridgeTopics").textContent.includes("普京抵达深圳") && document.querySelector("#starbridgeTopics").textContent.includes("A股")')
                assert evaluate('document.querySelector("#starbridgeConfirm").disabled')
                evaluate('document.querySelector("dialog").close()')
                assert evaluate('sessionStorage.getItem("kn-starbridge-draft-v1")') is None
                evaluate('document.getElementById("starbridgeOpen").click()')
                wait_for('document.querySelectorAll(".starbridge-topic").length === 81')
                evaluate('document.querySelectorAll(".starbridge-topic input")[0].click(); document.querySelectorAll(".starbridge-topic input")[2].click()')
                assert evaluate('document.querySelectorAll(".starbridge-topic input:checked").length') == 1
                evaluate('document.querySelectorAll(".starbridge-topic input")[0].click()')
                screenshot = call('Page.captureScreenshot', {'format': 'png'})
                (evidence / 'desktop-selection.png').write_bytes(base64.b64decode(screenshot['data']))
                call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 844, 'deviceScaleFactor': 1, 'mobile': True})
                assert evaluate('document.querySelector("dialog").getBoundingClientRect().width <= innerWidth')
                screenshot = call('Page.captureScreenshot', {'format': 'png'})
                (evidence / 'mobile-selection.png').write_bytes(base64.b64decode(screenshot['data']))
                call('Emulation.setDeviceMetricsOverride', {'width': 1440, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False})
                evaluate('document.querySelector("#starbridgeConfirm").click()')
                wait_for('location.pathname === "/static/chat.html" && !!document.querySelector("deep-chat")?.shadowRoot?.querySelector("[contenteditable=true]")?.innerText.includes("浏览器验证选题甲")')
                text = evaluate('document.querySelector("deep-chat").shadowRoot.querySelector("[contenteditable=true]").innerText')
                assert '数据包链接：' in text and '一、事件概述' in text and 'citizen_comments' in text
                time.sleep(1.5)
                assert evaluate('document.querySelector("deep-chat").shadowRoot.querySelector("[contenteditable=true]").innerText').count('【星桥约稿任务】') == 1
                assert evaluate('sessionStorage.getItem("kn-starbridge-draft-v1")') is None
                time.sleep(.3)
                screenshot = call('Page.captureScreenshot', {'format': 'png'})
                (evidence / 'studio-prefilled.png').write_bytes(base64.b64decode(screenshot['data']))
                assert '/api/chat/stream' not in requests
                report = {'social_demo_platforms': 4, 'social_demo_items': 80, 'social_demo_rendered': True, 'starbridge_topics': 81, 'single_selection': True, 'prefilled_selected_topic': True, 'inline_package': True, 'prompt': True, 'handoff_consumed': True, 'auto_send_requests': 0, 'mobile_dialog_fits': True, 'requests': requests}
                (evidence / 'browser-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(report, ensure_ascii=False))
        finally:
            process.terminate()
            process.wait(timeout=15)
            server.should_exit = True
            worker.join(timeout=5)


if __name__ == '__main__':
    verify()
