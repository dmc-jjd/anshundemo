"""Three real model writing/review rounds; reference report is used only for scoring."""
from __future__ import annotations
import asyncio,json,re,sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from types import SimpleNamespace
from pydantic import BaseModel,Field
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.config import DATA
from app.model_client import invoke_agent
from app.ooxml import read_docx,read_xlsx
from app.storage import Store

class Writing(BaseModel):
    paragraph:str
class Review(BaseModel):
    issues:list[str]=Field(default_factory=list)
class Events:
    def __init__(self): self.items=[]
    def append_event(self,_,event): self.items.append(event)

async def main():
    events=Events(); context=SimpleNamespace(model_adapter=None,store=events,task_id='first-section-three-rounds')
    task=Store(DATA).get_task('9720f37ef9d646c8b81655c2d0a73afb')
    metrics=Store(DATA).get_artifact(task.result_refs['calculate_metrics'])
    rows=read_xlsx(ROOT/'安顺市委10月负面预警数据（已去重）.xlsx',sheet_index=3)['rows'][1:]
    cats=Counter(r['cells'][2] for r in rows); local=Counter(r['cells'][1] for r in rows)
    source=Store(DATA).get_artifact(task.result_refs['import_records'])['records']
    media=[r for r in source if r['media_level'] in ('全国','省级') and r['title']]
    evidence={'month':'2026-10','all_count':metrics['record_count'],'sentiment':metrics['sentiment'],
              'platform':metrics['platform'],'peak_day':metrics['peak_day'],'deduplicated_count':len(rows),
              'category_counts':dict(cats),'district_counts':dict(local),
              'media_examples':[{'title':r['title'],'source':r['source']} for r in media[:12]],
              'negative_examples':[r['cells'][0] for r in rows[:10]]}
    reference=read_docx(ROOT/'2026年10月安顺市网络舆情分析报告.docx')['blocks']
    target=[next(b['text'] for b in reference if b['text'].startswith(prefix)) for prefix in ('（一）','（二）','（三）','（四）')]
    path=DATA/'three-agent-rounds.json'
    saved=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    records=[r for r in saved.get('rounds',[]) if 'paragraphs' in r]
    prior=records[-1]['paragraphs'] if records else None
    feedback=(records[-1].get('format_issues',[])+records[-1].get('content_issues',[]))[:4] if records else []
    for round_number in range(len(records)+1,4):
        paragraphs=[]
        try:
            for index,prefix in enumerate(('（一）','（二）','（三）','（四）')):
                scoped=[{'month':evidence['month'],'all_count':evidence['all_count'],'sentiment':evidence['sentiment'],'peak_day':evidence['peak_day'],'deduplicated_count':evidence['deduplicated_count']},
                        {'month':evidence['month'],'all_count':evidence['all_count'],'platform':evidence['platform']},
                        {'month':evidence['month'],'media_examples':evidence['media_examples']},
                        {'month':evidence['month'],'deduplicated_count':evidence['deduplicated_count'],'category_counts':evidence['category_counts'],'district_counts':evidence['district_counts'],'negative_examples':evidence['negative_examples']}][index]
                payload={'task':f'只写安顺月报第一大部分{prefix}一段，保持正式公文句式。仅据证据写；未给出的同比和 TOP10 不编造。输出 paragraph 字符串。',
                         'evidence':scoped,'prior_draft':prior[index][:450] if prior else None,'review_feedback':feedback[:4]}
                writing=await invoke_agent('writer',payload,Writing,context)
                paragraphs.append(writing.paragraph)
        except Exception as exc:
            records.append({'round':round_number,'completed_paragraphs':paragraphs,'writer_error_type':type(exc).__name__,'http_status':getattr(exc,'code',None)})
            break
        overlaps=[round(SequenceMatcher(None,re.sub(r'\s+','',x),re.sub(r'\s+','',y),autojunk=False).ratio(),4) for x,y in zip(paragraphs,target)]
        numbers=[]
        for i,text in enumerate(paragraphs):
            numbers.append(re.findall(r'\d+(?:\.\d+)?%?',text))
        row={'round':round_number,'paragraphs':paragraphs,'overlap':overlaps,'numbers':numbers}
        records.append(row)
        (DATA/'three-agent-rounds.json').write_text(json.dumps({'reference_excluded_from_model_input':True,'rounds':records,'model_events':events.items},ensure_ascii=False,indent=2),encoding='utf-8')
        for role,key,review_payload in (
            ('format_reviewer','format_issues',{'paragraphs':paragraphs,'criteria':'检查格式和表达，仅输出 issues'}),
            ('content_reviewer','content_issues',{'paragraphs':paragraphs,'evidence':evidence,'criteria':'检查事实和数值，仅输出 issues'})):
            try:
                row[key]=(await invoke_agent(role,review_payload,Review,context)).issues
            except Exception as exc:
                row[key]=[]
                row[key+'_error']={'type':type(exc).__name__,'http_status':getattr(exc,'code',None)}
        prior=paragraphs; feedback=(row['format_issues']+row['content_issues'])[:4]
    result={'reference_excluded_from_model_input':True,'rounds':records,'model_events':events.items}
    path=DATA/'three-agent-rounds.json'; path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'rounds':[{'round':r['round'],'overlap':r.get('overlap'),'error_type':r.get('error_type')} for r in records],
                      'model_calls':len(events.items),'artifact':str(path)},ensure_ascii=True))
asyncio.run(main())
