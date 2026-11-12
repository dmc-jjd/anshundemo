"""Read-only calculations and bounded material retrieval over a frozen fact version."""
from collections import Counter
from datetime import date
from functools import cached_property
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator

class Calculation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    @model_validator(mode='before')
    @classmethod
    def scope_for_metric(cls,value):
        if isinstance(value,dict):
            value=dict(value)
            if value.get('metric') in ('warning_percentage','category_names','category_statistics','leading_category','county_statistics'):
                value.setdefault('scope','confirmed_events')
                if value['scope']=='all_records':raise ValueError('该运算按已确认去重事件统计，请选择事件范围。')
            if value.get('metric') in ('sentiment_count','sentiment_percentage','scaled_count','peak_date','platform_names','platform_statistics') and value.get('scope','all_records')!='all_records':
                raise ValueError('该运算按全量原始记录统计，不能使用事件分母。')
        return value
    metric:Literal['count','scaled_count','sentiment_count','sentiment_percentage','warning_percentage','peak_date',
                   'category_names','category_statistics','leading_category','platform_names','platform_statistics',
                   'county_statistics','report_month','report_year','issue_number','publish_month','publish_day','publish_year','top10','constant']
    scope:Literal['all_records','confirmed_events','warning_events','negative_warning_events']='all_records'
    sentiment:Literal['正面','中性','负面']|None=None
    limit:int=Field(default=6,ge=1,le=20)
    precision:int=Field(default=2,ge=0,le=4)
    include_day_suffix:bool=False
    value:str|None=None

CALCULATION_CATALOG={
 'count':'指定范围的记录数或去重事件数；事件内多条只计一次',
 'scaled_count':'全量记录条数除以10000；万条单位，不带单位字样',
 'sentiment_count':'全量记录中指定调性的条数',
 'sentiment_percentage':'指定调性条数/全量记录数，输出带百分号的百分数',
 'warning_percentage':'确认重点预警范围内的事件数/全量记录数，输出百分数',
 'peak_date':'冻结统计中的信息峰值日期，格式X月X，可选择加日字',
 'category_names':'指定事件范围按已确认分类计数降序的类别列表',
 'category_statistics':'指定事件范围的全部类别、事件数与占比',
 'leading_category':'最高类别与占比的完整表述',
 'platform_names':'全量记录中实际平台条数降序，输出平台名称列表',
 'platform_statistics':'全量记录中实际平台、条数、占比的完整条目',
 'county_statistics':'指定事件范围按冻结属地识别结果计数；跨区/不明单列，分母为该范围全部事件',
 'report_month':'任务报告统计月份', 'report_year':'任务报告统计年份',
 'issue_number':'任务显式提供的期号，不从历史报告猜测',
 'publish_month':'任务显式成文日期的月份','publish_day':'任务显式成文日期的日','publish_year':'任务显式成文日期的年份',
 'top10':'冻结的负面且预警事件TOP10，事件内符合条件记录数，不是星级','constant':'固定值，用于表/图编号等结构性常量'}

class MissingReportInput(ValueError):pass

