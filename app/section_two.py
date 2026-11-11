"""Second-section schemas and validation; all model instructions live in agent.py."""
import calendar,re
from datetime import date,datetime,timedelta,timezone
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field

POLICY_VERSION='anshun-mixed-risk-v3-seasonal-fallback'
ANALYSIS_POLICY_VERSION='anshun-causal-analysis-style-v7'
OUTLOOK_POLICY_VERSION='anshun-mixed-outlook-style-v8'
LOCAL_NAMES=('安顺','西秀','平坝','普定','镇宁','关岭','紫云','黄果树')

class Contract(BaseModel):model_config=ConfigDict(extra='forbid')
BasisType=Literal['historical','seasonal','local_activity']

class RiskCandidate(Contract):
    id:str=Field(pattern=r'^c[1-8]$')
    category:str=Field(min_length=2,max_length=30)
    basis_type:BasisType
    context_factors:list[Literal['season','festival','custom','industry','current_signal']]=Field(min_length=1,max_length=5)
    knowledge_basis:str=Field(min_length=20,max_length=400)
    local_facts_to_verify:list[str]=Field(default_factory=list,max_length=4)
    comparison_reason:str=Field(min_length=20,max_length=300)

class CandidateComparison(Contract):
    candidates:list[RiskCandidate]=Field(min_length=5,max_length=8)

class HistoryCitation(Contract):
    page_ref:str=''
    url:str|None=None
    period:str=Field(pattern=r'^\d{4}-(?:0[1-9]|1[0-2])$')
    quote:str=Field(default='',max_length=180)
    excerpt_index:int|None=Field(default=None,ge=0,le=49)
    location_quote:str=Field(default='',max_length=100)
    basis:Literal['official_frequency','recurrence_case','historical_case','seasonal_advisory','seasonal_context','local_activity']

class HistoryTopic(Contract):
    candidate_id:str=''
    category:str=Field(min_length=2,max_length=30)
    basis_type:BasisType='historical'
    knowledge_basis:str=Field(default='',max_length=400)
    applies_to_months:list[int]=Field(default_factory=list,max_length=12)
    rationale:str=Field(min_length=20,max_length=1600)
    evidence:list[HistoryCitation]=Field(default_factory=list,max_length=4)

class HistoricalResearch(Contract):
    topics:list[HistoryTopic]=Field(default_factory=list,max_length=6)
    gaps:list[str]=Field(default_factory=list,max_length=10)

class OutlookItem(Contract):
    basis_type:BasisType='historical'
    basis_label:str|None=Field(default=None,max_length=80)
    paragraph:str|None=Field(default=None,min_length=180,max_length=600)
    category:str=Field(min_length=2,max_length=30)
    historical_basis:str=Field(min_length=20,max_length=200)
    history_refs:list[str]=Field(min_length=1)
    trigger:str=Field(min_length=12,max_length=120)
    risk_path:str=Field(min_length=25,max_length=160)
    early_signals:list[str]=Field(min_length=1,max_length=5)
    owner:str=Field(min_length=2,max_length=100)
    action:str=Field(min_length=30,max_length=180)
    objective:str=Field(min_length=10,max_length=100)

class RiskChain(Contract):
    trigger:str=Field(min_length=15,max_length=120)
    escalation:str=Field(min_length=20,max_length=160)
    impact:str=Field(min_length=12,max_length=100)
    signal:str=Field(min_length=8,max_length=80)
    owner:str=Field(min_length=2,max_length=40)
    mitigation:str=Field(min_length=25,max_length=160)
    source_refs:list[str]=Field(min_length=1)

class AnalysisPlan(Contract):
    paragraph:str|None=Field(default=None,min_length=300,max_length=2000)
    overview:str=Field(min_length=25,max_length=120)
    chains:list[RiskChain]=Field(min_length=2,max_length=8)

