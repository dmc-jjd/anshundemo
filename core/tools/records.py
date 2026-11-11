"""records 域工具：导入、筛选、分类、材料选择与证据读取。自 `app/tool.py` 原样搬出，逻辑未改。

三个数据面常量（必需列 / 列名映射 / 摘要列）与函数一同搬来，仍从 `vocabulary` 读取，
不回落字面量——records 字段序由 `COLUMN_MAP` 的键序决定（见 tests/test_s2_manifest_vocabulary.py）。
"""

from __future__ import annotations

import hashlib,re
from datetime import datetime,timedelta
from pathlib import Path

from core.tools.ooxml import read_xlsx
from core.tools.contracts import ToolResult
from core.tools import vocabulary
from core.tools._shared import records_of

REQUIRED_COLUMNS=vocabulary.required_columns()
COLUMN_MAP=vocabulary.column_map()
SUMMARY_COLUMNS=vocabulary.summary_columns()


def import_records(args,ctx):
    path=Path(args['path']); sheet=int(args.get('sheet_index',3))
    book=read_xlsx(path,sheet_index=sheet)
    rows=book['rows']; header=rows[0]['cells']
    for column in REQUIRED_COLUMNS:
        if column not in header: raise ValueError('missing_required_columns')
    records=[]; file_hash=hashlib.sha256(path.read_bytes()).hexdigest()
    for row in rows[1:]:
        cells=row['cells']; data={key:(cells[i] if i<len(cells) else '') for i,key in enumerate(header)}
        if not any(data.values()): continue
        rid=f'{file_hash[:12]}:{book["sheet"]}:{row["excel_row"]}'
        published=data.get('发布时间','')
        if re.fullmatch(r'\d+(?:\.\d+)?',published):
            try:published=(datetime(1899,12,30)+timedelta(days=float(published))).isoformat(timespec='minutes')
            except (ValueError,OverflowError):pass
        mapped={field:data.get(column,'') for column,field in COLUMN_MAP.items()}
        mapped['published']=published
        records.append({
            'id':rid,
            **mapped,
            'summary':data.get(SUMMARY_COLUMNS[0]) or (data.get(SUMMARY_COLUMNS[1],'') or '')[:1200],
            'source_ref':{'file_hash':file_hash,'sheet':book['sheet'],'row':row['excel_row']},
        })
    ref=ctx.store.put_artifact(ctx.task_id,'records',{'records':records,'file_hash':file_hash,'header':header,'sheet':book['sheet']})
    return ToolResult(status='ok',data_ref=ref,method=f'OOXML sheet {sheet}; every nonempty source row retained',warnings=[f'{len(records)} source rows'])

def filter_records(args,ctx):
    records=records_of(ctx,args['records_ref']); scope=args.get('scope','negative')
    if scope=='negative': selected=[r for r in records if '负' in r.get('sentiment','')]
    elif scope=='positive': selected=[r for r in records if r.get('sentiment')=='正面']
    elif scope=='neutral': selected=[r for r in records if r.get('sentiment')=='中性']
    elif scope in ('warning','negative_warning','negative_or_warning'):
        vals={str(r.get('warning','')).strip() for r in records}
        if scope!='negative_or_warning' and not any(v in ('是','已预警','1','true','TRUE','预警') for v in vals):
            return ToolResult(status='needs_review',method='warning field examined',unresolved=[{'kind':'warning_rule','question':'预警字段没有可确认的真值规则','values':sorted(vals)[:20]}])
        truth=('是','已预警','1','true','TRUE','预警')
        if scope=='negative_or_warning': selected=[r for r in records if '负' in r.get('sentiment','') or str(r.get('warning','')).strip() in truth]
        else: selected=[r for r in records if str(r.get('warning','')).strip() in truth and (scope=='warning' or '负' in r.get('sentiment',''))]
    elif scope=='media': selected=[r for r in records if r.get('media_level')==args.get('media_level')]
    else: raise ValueError('unknown_scope')
    ref=ctx.store.put_artifact(ctx.task_id,'records',{'records':selected,'scope':scope,'parent_ref':args['records_ref']})
    return ToolResult(status='ok',data_ref=ref,method=f'exact field filter: {scope}',warnings=[f'{len(selected)} selected of {len(records)}'])

def classify_records(args,ctx):
    records=records_of(ctx,args['records_ref']); items=[{'record_id':r['id'],'category':r['category'] or None} for r in records]
    ref=ctx.store.put_artifact(ctx.task_id,'classifications',{'items':items,'all_record_ids':[r['id'] for r in records]})
    missing=sum(x['category'] is None for x in items)
    return ToolResult(status='needs_review' if missing else 'ok',data_ref=ref,method='source event category field; blanks remain blank',warnings=[f'{missing} blank source categories'] if missing else [],unresolved=[{'kind':'missing_source_category','question':'原始分类为空；请运行独立聚类候选工具并人工确认'}] if missing else [])

def select_materials(args,ctx):
    records=records_of(ctx,args['records_ref']); limit=int(args.get('limit',10))
    items=[{'record_id':r['id'],'title':r['title'],'source_ref':r['source_ref']} for r in records[:limit]]
    ref=ctx.store.put_artifact(ctx.task_id,'materials',{'items':items,'selection_rule':'source row order; representative quality unconfirmed'})
    return ToolResult(status='needs_review',data_ref=ref,method='source order preview only',unresolved=[{'kind':'selection_rule','question':'代表材料和 TOP10 排序规则待确认'}])

def read_evidence(args,ctx):
    data=ctx.store.get_artifact(args['data_ref']); ref=ctx.store.put_artifact(ctx.task_id,'evidence',data)
    return ToolResult(status='ok',data_ref=ref,method='local artifact read',tool_version='1')

HANDLERS={f.__name__:f for f in (import_records,filter_records,classify_records,select_materials,read_evidence)}
