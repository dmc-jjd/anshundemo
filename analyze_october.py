from pathlib import Path
import openpyxl,json,collections,re
root=Path.cwd();out=root/'report_work'
w=openpyxl.load_workbook(r'C:\Users\knwl\Desktop\安顺市委10月总数据.xlsx',read_only=True,data_only=True)
s=w['03101627'];it=s.iter_rows(values_only=True);headers=next(it);rows=[dict(zip(headers,r)) for r in it if any(v is not None for v in r)]
def count(key,rs=rows):return dict(collections.Counter(str(r.get(key) or '未标注') for r in rs).most_common())
neg=[r for r in rows if r['舆情调性']=='负面'];warn=[r for r in rows if r['是否预警']=='已预警']; nw=[r for r in neg if r['是否预警']=='已预警']
daily=collections.Counter(str(r['发布时间'])[:10] for r in rows)
result={'total':len(rows),'date_min':min(str(r['发布时间']) for r in rows),'date_max':max(str(r['发布时间']) for r in rows),'sentiment':count('舆情调性'),'platform':count('媒体环节'),'category':count('事件分类'),'warning':count('是否预警'),'negative_categories':count('事件分类',neg),'warn_categories':count('事件分类',warn),'warn_sentiment':count('舆情调性',warn),'negative_warning_total':len(nw),'daily':dict(sorted(daily.items())),'sources':count('来源信息'),'media_level':count('媒体级别'),'unique_urls':len(set(r['网址'] for r in rows)),'unique_titles':len(set(r['标题'] for r in rows)),'negative_unique_titles':len(set(r['标题'] for r in neg)),'negative_platform':count('媒体环节',neg),'pivot':{s.title:[list(r) for r in s.iter_rows(values_only=True)] for s in w if s.title!='03101627'}}
(out/'october_statistics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
(out/'all_records.json').write_text(json.dumps(rows,ensure_ascii=False,default=str),encoding='utf-8')
# Export categorized warning records and frequent titles, no personal contact details needed.
lines=[]
for i,r in enumerate(warn):
 lines.append(f"{i+1}. [{r['发布时间']}][{r['舆情调性']}][{r['事件分类'] or '未分类'}][{r['来源信息']}] {r['标题']}\n摘要：{str(r['摘要'] or '')[:1200]}\nURL：{r['网址']}")
(out/'warning_records.txt').write_text('\n\n'.join(lines),encoding='utf-8')
for label,rs in [('negative',neg),('positive',[r for r in rows if r['舆情调性']=='正面'])]:
 c=collections.Counter(str(r['标题']) for r in rs)
 (out/f'{label}_titles.txt').write_text('\n'.join(f'{n}\t{t}' for t,n in c.most_common(250)),encoding='utf-8')
peak=daily.most_common(5)
lines=[]
for day,n in peak:
 subset=[r for r in rows if str(r['发布时间']).startswith(day)]
 lines.append(f'日期 {day} 总量 {n}')
 lines.extend(f'{v}\t{k}' for k,v in collections.Counter(str(r['标题']) for r in subset).most_common(35))
(out/'peak_titles.txt').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps({k:result[k] for k in ['total','date_min','date_max','sentiment','platform','category','warning','warn_categories','negative_warning_total']},ensure_ascii=False))
