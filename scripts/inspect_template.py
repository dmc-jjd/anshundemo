from __future__ import annotations
import hashlib,json,sys,zipfile,xml.etree.ElementTree as ET
from pathlib import Path

W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
path=Path(sys.argv[1]); raw=path.read_bytes(); root=ET.fromstring(zipfile.ZipFile(path).read('word/document.xml'))
body=root.find(f'{W}body'); blocks=[]
for i,block in enumerate(body):
    if block.tag not in (f'{W}p',f'{W}tbl'): continue
    paragraphs=[block] if block.tag==f'{W}p' else list(block.iter(f'{W}p'))
    output=[]
    for p in paragraphs:
        runs=[]
        for r in p.iter(f'{W}r'):
            text=''.join(t.text or '' for t in r.iter(f'{W}t'))
            if not text: continue
            color=r.find(f'{W}rPr/{W}color'); highlight=r.find(f'{W}rPr/{W}highlight'); shade=r.find(f'{W}rPr/{W}shd')
            runs.append({'text':text,'color':color.attrib.get(f'{W}val') if color is not None else None,'highlight':highlight.attrib.get(f'{W}val') if highlight is not None else None,'shading':shade.attrib.get(f'{W}fill') if shade is not None else None})
        if runs: output.append({'text':''.join(x['text'] for x in runs),'runs':runs})
    if output: blocks.append({'index':i,'kind':'table' if block.tag==f'{W}tbl' else 'paragraph','paragraphs':output})
out={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'blocks':blocks}
if len(sys.argv)>2: Path(sys.argv[2]).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
else: print(json.dumps(out,ensure_ascii=True,indent=2))
