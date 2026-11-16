from __future__ import annotations
from difflib import SequenceMatcher
import hashlib,re
from pathlib import Path
from core.tools.ooxml import UnreadableDocument,read_docx
from core.tools.doc97 import _has_ole2_header,is_legacy_doc,read_doc

NUMBER_RE=re.compile(r'\d+(?:\.\d+)?%?')

#: 反向伪装（真的是 `.doc`、名字却是 `.docx`）的补救文案：要能指导用户怎么改。
LEGACY_DOC_RENAMED_HINT=('unreadable_document: 该文件实际是 Word 97-2003 (.doc) 格式，'
                         '请把扩展名改回 .doc 后重新上传')

def parse_report_document(path:str)->dict:
    # 唯一的格式派发点：`.doc` 与 `.docx` 在字节层不同，读取器各管一种。
    # documents.py 的 tool 复用本函数，别在下游再判一次扩展名。
    target=Path(path)
    try:
        doc=read_doc(target) if is_legacy_doc(target) else read_docx(target)
    except UnreadableDocument:
        # 反过来伪装的：真 `.doc` 被手动改名成 `.docx`（很常见的操作）。不补救的话用户只会
        # 收到「不是未加密的 OOXML ZIP」——看不出该怎么修。读 8 字节魔数的判定几乎零成本。
        if not is_legacy_doc(target) and _has_ole2_header(target):raise UnreadableDocument(LEGACY_DOC_RENAMED_HINT) from None
        raise
    doc['sha256']=hashlib.sha256(target.read_bytes()).hexdigest()
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
