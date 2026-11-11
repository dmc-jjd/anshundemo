from pathlib import Path
from docx import Document
import openpyxl,json
root=Path.cwd(); out=root/'report_work';out.mkdir(exist_ok=True)
p=root/'2026年8月安顺市网络舆情分析报告.docx'
d=Document(p)
lines=[]
for i,p in enumerate(d.paragraphs):
 if p.text.strip(): lines.append(f'P{i} [{p.style.name}] {p.text}')
for i,t in enumerate(d.tables):
 lines.append(f'TABLE {i}')
 lines.extend(' | '.join(c.text for c in r.cells) for r in t.rows)
(out/'august_template.txt').write_text('\n'.join(lines),encoding='utf-8')
meta={'sections':[{'width':s.page_width.cm,'height':s.page_height.cm,'top':s.top_margin.cm,'bottom':s.bottom_margin.cm,'left':s.left_margin.cm,'right':s.right_margin.cm} for s in d.sections], 'paragraph_formats':[],'images':len(d.inline_shapes)}
for i,p in enumerate(d.paragraphs):
 if p.text.strip():
  meta['paragraph_formats'].append({'i':i,'text':p.text[:80],'alignment':str(p.alignment),'first_line':str(p.paragraph_format.first_line_indent),'spacing':str(p.paragraph_format.line_spacing),'runs':[{'text':r.text[:60],'font':r.font.name,'size':r.font.size.pt if r.font.size else None,'bold':r.bold} for r in p.runs[:5]]})
(out/'template_format.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
x=Path(r'C:\Users\knwl\Desktop\安顺市委10月总数据.xlsx'); w=openpyxl.load_workbook(x,read_only=True,data_only=True)
summary=[]
for s in w:
 rows=s.iter_rows(values_only=True); sample=[]
 for i,r in enumerate(rows):
  if i<7: sample.append([str(v)[:400] if v is not None else None for v in r])
 summary.append({'sheet':s.title,'rows':s.max_row,'columns':s.max_column,'sample':sample})
(out/'workbook_structure.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'output':str(out),'sheets':[(s.title,s.max_row,s.max_column) for s in w],'template_paragraphs':len(d.paragraphs),'template_tables':len(d.tables)},ensure_ascii=False))
