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

FRAME_MIN_LEN=6
FRAME_COVER_LEN=4
FRAME_PLAIN_LEN=16
_FRAME_PUNCT=frozenset('。！？：；')
_FRAME_START=frozenset('。！？\n')

def _covered_long_equals(base,other,min_len=FRAME_COVER_LEN):
    cover=[False]*len(base)
    for tag,a0,a1,b0,b1 in SequenceMatcher(None,base,other,autojunk=False).get_opcodes():
        if tag=='equal' and (a1-a0)>=min_len:
            for i in range(a0,a1):
                cover[i]=True
    return cover

def _is_connector_frame(span,start,end,n,starts_boundary=False):
    if not re.search(r'[\u4e00-\u9fffA-Za-z0-9]',span): return False
    punct=span.endswith(tuple(_FRAME_PUNCT)) or ('：' in span) or ('。' in span)
    if (start==0 or starts_boundary or punct) and len(span)>=FRAME_COVER_LEN:
        return True
    return False

def _trim_coincidental_list_prefix(span,start):
    """Drop a leading '、碰巧相同的类目' so the frame starts at 等方面 / 。 / ："."""
    if not span.startswith('、'):
        return span,start
    for marker in ('等方面','等。','。','：'):
        index=span.find(marker)
        if index>0:
            return span[index:],start+index
    return span,start

def shared_paragraph_frames(texts,min_len=FRAME_COVER_LEN):
    """Long connector phrases shared by every paragraph in *texts* (first is the base)."""
    if not texts or any(not isinstance(item,str) for item in texts):
        return []
    base=texts[0]
    if len(texts)<2 or not base:
        return []
    cover=[True]*len(base)
    for other in texts[1:]:
        one=_covered_long_equals(base,other,min_len)
        cover=[flag and hit for flag,hit in zip(cover,one)]
    frames=[]
    i=0
    while i<len(base):
        if not cover[i]:
            i+=1
            continue
        j=i
        while j<len(base) and cover[j]:
            j+=1
        span=base[i:j]
        starts_boundary=i==0 or base[i-1] in _FRAME_START
        keep=_is_connector_frame(span,i,j,len(base),starts_boundary)
        if not keep and starts_boundary and len(span)>=min_len and re.search(r'[\u4e00-\u9fffA-Za-z0-9]',span):
            keep=True
        if keep:
            span,i=_trim_coincidental_list_prefix(span,i)
            if len(span)>=FRAME_COVER_LEN:
                frames.append({'start':i,'end':j,'text':span})
        i=j
    return frames

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
    corresponding={b['index']:[] for b in base}
    for item in alignments:
        if item['type'] not in ('equal','replace'): continue
        if len(item['base_blocks'])==1 and len(item['other_blocks'])==1:
            corresponding[item['base_blocks'][0]].append(item['other_text'][0])
    intra=[]
    for block in base:
        others=corresponding.get(block['index']) or []
        frames=shared_paragraph_frames([block['text'],*others]) if others else []
        if frames:
            intra.append({'base_block':block['index'],'frames':[{'text':f['text'],'start':f['start'],'end':f['end']} for f in frames]})
    return {'documents':[{'path':d['path'],'sha256':d['sha256'],'block_count':len(d['blocks'])} for d in documents], 'alignments':alignments,'unresolved':unmatched,'occurrences':occurrences,'intra_paragraph_frames':intra,'method':'SequenceMatcher anchored by exact block text, plus intra-paragraph shared frames; semantic alignment requires review'}
