"""Show redacted single-slot request shape and compare provider responses."""
from __future__ import annotations
import json,sys,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.config import DATA,MODEL_URL,MODEL_NAME,MODEL_KEY
from app.agent import AGENT_DEFINITIONS
from app.slot_writer import SlotAnswer
from app.storage import Store
from app.ooxml import read_docx

slot_id='B29_LIGHTGRAY_04'
manifest=json.loads((ROOT/'templates/anshun-colored/report.template.json').read_text(encoding='utf-8'))
slot=next(x for x in manifest['placeholders'] if x['id']==slot_id)
paragraph=next(b['text'] for b in read_docx(ROOT/'templates/anshun-colored/template-with-placeholders.docx')['blocks'] if b['text'].startswith('（三）') and '{{'+slot_id+'}}' in b['text'])
before,_,after=paragraph.partition('{{'+slot_id+'}}')
store=Store(DATA);task=store.get_task('9720f37ef9d646c8b81655c2d0a73afb')
records=store.get_artifact(task.result_refs['import_records'])['records']
media=[r for r in records if r.get('media_level') in ('全国','省级') and r.get('title')][:12]
evidence=[{'ref':r['id'],'title':r['title'],'source':r['source'],'category':r.get('category',''),'published':r.get('published','')} for r in media]
payload={'instruction':'只填写一个模板槽位，绝不重写整段。只输出 slot_id、value、source_refs 三个字段。value 应直接接在 before_text 和 after_text 之间，不能重复前后文字或标点。报道标题照来源标题原文引用，多个标题按模板标点连接；数字由程序填写，不能自行生成。source_refs 必须原样复制所引用记录的 ref，至少一个、最多三个；证据不足则返回空 value 和空 source_refs。',
         'slot':{'id':slot['id'],'semantic':slot['semantic'],'kind':slot['slot_type'],'required_source_fields':slot['source_fields_or_calculation'],'available_evidence_fields':['ref','title','source','category','published'],'before_text':before[-90:],'after_text':after[:90]},'evidence':evidence}
schema=json.dumps(SlotAnswer.model_json_schema(),ensure_ascii=False)
system=AGENT_DEFINITIONS['writer'].responsibility+'。'+AGENT_DEFINITIONS['writer'].boundary+'。只输出一个符合以下 JSON Schema 的对象，不要包装在其他字段内，不要解释或 Markdown：'+schema
base={'model':MODEL_NAME,'messages':[{'role':'system','content':system},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}],'response_format':{'type':'json_object'},'max_tokens':6000,'thinking':{'type':'enabled'},'reasoning_effort':'low'}
(DATA/'writer-request-redacted.json').write_text(json.dumps({'request_body':base,'authorization':'[redacted]'},ensure_ascii=False,indent=2),encoding='utf-8')
url=MODEL_URL.rstrip('/')
if not url.endswith('/chat/completions'):url+='/chat/completions'
def call(body):
    raw=json.dumps(body,ensure_ascii=False).encode()
    req=urllib.request.Request(url,raw,{'Authorization':'Bearer '+MODEL_KEY,'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=50) as res:
            obj=json.load(res)
            return {'status':res.status,'response_keys':list(obj),'finish_reason':(obj.get('choices') or [{}])[0].get('finish_reason'),'usage':obj.get('usage'),'content_chars':len(str((obj.get('choices') or [{}])[0].get('message',{}).get('content') or ''))}
    except urllib.error.HTTPError as exc:
        try: detail=json.loads(exc.read())
        except Exception: detail={}
        err=detail.get('error') or {}
        return {'status':exc.code,'error_type':err.get('type'),'error_code':err.get('code'),'error_message':str(err.get('message','')).replace(MODEL_KEY,'[redacted]')[:180]}
    except Exception as exc:return {'error_type':type(exc).__name__}

print(json.dumps({'slot_id':slot_id,'endpoint_path':url.split('api.deepseek.com')[-1],
                  'model':MODEL_NAME,'body_bytes':len(json.dumps(base,ensure_ascii=False).encode()),
                  'system_chars':len(system),'user_chars':len(base['messages'][1]['content']),
                  'evidence_count':len(evidence),'evidence_title_chars':sum(len(x['title']) for x in evidence),
                  'user_payload_shape':{'instruction':payload['instruction'],'slot':payload['slot'],
                                        'evidence_fields':list(evidence[0]),'example_evidence':{'ref':evidence[0]['ref'],'title':evidence[0]['title'],'source':evidence[0]['source']}}},ensure_ascii=False))
if '--dump-only' in sys.argv:
    raise SystemExit(0)
for name,body in [('exact_slot',base),('short_same_options',{**base,'messages':[base['messages'][0],{'role':'user','content':json.dumps({'slot_id':slot_id,'instruction':'返回该槽位的简短示例 JSON，value 为 空，source_refs 为空数组'},ensure_ascii=False)}]}),
                  ('short_low_tokens',{**base,'max_tokens':512,'messages':[base['messages'][0],{'role':'user','content':json.dumps({'slot_id':slot_id,'instruction':'返回 JSON：slot_id、value、source_refs'},ensure_ascii=False)}]})]:
    print(json.dumps({'case':name,'body_bytes':len(json.dumps(body,ensure_ascii=False).encode()),'result':call(body)},ensure_ascii=False))
