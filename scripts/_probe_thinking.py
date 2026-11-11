"""探针：thinking=enabled 时 content 与 reasoning_content 分别是什么。"""
import json, urllib.request
from pathlib import Path

env = {}
for line in Path('.env').read_text(encoding='utf-8-sig').splitlines():
    line = line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k, v = line.split('=', 1); env[k.strip()] = v.strip().strip('"').strip("'")

URL = env['REPORT_MODEL_URL'].rstrip('/') + '/chat/completions'
KEY = env['REPORT_MODEL_KEY']; MODEL = env['REPORT_MODEL_NAME']

def call(thinking, label):
    body = {'model': MODEL, 'messages': [{'role':'user','content':'只输出一个JSON对象：{"a":1}'}],
            'max_tokens': 2000, 'response_format': {'type':'json_object'}}
    if thinking: body['thinking'] = {'type':'enabled'}; body['reasoning_effort'] = 'low'
    data = json.dumps(body).encode()
    req = urllib.request.Request(URL, data, {'Authorization':'Bearer '+KEY,'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r: resp = json.load(r)
    msg = (resp.get('choices') or [{}])[0].get('message') or {}
    print('%s: content=%r' % (label, msg.get('content')))
    print('      reasoning_content=%r' % (msg.get('reasoning_content')))
    print('      message keys=%s finish_reason=%s' % (sorted(msg.keys()), (resp.get('choices') or [{}])[0].get('finish_reason')))

print('model', MODEL)
call(True, 'thinking=enabled')