def render_analysis(plan,allowed):
    text=plan.overview.rstrip('。')+'。'
    for label,chain in zip(('一是','二是'),plan.chains):
        if not set(chain.source_refs)<=allowed:raise ValueError('研判风险链缺少本月来源；无效引用：'+','.join(sorted(set(chain.source_refs)-allowed))+'。source_refs须原样复制已提供ref，不得自行构造top10:1或事实ID:top10#序号。可用ref：'+','.join(sorted(allowed)))
        trigger=re.sub(r'^(?:若|如果|一旦)','',chain.trigger.rstrip('。；，'))
        escalation=re.sub(r'^(?:可能|进而)','',chain.escalation.rstrip('。；，'))
        mitigation=chain.mitigation.rstrip('。；，')
        measure=mitigation if mitigation.startswith(('由','建议',chain.owner)) else '由'+chain.owner+mitigation
        text+=f'{label}若{trigger}，可能{escalation}，进而{chain.impact.rstrip("。；，")}；应关注{chain.signal.rstrip("。；，")}，{measure}。'
    if plan.paragraph:text=plan.paragraph
    if re.search(r'峰值日信息量不等于|不等于事件风险高峰|住户名单不公开|公开受损住户名单',text):raise ValueError('正文不要复述内部写作禁令；不能把当事人名单未公开当作治理问题，应定向核验权益、公开脱敏办理进展。')
    if not 300<=len(text)<=500:raise ValueError(f'研判风险链合成后{len(text)}字，应控制300—500字；压缩背景、保留因果与阻断措施。')
    return text,sorted({ref for chain in plan.chains for ref in chain.source_refs})

def forecast_window(report):
    year,month=map(int,report.parameters()['report_month'].split('-'))
    periods=[]
    for offset in (1,2):
        index=year*12+month-1+offset;periods.append(f'{index//12:04}-{index%12+1:02}')
    return {'region':'安顺市','report_month':f'{year:04}-{month:02}', 'periods':periods,
            'label':'—'.join(str(int(x[5:]))+'月' for x in periods),
            'historical_years':sorted({y for p in periods for y in range(int(p[:4])-5,int(p[:4]))}),
            'preferred_lookback_years':3,'maximum_lookback_years':5,
            'as_of':date(year,month,calendar.monthrange(year,month)[1]).isoformat()}

def role(field):
    if field['id']=='monthly_recommendations' or field.get('kind')=='paragraph_list':return 'outlook'
    if field['id']=='b40_analysis_paragraph' or '研判分析' in field.get('display_name',''):return 'analysis'
    return None

def policy_for(field):return ANALYSIS_POLICY_VERSION if role(field)=='analysis' else OUTLOOK_POLICY_VERSION

def asserted_knowledge(text):
    """Exclude explicit denials from claims; retain all positive facts/numbers."""
    clause=r'(?:(?!但|然而|不过|却)[^，。；,;])'
    text=re.sub(r'(?:不作|不代表|并不代表|不等于|不构成|不能(?:据此)?认定|并非|并未|不是|不属于|尚无|无|缺少|缺乏|未见|没有|未有|未据|非|不(?=高发|多发|高频|频发|屡发))'+clause+r'{0,70}(?:高发|多发|高频|频发|屡发|往年|历年|统计|案例|事实)'+clause+r'*','',text)
    text=re.sub(r'(?:尚未|未|没有|无法)(?:核实|核验|掌握|确认|证实)[^，。；,;]{0,80}(?:数据|统计|案例|事实|结构|情况)[^，。；,;]*','',text)
    def unverified(match):
        value=match.group()
        return value if re.search(r'20\d{2}年|\d+[%％]|\d+起|发生过|统计显示',value) else ''
    return re.sub(r'[^，。；,;]{0,60}(?:往年|历年|历史)[^，。；,;]{0,40}(?:尚未核实|未核实|尚未掌握|未掌握)',unverified,text)


def seasonal_knowledge_usable(knowledge):
    claims=asserted_knowledge(knowledge)
    if len(knowledge.strip())<20:return False
    if re.search(r'20\d{2}年|历年|往年|统计显示|发生过|\d+[%％]|\d+起',claims):return False
    # General seasonal mechanisms may mention a peak; a local frequency claim
    # still needs a verified source.
    return not re.search('(?:'+'|'.join(LOCAL_NAMES)+r')[^，。；]{0,24}(?:高发|多发|频发|高频)',claims)


