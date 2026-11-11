from __future__ import annotations
from difflib import SequenceMatcher
import hashlib,re
from pathlib import Path
from .ooxml import read_docx

NUMBER_RE=re.compile(r'\d+(?:\.\d+)?%?')

def parse_report_document(path:str)->dict:
    doc=read_docx(Path(path)); doc['sha256']=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return doc

def compare_reports(documents:list[dict])->dict:
    if len(documents)<2: raise ValueError('at_least_two_documents')
    base=documents[0]['blocks']; alignments=[]; unmatched=[]; occurrences=[]
    for d in documents:
        for b in d['blocks']:
            for m in NUMBER_RE.finditer(b['text']):
                occurrences.append({'id':f"{d['sha256'][:10]}:{b['index']}:{m.start()}",'file':d['path'],'block':b['index'],'start':m.start(),'end':m.end(),'value':m.group()})
    for d in documents[1:]:
        other=d['blocks']; matcher=SequenceMatcher(None,[b['text'] for b in base],[b['text'] for b in other],autojunk=False)
        for tag,a0,a1,b0,b1 in matcher.get_opcodes():
            item={'base_file':documents[0]['path'],'other_file':d['path'],'type':tag,'base_blocks':[x['index'] for x in base[a0:a1]],'other_blocks':[x['index'] for x in other[b0:b1]],'base_text':[x['text'] for x in base[a0:a1]],'other_text':[x['text'] for x in other[b0:b1]]}
            alignments.append(item)
            if tag!='equal': unmatched.append(item)
    return {'documents':[{'path':d['path'],'sha256':d['sha256'],'block_count':len(d['blocks'])} for d in documents], 'alignments':alignments,'unresolved':unmatched,'occurrences':occurrences,'method':'SequenceMatcher anchored by exact block text; semantic alignment requires review'}

