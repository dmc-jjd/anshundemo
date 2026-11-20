"""Bind a category list's length, order and materials to confirmed category statistics."""
import re

def context_for(report,field):
    scope=field.get('category_coverage_scope')
    if not scope:return None
    if scope not in ('confirmed_events','warning_events','negative_warning_events'):raise ValueError('invalid_category_coverage_scope')
    counts={k:v for k,v in report.categories_for(scope,field.get('count_unit','events')).items() if v>0}
    rows=report.records_for(scope);total=sum(counts.values());result=[]
    for category,count in counts.items():
        examples=[];seen=set()
        for row in rows:
            if report.categories.get(row['id'])!=category or row['title'] in seen:continue
            seen.add(row['title'])
            examples.append({'ref':row['id'],'title':row['title'],'summary':row.get('summary','')[:500],
                             'source':row.get('source',''),'published':row.get('published','')})
            if len(examples)==3:break
        result.append({'category':category,'count':count,'percentage':f'{count/total*100:.2f}%','materials':examples})
    return {'scope':scope,'count_unit':field.get('count_unit','events'),'unit':'条' if field.get('count_unit')=='records' or report.record_mode else '件','total':total,'rows':result}

def validate_coverage(value,context):
    if context is None:return
    rows=context['rows']
    if not isinstance(value,list) or len(value)!=len(rows):raise ValueError('类别明细必须覆盖全部非零类别，不能截断或合并。')
    names=[row['category'] for row in rows]
    for text,expected in zip(value,names):
        text=re.sub(r'^\s*\d+[.、．]\s*','',str(text))
        if not text.startswith(expected):raise ValueError('类别明细顺序或类别名称与确认统计不一致：'+expected)
