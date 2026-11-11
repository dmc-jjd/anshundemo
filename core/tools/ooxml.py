"""Small, dependency-free readers for the OOXML subset used by the local demo."""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
import re, zipfile, xml.etree.ElementTree as ET

W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
S='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'

class UnreadableDocument(ValueError): pass

def read_docx(path:Path)->dict:
    path=Path(path)
    if not zipfile.is_zipfile(path): raise UnreadableDocument('unreadable_document: not an unencrypted OOXML ZIP')
    try:
        with zipfile.ZipFile(path) as z: root=ET.fromstring(z.read('word/document.xml'))
    except Exception as e: raise UnreadableDocument(f'unreadable_document: {e}') from e
    blocks=[]
    body=root.find(f'{W}body')
    if body is None: raise UnreadableDocument('unreadable_document: missing body')
    for i,child in enumerate(body):
        if child.tag==f'{W}p':
            text=''.join(t.text or '' for t in child.iter(f'{W}t'))
            if not text.strip(): continue
            st=child.find(f'.//{W}pStyle')
            style=st.attrib.get(f'{W}val','') if st is not None else ''
            blocks.append({'index':i,'kind':'paragraph','text':text,'style':style})
        elif child.tag==f'{W}tbl':
            rows=[]
            for tr in child.findall(f'{W}tr'):
                rows.append([''.join(t.text or '' for t in tc.iter(f'{W}t')) for tc in tr.findall(f'{W}tc')])
            blocks.append({'index':i,'kind':'table','rows':rows,'text':' | '.join(' / '.join(r) for r in rows)})
    if not blocks: raise UnreadableDocument('unreadable_document: no readable text')
    return {'path':str(path),'blocks':blocks}

def _col_index(ref:str)->int:
    letters=re.match(r'[A-Z]+',ref).group()
    n=0
    for c in letters: n=n*26+ord(c)-64
    return n-1

def read_xlsx(path:Path, max_rows:int|None=None, sheet_index:int=1)->dict:
    path=Path(path)
    if not zipfile.is_zipfile(path): raise ValueError('unreadable_spreadsheet')
    with zipfile.ZipFile(path) as z:
        shared=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            with z.open('xl/sharedStrings.xml') as f:
                for _,el in ET.iterparse(f,events=('end',)):
                    if el.tag==f'{S}si':
                        shared.append(''.join(t.text or '' for t in el.iter(f'{S}t'))); el.clear()
        sheet=f'xl/worksheets/sheet{sheet_index}.xml'
        if sheet not in z.namelist(): sheet=None
        if not sheet: raise ValueError('unreadable_spreadsheet: no worksheet')
        rows=[]
        with z.open(sheet) as f:
            for _,el in ET.iterparse(f,events=('end',)):
                if el.tag!=f'{S}row': continue
                cells={}
                for c in el.findall(f'{S}c'):
                    ref=c.attrib.get('r','A1'); typ=c.attrib.get('t','')
                    v=c.find(f'{S}v')
                    if typ=='inlineStr': value=''.join(t.text or '' for t in c.iter(f'{S}t'))
                    elif v is None: value=''
                    elif typ=='s': value=shared[int(v.text)] if v.text and int(v.text)<len(shared) else ''
                    else: value=v.text or ''
                    cells[_col_index(ref)]=value
                if cells:
                    row=['']*(max(cells)+1)
                    for j,v in cells.items(): row[j]=v
                    rows.append({'excel_row':int(el.attrib.get('r',len(rows)+1)),'cells':row})
                el.clear()
                if max_rows and len(rows)>=max_rows: break
    return {'path':str(path),'rows':rows,'sheet':sheet}