class FrozenReport:
    def __init__(self,store,task_id):
        self.store=store;self.state=store.get_task(task_id)
        if not self.state.fact_ref:raise ValueError('data_review_required')
        self.fact_ref=self.state.fact_ref;self.facts=store.get_artifact(self.fact_ref)
        self.refs=self.facts.get('result_refs') or self.state.result_refs
        self.metrics=self.facts.get('metrics') or store.get_artifact(self.refs['calculate_metrics'])
    @cached_property
    def records(self):return self.store.get_artifact(self.refs['import_records'])['records']
    @cached_property
    def by_id(self):return {r['id']:r for r in self.records}
    @cached_property
    def groups(self):return self.store.get_artifact(self.refs['confirmed_event_groups'])['groups'] if self.refs.get('confirmed_event_groups') else []
    @cached_property
    def categories(self):
        if not self.refs.get('confirmed_theme_groups'):return {}
        return {rid:g['candidate_theme'] for g in self.store.get_artifact(self.refs['confirmed_theme_groups'])['groups'] for rid in g['member_ids']}
    @cached_property
    def localities(self):
        if not self.refs.get('resolve_locality'):return {}
        return {x['record_id']:x['candidates'] for x in self.store.get_artifact(self.refs['resolve_locality'])['items']}
    def warned(self,r):return str(r.get('warning','')).strip() in ('是','已预警','1','true','TRUE','预警')
    def events(self,scope='confirmed_events'):
        if scope=='all_records':raise ValueError('event_scope_required')
        def matches(g):
            rows=[self.by_id[rid] for rid in g['member_ids']]
            return scope=='confirmed_events' or any(self.warned(r) and (scope!='negative_warning_events' or r.get('sentiment')=='负面') for r in rows)
        return [g for g in self.groups if matches(g)]
    def warning_scope(self):
        rules=self.state.metadata.get('template_rules',{})
        return 'warning_events' if rules.get('first_warning_scope')=='warning' else 'confirmed_events'
    def categories_for(self,scope='confirmed_events'):
        counts=Counter()
        for g in self.events(scope):
            labels={self.categories.get(rid,'未分类') for rid in g['member_ids']}
            if len(labels)!=1:raise ValueError('frozen_event_category_conflict')
            counts[next(iter(labels))]+=1
        return dict(sorted(counts.items(),key=lambda x:(-x[1],x[0])))
    def counties_for(self,scope='confirmed_events'):
        counts=Counter()
        for g in self.events(scope):
            labels={name for rid in g['member_ids'] for name in self.localities.get(rid,[])}
            counts[next(iter(labels)) if len(labels)==1 else '跨区涉及' if labels else '属地不明']+=1
        return dict(sorted(counts.items(),key=lambda x:(-x[1],x[0])))
    def parameters(self):
        params=self.state.metadata.get('report_parameters',{})
        return {'report_month':self.facts.get('report_month') or self.state.metadata.get('report_month'),**params}
    def calculate(self,spec):
        spec=Calculation.model_validate(spec);m=spec.metric;p=self.parameters();total=int(self.metrics.get('record_count',0))
        pct=lambda value,denom:format(value/denom*100,f'.{spec.precision}f')+'%' if denom else '0.'+'0'*spec.precision+'%'
        if m.startswith('publish_'):
            if not p.get('publication_date'):raise MissingReportInput('缺少报告成文日期，请在报告参数中填写。')
            day=date.fromisoformat(p['publication_date']);value=str(getattr(day,{'publish_year':'year','publish_month':'month','publish_day':'day'}[m]))
        elif m in ('report_month','report_year'):
            if not p.get('report_month'):raise MissingReportInput('缺少报告统计月份。')
            year,month=p['report_month'].split('-');value=str(int(month)) if m=='report_month' else year
        elif m=='issue_number':
            if p.get('issue_number') is None:raise MissingReportInput('缺少报告期号，请在报告参数中填写。')
            value=str(p['issue_number'])
        elif m=='count':value=str(total if spec.scope=='all_records' else len(self.events(spec.scope)))
        elif m=='scaled_count':value=format(total/10000,f'.{spec.precision}f').rstrip('0').rstrip('.') if spec.precision else str(round(total/10000))
        elif m in ('sentiment_count','sentiment_percentage'):
            if not spec.sentiment:raise ValueError('sentiment_required')
            n=self.metrics.get('sentiment',{}).get(spec.sentiment,0);value=str(n) if m=='sentiment_count' else pct(n,total)
        elif m=='warning_percentage':value=pct(len(self.events(spec.scope)),total)
        elif m=='peak_date':
            if not self.metrics.get('peak_day'):raise MissingReportInput('冻结统计缺少峰值日期。')
            day=date.fromisoformat(self.metrics['peak_day']);value=f'{day.month}月{day.day}'+('日' if spec.include_day_suffix else '')
        elif m in ('platform_names','platform_statistics'):
            counts=sorted(((name,n) for name,n in self.metrics.get('platform',{}).items() if n),key=lambda x:(-x[1],x[0]))
            # All actual platforms remain consistent across the names and entries.
            value='、'.join(name for name,n in counts) if m=='platform_names' else '；'.join(f'{name}{n}条，占{pct(n,total)}' for name,n in counts)
        elif m in ('category_names','category_statistics','leading_category'):
            counts=self.categories_for(spec.scope);denom=sum(counts.values())
            if not counts:raise MissingReportInput('缺少已确认的类别统计。')
            if m=='category_names':value='、'.join(list(counts)[:spec.limit])
            elif m=='category_statistics':value='；'.join(f'{name}{n}件，占{pct(n,denom)}' for name,n in counts.items())
            else:
                name,n=next(iter(counts.items()));value=f'{name}类信息占比约{pct(n,denom)}，占比较高'
        elif m=='county_statistics':
            counts=self.counties_for(spec.scope);denom=sum(counts.values())
            value='；'.join(f'{name}{n}件，占比{pct(n,denom)}' for name,n in counts.items())
        elif m=='top10':value=[[str(r['rank']),r['summary'],str(r['negative_warning_count'])] for r in self.facts.get('top10',[])]
        elif m=='constant':value=str(spec.value or '')
        else:raise ValueError('unsupported_calculation')
        parameter_ref=self.state.metadata.get('report_parameters_ref') if m=='issue_number' or m.startswith('publish_') else None
        return {'value':value,'source_refs':[parameter_ref or self.fact_ref],'calculation':spec.model_dump(),'fact_ref':self.fact_ref}
    def summary(self):
        return {'fact_ref':self.fact_ref,'report_parameters':self.parameters(),'record_count':self.metrics.get('record_count'),
                'scope_policy':{'section_one_categories_and_localities':'confirmed_events',
                                'confirmed_events_population':self.state.metadata.get('event_scope','negative_or_warning'),
                                'first_warning_events':self.warning_scope(),'top10':'negative_warning_events',
                                'note':'第一部分事件统计使用已确认并集事件；TOP10使用负面且预警交集内原始记录数。两者不可互换。'},
                'sentiment':self.metrics.get('sentiment'),'platform':self.metrics.get('platform'),'daily_count':self.metrics.get('daily_count'),
                'peak_day':self.metrics.get('peak_day'),'confirmed_event_count':len(self.groups),
                'warning_scope':self.warning_scope(),'category_event_counts':self.categories_for() if self.groups else {},
                'county_event_counts':self.counties_for() if self.groups else {},
                'county_basis':'冻结属地识别的唯一候选；跨区及不明单列，不推测归属',
                'top10':[{'rank':r['rank'],'summary':r['summary'],'negative_warning_count':r['negative_warning_count']} for r in self.facts.get('top10',[])]}

