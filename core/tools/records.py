"""records 域工具：导入、筛选、分类、材料选择与证据读取。自 `app/tool.py` 原样搬出，逻辑未改。

三个数据面常量（必需列 / 列名映射 / 摘要列）**不再**以模块级快照存在——这是同一份词表的
第二份快照（第一份在 `core/tool.py`），两份各按自己的 import 时机冻结，改一份不会让另一份红。
现在 `import_records()` 在函数内按当前包（或显式 `package=` 的包）取，records 工件字段序
仍由列名映射的键序决定（见 tests/test_s2_manifest_vocabulary.py），行为逐字节不变。

三不变量（`core/packages/` 同一套）：① 模块级包派生常量为零；② 不在请求期切包；
③ package 不进 artifact payload。
"""

from __future__ import annotations

import hashlib,re
from datetime import datetime,timedelta
from pathlib import Path

from core.text import NORMALIZATION_VERSION, normalize_record
from core.tools.ooxml import read_xlsx
from core.tools.contracts import ToolResult
from core.tools import vocabulary
from core.tools._shared import records_of


def _data_fields(package=None):
    """`(必需列, 列名映射, 摘要列)`：函数内按包读，模块级不留快照。"""
    return (vocabulary.required_columns(package), vocabulary.column_map(package),
            vocabulary.summary_columns(package))


def import_records(args,ctx):
    path=Path(args['path'])
    if args.get('sheet_index') is None:
        sheet=vocabulary.sheet_index(getattr(ctx,'package',None))
    else:
        sheet=int(args['sheet_index'])
    required_columns, column_map, summary_columns = _data_fields(getattr(ctx,'package',None))
    book=read_xlsx(path,sheet_index=sheet)
    rows=book['rows']; header=rows[0]['cells']
    for column in required_columns:
        if column not in header: raise ValueError('missing_required_columns')
    records=[]; file_hash=hashlib.sha256(path.read_bytes()).hexdigest()
    for row in rows[1:]:
        cells=row['cells']; data={key:(cells[i] if i<len(cells) else '') for i,key in enumerate(header)}
        if not any(data.values()): continue
        rid=f'{file_hash[:12]}:{book["sheet"]}:{row["excel_row"]}'
        published_column=next((column for column,field in column_map.items() if field=='published'),None)
        published=data.get(published_column,'') if published_column else ''
        if re.fullmatch(r'\d+(?:\.\d+)?',published):
            try:published=(datetime(1899,12,30)+timedelta(days=float(published))).isoformat(timespec='minutes')
            except (ValueError,OverflowError):pass
        mapped={field:data.get(column,'') for column,field in column_map.items()}
        mapped['published']=published
        summary=(data.get(summary_columns[0]) or '') if summary_columns else ''
        if not summary:
            for column in summary_columns[1:]:
                summary=data.get(column) or ''
                if summary: break
            summary=summary[:1200]
        records.append(normalize_record({
            'id':rid,
            **mapped,
            'summary':summary,
            'source_ref':{'file_hash':file_hash,'sheet':book['sheet'],'row':row['excel_row']},
        }))
    ref=ctx.store.put_artifact(ctx.task_id,'records',{'records':records,'file_hash':file_hash,'header':header,'sheet':book['sheet'],'normalization':NORMALIZATION_VERSION})
    return ToolResult(status='ok',data_ref=ref,method=f'OOXML sheet {sheet}; every nonempty source row retained',warnings=[f'{len(records)} source rows'])

def _clause_matches(record, clause, contract):
    if not clause:
        return False
    if isinstance(clause, str):
        return _scope_matches(record, clause, contract)
    sentiment_cfg = contract.get('sentiment') or {}
    warning_cfg = contract.get('warning') or {}
    field = sentiment_cfg.get('field') or 'sentiment'
    warning_field = warning_cfg.get('field') or 'warning'
    text = str(record.get(field) or '')
    warning_value = str(record.get(warning_field) or '').strip()
    truth = {str(item).strip() for item in (warning_cfg.get('truth') or ())}
    parts = []
    if 'contains' in clause:
        parts.append(any(token in text for token in clause.get('contains') or ()))
    if 'values' in clause:
        parts.append(text in {str(item) for item in clause.get('values') or ()})
    if clause.get('warning_truth'):
        parts.append(warning_value in truth)
    if 'any' in clause:
        parts.append(any(_clause_matches(record, item, contract) for item in clause.get('any') or ()))
    if 'all' in clause:
        parts.append(all(_clause_matches(record, item, contract) for item in clause.get('all') or ()))
    return any(parts) if parts else False


def _scope_spec(scope, contract):
    sentiment_cfg = contract.get('sentiment') or {}
    warning_cfg = contract.get('warning') or {}
    scopes = {}
    scopes.update(sentiment_cfg.get('scopes') or {})
    scopes.update(warning_cfg.get('scopes') or {})
    return scopes.get(scope)


def _scope_matches(record, scope, contract):
    spec = _scope_spec(scope, contract)
    if spec is None:
        raise ValueError('unknown_scope')
    return _clause_matches(record, spec, contract)


def _truth_present(records, contract):
    warning_cfg = contract.get('warning') or {}
    field = warning_cfg.get('field') or 'warning'
    truth = {str(item).strip() for item in (warning_cfg.get('truth') or ())}
    return any(str(record.get(field) or '').strip() in truth for record in records)


def filter_records(args,ctx):
    records=records_of(ctx,args['records_ref']); scope=args.get('scope','negative')
    if scope=='media':
        selected=[r for r in records if r.get('media_level')==args.get('media_level')]
    else:
        contract=vocabulary.filter_contract(getattr(ctx,'package',None))
        spec=_scope_spec(scope, contract)
        if spec is None:
            raise ValueError('unknown_scope')
        if isinstance(spec, dict) and spec.get('require_truth_present'):
            vals={str(r.get((contract.get('warning') or {}).get('field') or 'warning','')).strip() for r in records}
            if not _truth_present(records, contract):
                return ToolResult(status='needs_review',method='warning field examined',unresolved=[{'kind':'warning_rule','question':'预警字段没有可确认的真值规则','values':sorted(vals)[:20]}])
        selected=[r for r in records if _scope_matches(r, scope, contract)]
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
