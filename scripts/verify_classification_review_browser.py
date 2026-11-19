"""Live Chrome review regression; blocks every backend write and uses a fresh profile."""
import base64
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
from websockets.sync.client import connect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/verification/2026-11-19-classification-review'
TASK='5ebf3edc104b43d1a5ca67ce0ca2180e'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    profile=Path(tempfile.mkdtemp(prefix='v5-classification-browser-'))
    process=subprocess.Popen([r'C:/Program Files/Google/Chrome/Application/chrome.exe','--headless=new',
        '--remote-debugging-port=0','--no-first-run','--no-default-browser-check','--disable-background-networking',
        '--disable-sync','--disable-extensions','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',
        f'--user-data-dir={profile}','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
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
                seq+=1;ws.send(json.dumps({'id':seq,'method':method,'params':params or {}}))
                while True:
                    response=json.loads(ws.recv(timeout=20))
                    if response.get('id')==seq:
                        if 'error' in response:raise RuntimeError(response['error'])
                        return response.get('result',{})
            def js(expression):
                response=call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
                if 'exceptionDetails' in response:raise RuntimeError(response['exceptionDetails'])
                return response.get('result',{}).get('value')
            call('Page.enable')
            call('Page.addScriptToEvaluateOnNewDocument',{'source':"""
                localStorage.setItem('workbench.reportPackage','longchuan_yuebao');
                const originalFetch=window.fetch;
                window.fetch=(u,o={})=>{if(!['GET','HEAD'].includes((o.method||'GET').toUpperCase()))throw Error('Backend writes blocked');return originalFetch(u,o)};
            """})
            call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1100,'deviceScaleFactor':1,'mobile':False})
            call('Page.navigate',{'url':'http://127.0.0.1:8765/'})
            for _ in range(100):
                if js("typeof classificationReviewItems==='function' && typeof openData==='function'"):break
                time.sleep(.1)
            js(f"openData('{TASK}')")
            counts=js("({raw:Object.keys(dataEditor.records).length,groups:dataEditor.groups.length,pending:reviewGate(dataEditor).unclassified.length,confirmDisabled:document.querySelector('#confirmDataAction').disabled})")
            assert counts['groups']==0 and counts['pending']==282 and counts['confirmDisabled'],counts
            js("document.querySelectorAll('.review-tabs button')[1].click()")
            assert js("document.querySelectorAll('.review-layout .result-row').length")==15
            assert js("!!document.querySelector('.event-category-controls')")
            assert not js("document.querySelector('#dialogBody').textContent.includes('将勾选记录拆成新事件')")
            js("document.querySelector('.review-layout').scrollIntoView({block:'start'})")
            (OUT/'pending-records.png').write_bytes(base64.b64decode(call('Page.captureScreenshot',{'format':'png'})['data']))
            js("document.querySelector('.event-category-controls select').value='社会民生';[...document.querySelectorAll('.event-category-controls button')].find(b=>b.textContent==='应用此记录分类').click()")
            time.sleep(.4)
            after=js("({pending:reviewGate(dataEditor).unclassified.length,groups:dataEditor.groups.length,saved:!!localStorage.getItem('report-review-draft:'+dataEditor.id),confirmDisabled:document.querySelector('#confirmDataAction').disabled})")
            assert after=={'pending':281,'groups':0,'saved':True,'confirmDisabled':True},after
            # Reload only in this isolated browser profile: verify local progress recovery.
            js("document.querySelector('#reviewDialog').close()")
            js(f"openData('{TASK}')")
            assert js('reviewGate(dataEditor).unclassified.length')==281
            final={'before':counts,'after_local_classification':after,'local_restore':True,'backend_writes':'blocked','business_reports_generated':False}
            (OUT/'browser.json').write_text(json.dumps(final,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
            print(json.dumps(final,ensure_ascii=False))
    finally:
        process.terminate()
        process.wait(timeout=15)


if __name__=='__main__':main()
