"""Read-only Chrome acceptance for generated charts in both report previews."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request

from websockets.sync.client import connect


def verify(task_id, output):
    output.mkdir(parents=True, exist_ok=True)
    profile=Path(tempfile.mkdtemp(prefix='report-chart-chrome-'))
    process=subprocess.Popen([
        'C:/Program Files/Google/Chrome/Application/chrome.exe', '--headless=new',
        '--remote-debugging-port=0', '--no-first-run', '--no-default-browser-check',
        '--disable-background-networking', '--disable-sync', '--disable-extensions',
        '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',
        f'--user-data-dir={profile}', 'about:blank'],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if (profile/'DevToolsActivePort').exists():break
            time.sleep(.1)
        port=(profile/'DevToolsActivePort').read_text().splitlines()[0]
        targets=json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json'))
        with connect(next(t for t in targets if t['type']=='page')['webSocketDebuggerUrl'],max_size=8_000_000) as ws:
            seq=0
            def call(method,params=None):
                nonlocal seq
                seq+=1
                ws.send(json.dumps({'id':seq,'method':method,'params':params or {}}))
                while True:
                    response=json.loads(ws.recv(timeout=30))
                    if response.get('id')==seq:
                        if 'error' in response:raise RuntimeError(response['error'])
                        return response.get('result',{})
            def js(expression):
                response=call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
                if 'exceptionDetails' in response:raise RuntimeError(response['exceptionDetails'])
                return response.get('result',{}).get('value')
            call('Page.enable')
            call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1000,'deviceScaleFactor':1,'mobile':False})
            call('Page.navigate',{'url':'http://127.0.0.1:8765/'})
            for _ in range(100):
                if js('typeof openWritingReview==="function"'):break
                time.sleep(.1)
            results=[]
            for name,entry in [('draft','openDraft'),('review','openWritingReview')]:
                js(f'{entry}({json.dumps(task_id)})')
                if name=='review':js("[...document.querySelectorAll('#dialogBody details')].find(d=>d.querySelector('summary')?.textContent==='当前报告预览').open=true")
                for _ in range(100):
                    images=js("[...document.querySelectorAll('#dialogBody .report-paper img.report-chart')].map(e=>({url:e.getAttribute('src'),width:e.naturalWidth,height:e.naturalHeight}))")
                    if len(images)==3 and all(i['width'] for i in images):break
                    time.sleep(.1)
                assert len(images)==3 and all(i['width'] for i in images),images
                assert js("document.querySelectorAll('#dialogBody .report-paper .chart-placeholder').length")==0
                for index in range(3):
                    js(f"document.querySelectorAll('#dialogBody .report-paper img.report-chart')[{index}].scrollIntoView({{block:'center'}})")
                    (output/f'{name}-{index+1}.png').write_bytes(base64.b64decode(call('Page.captureScreenshot',{'format':'png'})['data']))
                results.append({'entry':name,'images':images,'placeholders':0})
            (output/'browser.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(results))
    finally:
        process.terminate()
        process.wait(timeout=15)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('task_id')
    parser.add_argument('--output',type=Path,default=Path(tempfile.gettempdir())/'chart-fix-evidence')
    args=parser.parse_args()
    verify(args.task_id,args.output)
