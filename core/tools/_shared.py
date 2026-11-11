"""域工具共享小件：分词与工件记录展开。自 `app/tool.py` 原样搬出，逻辑未改。"""

from __future__ import annotations

import re


def words(text:str)->set[str]:
    text=re.sub(r'\s+','',str(text or '').lower())
    chinese=re.findall(r'[\u4e00-\u9fff]{2,}|[a-z0-9]{3,}',text)
    out=set()
    for chunk in chinese:
        if re.fullmatch(r'[\u4e00-\u9fff]+',chunk):
            out.update(chunk[i:i+2] for i in range(len(chunk)-1))
        else: out.add(chunk)
    return out


def records_of(ctx,ref):
    obj=ctx.store.get_artifact(ref)
    return obj['records'] if isinstance(obj,dict) and 'records' in obj else obj