def validate_history(result,store,task_id,window,page_refs=None):
    good=[];errors=[];months={x[5:] for x in window['periods']};limit_year=int(window['report_month'][:4])
    norm=lambda s:re.sub(r'\s+','',s)
    if page_refs is None:
        with store.connect() as conn:page_refs=[row['id'] for row in conn.execute('SELECT id FROM artifacts WHERE task_id=? AND kind=?',(task_id,'historical_page'))]
    pages={ref:store.get_artifact(ref) for ref in page_refs if ref.startswith('historical_page-')}
    for topic in result.topics:
        valid=[]
        for citation in topic.evidence:
            try:
                url=citation.url or (citation.page_ref if citation.page_ref.startswith(('http://','https://')) else None)
                if url:
                    matches=[ref for ref,page in pages.items() if page.get('url')==url]
                    if not matches:raise ValueError('URL没有对应的已阅读网页，需先Fetch原文')
                    if citation.page_ref not in matches:citation.page_ref=max(matches,key=lambda ref:pages[ref].get('retrieved_at',''))
                if not store.artifact_belongs_to_task(citation.page_ref,task_id):raise ValueError('来源不属于当前任务，请复制Fetch的ref或返回已读url')
                page=store.get_artifact(citation.page_ref);content=norm(page.get('content',''))
                from .historical_web import page_read_error
                read_error=page_read_error(page.get('content',''))
                if read_error:raise ValueError(read_error)
                if citation.excerpt_index is not None:
                    excerpts=source_excerpts(page['content'])
                    if citation.excerpt_index>=len(excerpts):raise ValueError('原文片段索引无效')
                    citation.quote=excerpts[citation.excerpt_index]
                if not any(name in citation.location_quote for name in LOCAL_NAMES):citation.location_quote=next((name for name in LOCAL_NAMES if name in content),'')
                citation.url=page['url']
                if len(citation.quote)<12:raise ValueError('缺少可校验的连续原文摘录')
                if not page.get('url') or norm(citation.quote) not in content or norm(citation.location_quote) not in content:raise ValueError('摘录不在已阅读原文中')
                if not any(x in citation.location_quote for x in LOCAL_NAMES):raise ValueError('不是安顺本地证据')
                target=next((p for p in window['periods'] if p[5:]==citation.period[5:]),None)
                if topic.basis_type=='historical':
                    if not target or int(citation.period[:4]) not in range(int(target[:4])-5,int(target[:4])):raise ValueError('历史案例需为近五年相同月份')
                elif not (limit_year-5<=int(citation.period[:4])<=limit_year+1):raise ValueError('季节/活动依据超出近五年及未来窗口')
                published=page.get('published_at') or ''
                local_published=datetime.fromisoformat(published.replace('Z','+00:00')).astimezone(timezone(timedelta(hours=8))).date().isoformat() if published else ''
                if local_published>window['as_of']:raise ValueError('资料晚于报告截止日')
                year,month=map(int,citation.period.split('-'))
                if not (local_published.startswith(citation.period) or re.search(fr'{year}[年./-]0?{month}(?:月|[./-])',content)):raise ValueError('历史年月缺少原文或发布日期依据')
                if citation.basis=='official_frequency':
                    from urllib.parse import urlparse
                    host=urlparse(page['url']).hostname or ''
                    if not (host.endswith('.gov.cn') or host.endswith('.police.gov.cn')):raise ValueError('官方高发依据须来自原始官方来源')
                    if not re.search(r'高发|多发|频发|高频|屡发',asserted_knowledge(citation.quote)):raise ValueError('季节性提示不能冒充高频依据')
                    if not any(name in citation.quote for name in LOCAL_NAMES) and not (host=='anshun.gov.cn' or host.endswith('.anshun.gov.cn')):raise ValueError('省级高发描述须明确涉及安顺，不能只借用网页其他位置的地名')
                valid.append(citation)
            except (KeyError,ValueError) as exc:errors.append(topic.category+':'+str(exc))
        cases=[c for c in valid if c.basis in ('recurrence_case','historical_case')]
        frequent=any(c.basis=='official_frequency' for c in valid)
        recurring=len({c.period[:4] for c in cases})>=2 and len({store.get_artifact(c.page_ref)['url'] for c in cases})>=2
        knowledge_ref=None;downgraded=None
        # An unusable historical citation does not invalidate independent
        # seasonal reasoning. Drop its factual claim, never promote the page.
        if topic.basis_type=='historical' and not (frequent or cases) and seasonal_knowledge_usable(topic.knowledge_basis):
            target_months={int(x[5:]) for x in window['periods']}
            if not topic.applies_to_months or target_months&set(topic.applies_to_months):
                topic=topic.model_copy(update={'basis_type':'seasonal','applies_to_months':topic.applies_to_months or sorted(target_months)})
                downgraded='historical';valid=[]
        if topic.basis_type=='historical':
            qualifies=frequent or bool(cases)
            label='官方高发提示' if frequent else '历史同期跨年复现' if recurring else '历史同期案例参考'
        else:
            months_apply={int(x[5:]) for x in window['periods']}&set(topic.applies_to_months)
            knowledge=topic.knowledge_basis.strip()
            if topic.basis_type=='local_activity':
                qualifies=bool(valid) and bool(months_apply);label='已核实地方活动/习俗/产业背景'
            else:
                qualifies=bool(months_apply) and (bool(valid) or len(knowledge)>=20)
                label='本地季节风险资料' if valid else '季节条件推演（模型知识，非本地高发统计）'
                if (not valid or knowledge) and not seasonal_knowledge_usable(knowledge):
                    qualifies=False;errors.append(topic.category+':模型知识只支持条件性季节推演，具体地方历史事实需取证')
                if qualifies and not valid:
                    knowledge_ref=store.put_artifact(task_id,'risk_knowledge',{'category':topic.category,'knowledge_basis':knowledge,
                        'region':window['region'],'periods':window['periods'],'source_type':'model_knowledge','verified_local_history':False})
        if qualifies:
            good.append({'candidate_id':topic.candidate_id,'category':topic.category,'basis_type':topic.basis_type,'basis_label':label,'downgraded_from':downgraded,
                         'knowledge_basis':topic.knowledge_basis,'knowledge_ref':knowledge_ref,'applies_to_months':topic.applies_to_months,
                         'frequency_supported':frequent,'recurrence_supported':recurring,'rationale':topic.rationale,'evidence':[c.model_dump() for c in valid]})
        else:errors.append(topic.category+':依据或未来窗口适用性不足；历史、季节与地方活动可混合选题')
    if len({t['category'] for t in good})<4:errors.append('不足4类有依据的未来风险；可补充季节条件或已核实地方活动，不要求全是历史高发。')
    return good,errors

