"""Read-only reconciliation of the reference workbook and frozen event groups."""
import json,sys,re,hashlib
from pathlib import Path
from collections import Counter,defaultdict
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.storage import Store
from app.frozen_report import FrozenReport
from app.ooxml import read_xlsx

def compare(root=ROOT/'data'):
    report=FrozenReport(Store(root),'5108c8a9871a4ae5a97aab6dacd915ff')
    path=ROOT/'安顺市委10月负面预警数据（已去重）.xlsx';data=read_xlsx(path,sheet_index=3)
    header=data['rows'][0]['cells'];rows=[dict(zip(header,r['cells']))|{'excel_row':r['excel_row']} for r in data['rows'][1:]]
    by_url=defaultdict(list);by_title=defaultdict(list)
    for record in report.records:
        if record.get('url'):by_url[record['url'].strip()].append(record)
        by_title[record['title'].strip()].append(record)
    groups={rid:g['id'] for g in report.groups for rid in g['member_ids']};matches=[]
    for row in rows:
        candidates=by_url.get(row.get('网址','').strip(),[])
        method='url'
        if not candidates:candidates=by_title.get(row.get('原文标题','').strip(),[]);method='exact_original_title'
        matches.append({'row':row['excel_row'],'reference_title':row['标题'],'original_title':row.get('原文标题'),
            'url':row.get('网址'),'county':row.get('区县'),'category':row.get('事件分类'),'warning':row.get('是否预警'),
            'sentiment':row.get('舆情调性'),'duplicate_flag':row.get('是否事重复数据'),
            'method':method if candidates else 'unmatched','record_ids':[r['id'] for r in candidates],
            'current_groups':sorted({groups[r['id']] for r in candidates if r['id'] in groups})})
    matched_ids={rid for m in matches for rid in m['record_ids']}
    covered_groups={g for m in matches for g in m['current_groups']}
    ref_titles=Counter(row['标题'] for row in rows)
    group_sizes=Counter(len(g['member_ids']) for g in report.groups)
    warned=[r for r in report.records if report.warned(r)];negative=[r for r in report.records if r.get('sentiment')=='负面']
    groups_with_warning=sum(any(report.warned(report.by_id[rid]) for rid in g['member_ids']) for g in report.groups)
    singleton_not_warned=[g for g in report.groups if len(g['member_ids'])==1 and not report.warned(report.by_id[g['member_ids'][0]])]
    ref_by_title=defaultdict(set)
    for m in matches:ref_by_title[m['reference_title']].update(m['current_groups'])
    missing=[m for m in matches if not m['record_ids']]
    by_group=defaultdict(list)
    for m in matches:
        for key in m['current_groups']:by_group[key].append(m)
    uncovered_warned=[g for g in report.groups if g['id'] not in covered_groups and any(report.warned(report.by_id[x]) for x in g['member_ids'])]
    examples=[{'group_id':g['id'],'title':g['title'],'member_count':len(g['member_ids']),
               'warned_member_count':sum(report.warned(report.by_id[x]) for x in g['member_ids']),
               'representative':{k:report.by_id[g['representative_id']].get(k) for k in ['id','title','summary','published','url']}} for g in uncovered_warned]
    result={'source':str(path),'detail_sheet':data['sheet'],'reference_rows':len(rows),'reference_unique_titles':len(ref_titles),
        'task_id':report.state.id,'fact_ref':report.fact_ref,'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'reference_flags':{key:dict(Counter(row.get(key,'') for row in rows)) for key in ['是否预警','是否事重复数据','舆情调性','事件分类','区县']},
        'raw_counts':{'all':len(report.records),'negative':len(negative),'warning':len(warned),
                      'negative_and_warning':sum(report.warned(r) for r in negative),
                      'negative_or_warning':sum(report.warned(r) or r.get('sentiment')=='负面' for r in report.records)},
        'current_group_count':len(report.groups),'groups_with_warning':groups_with_warning,'groups_without_warning':len(report.groups)-groups_with_warning,
        'group_sizes':dict(group_sizes),'nonwarned_singletons':len(singleton_not_warned),
        'reference_matched_rows':sum(bool(m['record_ids']) for m in matches),'reference_unmatched_rows':len(missing),
        'covered_current_groups':len(covered_groups),'not_covered_current_groups':len(report.groups)-len(covered_groups),
        'uncovered_warned_groups':len(uncovered_warned),'reference_rows_collapsed_net':len(rows)-len(covered_groups),
        'current_groups_covering_multiple_reference_rows':sum(len(items)>1 for items in by_group.values()),
        'collapsed_examples':[{'current_group':key,'reference_titles':[x['reference_title'] for x in items]} for key,items in by_group.items() if len(items)>1][:8],
        'uncovered_warned_examples':examples[:6],
        'reference_titles_covering_multiple_current_groups':sum(len(g)>1 for g in ref_by_title.values()),
        'unmatched_examples':missing[:5],'split_examples':[{'reference_title':title,'current_groups':sorted(ids)} for title,ids in ref_by_title.items() if len(ids)>1][:8]}
    out=Path(root)/'reference-comparison';out.mkdir(exist_ok=True)
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'reference-row-matches.json').write_text(json.dumps(matches,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'uncovered-warned-groups.json').write_text(json.dumps(examples,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result
if __name__=='__main__':compare()
