"""End-to-end comparison of the draft's complete first major section."""
from __future__ import annotations
import json,re,sys,zipfile
from difflib import SequenceMatcher
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.config import DATA
from app.storage import Store
from app.export import export_docx
from app.ooxml import read_docx

task=Store(DATA).get_task('9720f37ef9d646c8b81655c2d0a73afb')
facts={'result_refs':task.result_refs,'report_month':'2026-10','input_refs':task.input_refs,
       'deduplicated_path':str(ROOT/'安顺市委10月负面预警数据（已去重）.xlsx')}
draft={'fact_ref':'first-section-test','sections':[]}
output=DATA/'first-section-preview.docx'
output.write_bytes(export_docx(draft,facts,None,'draft',[]))
reference=read_docx(ROOT/'2026年10月安顺市网络舆情分析报告.docx')['blocks']
candidate=read_docx(output)['blocks']
def section(blocks,prefix):
    return next((b['text'] for b in blocks if b['kind']=='paragraph' and b['text'].startswith(prefix)),None)
results=[]
for prefix in ('（一）','（二）','（三）','（四）'):
    expected=section(reference,prefix)
    actual=section(candidate,prefix)
    slots=re.findall(r'\{\{([^}]+)\}\}',actual or '')
    clean=re.sub(r'\{\{[^}]+\}\}','',actual or '')
    results.append({'paragraph':prefix,'reference_chars':len(expected or ''),'draft_chars':len(actual or ''),
                    'remaining_slots':slots,'text_overlap':round(SequenceMatcher(None,clean,expected or '',autojunk=False).ratio(),4)})
ref_table=next((b for b in reference if b['kind']=='table' and len(b.get('rows',[]))==11),None)
draft_table=next((b for b in candidate if b['kind']=='table' and len(b.get('rows',[]))==11),None)
with zipfile.ZipFile(output) as z:
    xml=z.read('word/document.xml')
    drawings=xml.count(b'<w:drawing')
audit=json.loads((DATA/'first-section-audit.json').read_text(encoding='utf-8'))
summary={'numeric_exact':{'matched':audit['matched'],'total':audit['total'],'accuracy':audit['accuracy']},
         'paragraphs':results,'table':{'reference_rows':len(ref_table['rows']) if ref_table else None,
                                      'draft_rows':len(draft_table['rows']) if draft_table else None,
                                      'remaining_slots':re.findall(r'\{\{([^}]+)\}\}',draft_table['text']) if draft_table else []},
         'chart_drawings':drawings,'passed':False}
summary['passed']=(audit['accuracy']>=.95 and all(r['text_overlap']>=.95 and not r['remaining_slots'] for r in results)
                   and not summary['table']['remaining_slots'] and drawings>=5)
path=DATA/'first-section-full-test.json'
path.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'numeric':summary['numeric_exact'],'text_overlap':[r['text_overlap'] for r in results],
                  'remaining_body_slots':sum(len(r['remaining_slots']) for r in results),
                  'remaining_table_slots':len(summary['table']['remaining_slots']),
                  'chart_drawings':drawings,'passed':summary['passed'],'artifact':str(path)},ensure_ascii=True))