class OutlookItemValidationError(ValueError):
    def __init__(self,message,category,allowed_refs=(),code='outlook_item_invalid'):
        self.category=category;self.allowed_refs=sorted(allowed_refs);self.code=code
        super().__init__(message)


def render_outlook_item(item,topics,window):
    topic=next((t for t in topics if t['category']==item.category),None)
    allowed={c['page_ref'] for c in topic['evidence']}|({topic['knowledge_ref']} if topic.get('knowledge_ref') else set()) if topic else set()
    mapping={c.get('url'):c['page_ref'] for c in topic['evidence'] if c.get('url')} if topic else {}
    item.history_refs=[mapping.get(ref,ref) for ref in item.history_refs]
    if topic is None or not set(item.history_refs)<=allowed:
        invalid=sorted(set(item.history_refs)-allowed)
        message='前瞻类别和历史来源未对应：'+item.category+'；无效引用：'+(','.join(invalid) or '无')+'；该类别允许引用：'+(','.join(sorted(allowed)) or '无')
        raise OutlookItemValidationError(message,item.category,allowed,'category_source_mismatch')
    try:
        if item.basis_type!=topic.get('basis_type','historical'):raise ValueError('依据性质未对应选题')
        knowledge_only=bool(topic.get('knowledge_ref')) and not topic['evidence']
        cited=[c for c in topic['evidence'] if c['page_ref'] in item.history_refs]
        claim=item.historical_basis+' '+(item.paragraph or '')
        assertions=asserted_knowledge(claim)
        if item.basis_type=='seasonal' and (not seasonal_knowledge_usable(claim) or re.search(r'曾发生|同比',assertions)):raise ValueError('季节推演不能冒充本地历史高发或具体历史事实')
        frequency_supported=any(c['basis']=='official_frequency' for c in cited)
        cases=[c for c in cited if c['basis'] in ('recurrence_case','historical_case')]
        recurrence_supported=len({c['period'][:4] for c in cases})>=2 and len({c['url'] for c in cases})>=2
        if item.basis_type=='historical' and not frequency_supported and re.search(r'高发|高频|频发',assertions):raise ValueError('单案或复现依据不能声称历史高发')
        if item.basis_type=='historical' and not recurrence_supported and not frequency_supported and re.search(r'历年|跨年复现|连年',assertions):raise ValueError('单个历史案例不能声称跨年复现')
        if re.search(r'属地不明|信息量|峰值预警|数据质量',item.category):raise ValueError('必须选择事件风险，不能用统计或数据质量替代')
        if not set(re.findall(r'20\d{2}',item.historical_basis))<={c['period'][:4] for c in cited}:raise ValueError('历史依据中出现未被所引来源支持的年份，删去被剔除的资料。')
        evidence_text=' '.join(c['quote']+' '+c['period'] for c in cited)
        if knowledge_only:evidence_text+=' '+topic.get('knowledge_basis','')+' '+window['label']
        basis_numbers=item.historical_basis
        for ref in item.history_refs:basis_numbers=basis_numbers.replace(ref,'')
        first,last=window['periods'][0],window['periods'][-1]
        def known_forecast(match):
            year,start,end=match.groups()
            return '' if int(start)==int(first[5:7]) and int(end)==int(last[5:7]) and (year is None or year==first[:4]) else match.group()
        basis_numbers=re.sub(r'(?:(20\d{2})年)?(\d{1,2})月(?:至|到|—|–|-)(\d{1,2})月',known_forecast,basis_numbers)
        for match in re.finditer(r'\d+(?:\.\d+)?',basis_numbers):
            number=match.group()
            # A cited YYYY-MM date supports the equivalent Chinese M月 spelling,
            # without supporting an unrelated count of M events or people.
            if basis_numbers[match.end():].startswith('月') and number.isdigit() and int(number) in {int(c['period'][5:7]) for c in cited}:continue
            if not re.search(r'(?<!\d)'+re.escape(number)+r'(?!\d)',evidence_text):raise ValueError('历史依据包含摘录未支持的数字：'+item.category+'，'+number+'；请删去或补充对应有效来源，不能改成其他虚构数字。')
        if any('→' in s or '->' in s for s in (item.historical_basis,item.trigger,item.risk_path,item.action,item.objective)):raise ValueError('风险链必须写成自然书面句子，不能用箭头或流程图符号。')
        if re.search(r'不发生|零事故|零伤亡|两小时|\d+小时|工资清零',item.objective):raise ValueError('目标不能承诺零事故或无依据硬指标，应写可核验的风险压降方向。')
        clean=lambda s:s.strip().rstrip('。；，;,.').strip()
        trigger=re.sub(r'^(?:若|如果|一旦)','',clean(item.trigger));path=re.sub(r'^可能','',clean(item.risk_path))
        action=clean(item.action)
        advice=action if action.startswith('建议') else '建议'+action if action.startswith(('由',item.owner)) else '建议'+item.owner+action
        text=f'{item.category}方面，{clean(item.historical_basis)}。面向{window["label"]}，若{trigger}，可能{path}，应重点跟踪'+'、'.join(clean(s) for s in item.early_signals)+f'。{advice}，以{clean(item.objective)}。'
        if item.paragraph:text=item.paragraph
        if not set(re.findall(r'20\d{2}',text))<={c['period'][:4] for c in cited}|{p[:4] for p in window['periods']}:raise ValueError('正文出现未被所引来源支持的历史年份。')
        if re.search(r'→|->|零事故|零伤亡|确保不发生|保证不发生',text):raise ValueError('正文须为自然书面语，不得使用流程箭头或保证性零事故表述。')
        if len(text)>600:raise ValueError(f'单条前瞻建议{len(text)}字，超过600字，请压缩事实罗列，保留因果与前置措施。')
        return text,sorted(set(item.history_refs))
    except ValueError as exc:
        if isinstance(exc,OutlookItemValidationError):raise
        raise OutlookItemValidationError(str(exc),item.category,allowed) from exc


