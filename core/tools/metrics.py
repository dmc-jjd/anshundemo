"""metrics 域工具：指标计算与 TOP10 可编辑表。自 `app/tool.py` 原样搬出，逻辑未改。

`calculate_metrics` 里的预警真值集仍是字面量——数据化属 S7，本轮不动（见任务分解 §6 D3）。
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime,timedelta

from core.tools.contracts import ToolResult
from core.tools._shared import records_of


def calculate_metrics(args,ctx):
    records=records_of(ctx,args['records_ref']); sentiment=Counter(r['sentiment'] or '未知' for r in records); platform=Counter(r['platform'] or '未知' for r in records)
    metrics={'record_count':len(records),'sentiment':dict(sentiment),'platform':dict(platform),'warning_raw_count':sum(str(r.get('warning','')).strip() in ('是','已预警','1','true','TRUE','预警') for r in records)}
    day=Counter()
    for r in records:
        value=str(r.get('published',''))
        try:
            if re.fullmatch(r'\d+(?:\.\d+)?',value):
                key=(datetime(1899,12,30)+timedelta(days=float(value))).date().isoformat()
            else: key=value[:10]
            if key: day[key]+=1
        except (ValueError,OverflowError): pass
    metrics['daily_count']=dict(sorted(day.items()))
    metrics['peak_day']=max(day,key=day.get) if day else None
    if args.get('negative_ref'): metrics['negative_count']=len(records_of(ctx,args['negative_ref']))
    if args.get('confirmed_event_groups_ref'):
        groups=ctx.store.get_artifact(args['confirmed_event_groups_ref'])['groups']; metrics['confirmed_event_count']=len(groups)
        metrics['confirmed_event_member_ids']=[x for g in groups for x in g['member_ids']]
    denom=args.get('denominator')
    if denom is not None: metrics['ratio']=None if not denom else len(records)/denom
    ref=ctx.store.put_artifact(ctx.task_id,'metrics',metrics)
    return ToolResult(status='needs_review' if denom==0 else 'ok',data_ref=ref,method='source record counts and separately confirmed event counts',unresolved=[{'kind':'zero_denominator','question':'分母为零，比例缺失'}] if denom==0 else [])

def build_table(args,ctx):
    if not args.get('confirmed_event_groups_ref') or not args.get('ranking_rule'):
        return ToolResult(status='needs_review',method='editable table requires confirmed events and ranking rule',unresolved=[{'kind':'top10_rule','question':'缺少确认事件组或 TOP10 排序规则'}])
    groups=ctx.store.get_artifact(args['confirmed_event_groups_ref'])['groups']
    if args['ranking_rule']!='member_count_desc':
        return ToolResult(status='needs_review',method='unsupported ranking rule',unresolved=[{'kind':'top10_rule','question':'排序规则尚未实现或确认'}])
    ordered=sorted(groups,key=lambda g:(-len(g['member_ids']),g['member_ids'][0] if g['member_ids'] else ''))[:10]
    rows=[{'rank':i,'member_ids':g['member_ids'],'title':g.get('title') or '待核对代表标题','heat':None} for i,g in enumerate(ordered,1)]
    ref=ctx.store.put_artifact(ctx.task_id,'top10_table',{'rows':rows,'ranking_rule':args['ranking_rule'],'fact_ref':args.get('fact_ref'),'editable_word_table':True})
    return ToolResult(status='needs_review',data_ref=ref,method='confirmed-event member count ranking; heat still unconfirmed',unresolved=[{'kind':'heat_rule','question':'热度星级缺少来源规则'}])

HANDLERS={f.__name__:f for f in (calculate_metrics,build_table)}