class MaterialQuery(BaseModel):
    model_config=ConfigDict(extra='forbid')
    focus:Literal['media','negative_events','all']='all'
    date:str|None=None
    category:str|None=None
    keyword:str=''
    sentiments:list[Literal['正面','中性','负面']]=Field(default_factory=list)
    distinct_events:bool=False
    offset:int=Field(default=0,ge=0,le=30000)
    limit:int=Field(default=8,ge=1,le=20)

def query_materials(report,args):
    q=MaterialQuery.model_validate(args);positions={rid:g for g in report.groups for rid in g['member_ids']}
    source_counts=Counter(r.get('source','') for r in report.records)
    def is_media(r):return any(x in str(r.get('media_level','')) for x in ('中央','全国','省级','央级'))
    rows=[]
    for r in report.records:
        if q.focus=='media' and not is_media(r):continue
        if q.focus=='negative_events' and (r['id'] not in positions or r.get('sentiment')!='负面'):continue
        if q.date and not str(r.get('published','')).startswith(q.date):continue
        if q.sentiments and r.get('sentiment') not in q.sentiments:continue
        if q.category and report.categories.get(r['id'])!=q.category:continue
        if q.keyword and q.keyword not in r['title']+' '+r.get('summary',''):continue
        rows.append(r)
    rows.sort(key=lambda r:(-int(is_media(r)),-len(positions.get(r['id'],{}).get('member_ids',[])),-source_counts[r.get('source','')],r['id']))
    # Avoid filling the packet with syndicated copies of one title.
    unique=[];seen=set();seen_events=set()
    for r in rows:
        key=r['title'].strip()
        if key in seen:continue
        event_id=positions.get(r['id'],{}).get('id')
        if q.distinct_events and event_id and event_id in seen_events:continue
        if event_id:seen_events.add(event_id)
        seen.add(key);unique.append(r)
    selected=unique[q.offset:q.offset+q.limit]
    return {'fact_ref':report.fact_ref,'total':len(unique),'offset':q.offset,'next_offset':q.offset+len(selected) if q.offset+len(selected)<len(unique) else None,
            'items':[{'ref':r['id'],'title':r['title'],'summary':r.get('summary','')[:500],'source':r.get('source',''),
                      'published':r.get('published',''),'media_level':r.get('media_level',''),'sentiment':r.get('sentiment',''),
                      'theme':report.categories.get(r['id'],''),'event_id':positions.get(r['id'],{}).get('id')} for r in selected]}