def render_outlook(items,topics,window):
    if not 4<=len(items)<=5:raise ValueError('前瞻建议必须4—5类')
    if len({i.category for i in items})!=len(items):raise ValueError('前瞻类别重复')
    values=[];refs=set()
    for item in items:
        text,item_refs=render_outlook_item(item,topics,window)
        values.append(text);refs.update(item_refs)
    return values,sorted(refs)

def source_excerpts(content):
    """Exact source slices, not model paraphrases; stable indices for citations."""
    rows=[];seen=set()
    matches=list(re.finditer(r'高发|多发|频发|高频|屡发|发生.{0,16}(?:事故|火灾)|拖欠|凝冻|结冰|安顺|平坝|西秀|关岭|镇宁|紫云|普定|黄果树',content))
    matches.sort(key=lambda m:(0 if re.search(r'高发|多发|频发|高频|屡发',m.group()) else 1 if re.search(r'发生|拖欠|凝冻|结冰',m.group()) else 2,m.start()))
    for match in matches:
        start=max(0,match.start()-65);end=min(len(content),match.end()+110)
        text=content[start:min(end,start+180)].strip()
        key=re.sub(r'\s+','',text)
        if key in seen:continue
        seen.add(key);rows.append(text)
        if len(rows)>=40:break
    return rows
