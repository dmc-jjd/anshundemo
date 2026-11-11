"""locality 域工具：属地候选识别。自 `app/tool.py` 原样搬出，逻辑未改。

`LOCALITIES` 在函数内从 `vocabulary` 取，不在模块级取——避免 import 期依赖包配置。
"""

from __future__ import annotations

from core.tools.contracts import ToolResult
from core.tools import vocabulary
from core.tools._shared import records_of


def resolve_locality(args,ctx):
    records=records_of(ctx,args['records_ref']); terms=vocabulary.localities()
    results=[]; unresolved=[]
    for r in records:
        text=r['title']+' '+r.get('summary',''); hits=[k for k,ws in terms.items() if any(w in text for w in ws)]
        results.append({'record_id':r['id'],'candidates':hits,'evidence':hits})
        if len(hits)!=1: unresolved.append({'kind':'locality','record_ids':[r['id']],'question':'属地不唯一或缺失','candidates':hits})
    ref=ctx.store.put_artifact(ctx.task_id,'locality',{'items':results,'source_records_ref':args['records_ref']})
    return ToolResult(status='needs_review' if unresolved else 'ok',data_ref=ref,method='explicit district term match; no inferred locality',unresolved=unresolved[:20],warnings=[f'{len(unresolved)} locality rows need review'] if unresolved else [])

HANDLERS={f.__name__:f for f in (resolve_locality,)}
