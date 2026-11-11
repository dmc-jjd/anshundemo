"""端点稳定性探针：测 thinking=enabled 与 thinking=disabled 的延迟与可达性。不打印密钥。"""
import json, time, urllib.request, urllib.error
from pathlib import Path

env = {}
for line in Path('.env').read_text(encoding='utf-8-sig').splitlines():
    line = line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    k, v = line.split('=', 1)
    env[k.strip()] = v.strip().strip('"').strip("'")

URL = env['REPORT_MODEL_URL'].rstrip('/') + '/chat/completions'
KEY = env['REPORT_MODEL_KEY']
MODEL = env['REPORT_MODEL_NAME']

def call(thinking, label, timeout=120):
    body = {'model': MODEL, 'messages': [{'role': 'user', 'content': '只回复两个字：正常'}], 'max_tokens': 16}
    if thinking:
        body['thinking'] = {'type': 'enabled'}; body['reasoning_effort'] = 'low'
    else:
        body['thinking'] = {'type': 'disabled'}
    data = json.dumps(body).encode()
    req = urllib.request.Request(URL, data, {'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json'})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.load(r)
        dt = time.monotonic() - t0
        content = (resp.get('choices') or [{}])[0].get('message', {}).get('content', '')
        return ('OK %.1fs %r' % (dt, content[:40]), dt, True)
    except Exception as e:
        dt = time.monotonic() - t0
        return ('FAIL %.1fs %s: %s' % (dt, type(e).__name__, str(e)[:90]), dt, False)

print('endpoint=%s  model=%s' % (URL.replace('https://', ''), MODEL))
for i in range(2):
    msg, dt, ok = call(True, 'thinking=enabled')
    print('  [thinking=enabled]   %s' % msg)
for i in range(2):
    msg, dt, ok = call(False, 'thinking=disabled')
    print('  [thinking=disabled]  %s' % msg)
