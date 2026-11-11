"""Independent counts from frozen rows; checks calculations, not source truth."""
import json,sys
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.storage import Store
from app.frozen_report import FrozenReport
root=Path(sys.argv[1]);s=Store(root);r=FrozenReport(s,'5108c8a9871a4ae5a97aab6dacd915ff')
d=s.get_artifact(r.state.draft_ref);v={k:x['value'] for k,x in d['slot_values'].items()}
checks={};n=len(r.records);sentiment=Counter(x['sentiment'] for x in r.records);platform=Counter(x['platform'] for x in r.records)
checks['raw_record_count']=n==r.metrics['record_count']
checks['sentiment_totals']=dict(sentiment)==r.metrics['sentiment'] and sum(sentiment.values())==n
checks['platform_totals']=dict(platform)==r.metrics['platform'] and sum(platform.values())==n
for label,key in [('正面','positive'),('中性','neutral'),('负面','negative')]:
    checks[key+'_count']=v['b17_'+key+'_count']==str(sentiment[label])
    checks[key+'_percentage']=v['b17_'+key+'_ratio']==f'{sentiment[label]/n*100:.2f}%'
checks['warning_event_count']=v['b17_warning_count']==str(len(r.groups))
checks['warning_event_percentage']=v['b17_warning_ratio']==f'{len(r.groups)/n*100:.2f}%'
checks['event_count_consistency']=v['b30_negative_total']==str(len(r.groups))
checks['category_conservation']=sum(r.categories_for().values())==len(r.groups)
checks['locality_conservation']=sum(r.counties_for().values())==len(r.groups)
groups={g['id']:g for g in r.groups};expected=[]
for g in r.groups:
    count=sum(r.by_id[x].get('sentiment')=='负面' and str(r.by_id[x].get('warning','')).strip() in ('是','已预警','1','true','TRUE','预警') for x in g['member_ids'])
    if count:expected.append(count)
checks['top10_eligible_counts']= [int(row[2]) for row in v['b34_top10_table']]==sorted(expected,reverse=True)[:10]
for name,ref in d['chart_refs'].items():
    chart=s.get_artifact(ref);checks['chart_'+name+'_fact']=chart['fact_ref']==r.fact_ref
    checks['chart_'+name+'_sum']=sum(chart['counts'].values())==(len(r.groups) if name in ('theme','locality') else n)
checks['analysis_length']=300<=len(v.get('b40_analysis_paragraph',''))<=500
result={'checks':checks,'passed':sum(checks.values()),'total':len(checks),'limits':'验证冻结版本内部统计与导出一致性；不等同于原始来源真实性、属地识别正确率或全部分析文字准确率。',
        'frozen_summary_flags':[row['rank'] for row in r.facts.get('top10',[]) if row['summary'].isdigit()]}
(root/'data-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=True));assert all(checks.values())
