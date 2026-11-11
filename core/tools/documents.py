"""documents 域工具：报告文档解析与结构比对。自 `app/tool.py` 原样搬出，逻辑未改。

S2 临时债（RISK-8）：`app.template_compare` 的两个纯函数仍留在 app，本模块顶部回指它。
S6 随 template_compare 一并上移时消除。不改成依赖注入（会改 handler 的 (args, ctx) 签名），
也不复制实现（会引入行为分叉）——两者风险都比这条临时回指大。
"""

from __future__ import annotations

from app.schemas import ToolResult
from app.template_compare import parse_report_document,compare_reports


def parse_report_document_tool(args,ctx):
    data=parse_report_document(args['path']); ref=ctx.store.put_artifact(ctx.task_id,'parsed_document',data)
    return ToolResult(status='ok',data_ref=ref,method='OOXML blocks with original positions')

def compare_report_structures(args,ctx):
    data=compare_reports([ctx.store.get_artifact(x) for x in args['document_refs']]); ref=ctx.store.put_artifact(ctx.task_id,'template_comparison',data)
    return ToolResult(status='needs_review',data_ref=ref,method='local sequence alignment; semantic differences unconfirmed',unresolved=[{'kind':'template_review','question':'差异与槽位需模型或人工检查'}])

HANDLERS={f.__name__:f for f in (parse_report_document_tool,compare_report_structures)}
