"""Local report metadata suggestions; never asks a model to invent metadata."""
import logging,re
from datetime import datetime,timezone,timedelta,date
from pathlib import Path
from .template_compare import parse_report_document

LOG=logging.getLogger(__name__)

def _source_blocks(source):
    """源报告的 blocks；读不了就留一条带文件名与异常类型的警告，绝不静默吞掉。"""
    try:
        return parse_report_document(source['path'])['blocks']
    except (KeyError,ValueError,OSError) as exc:
        # UnreadableDocument 是 ValueError 子类：`.doc` 走 `read_docx` 时正落在这里被吞掉，
        # 于是期号推断无声少一份证据。派发点认格式后这条只该在真坏文件上出现。
        LOG.warning('report_parameters: 源报告读取失败，已跳过 %s (%s: %s)',
                    Path(source.get('path') or '').name,type(exc).__name__,exc)
        return []

def suggestions(template,report_month):
    target=date.fromisoformat(report_month+'-01')
    samples=[]
    for source in template.get('source_reports',[]):
        text='\n'.join(b.get('text','') for b in _source_blocks(source)[:12])
        issue=re.search(r'(20\d{2})\s*年\s*第\s*(\d+)\s*期',text)
        month=re.search(r'(20\d{2})\s*年\s*(\d{1,2})\s*月\s*网络舆情分析报告',text)
        if issue and month and issue[1]==month[1]:
            samples.append({'year':int(month[1]),'month':int(month[2]),'issue_number':int(issue[2])})
    same=sorted({(x['month'],x['issue_number']) for x in samples if x['year']==target.year})
    exact=[issue for month,issue in same if month==target.month]
    issue=exact[0] if len(set(exact))==1 else None
    reason='未找到可用的连续期号规则，请填写本期实际期号。'
    if issue is not None:reason='从模板来源中同年同月份报告识别，仍可修改。'
    elif len(same)>=2 and len({number-month for month,number in same})==1:
        proposed=target.month+same[0][1]-same[0][0]
        if proposed>0:issue=proposed;reason='按同年多份历史报告的每月递增规律推算，请核对；不会跨年沿用旧期号。'
    today=datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    return {'issue_number':issue,'publication_date':today,'issue_reason':reason,
            'publication_reason':'成文日期默认今天，可在开始处理前修改；月份和日期日由所选日期自动拆分。',
            'samples':samples,'report_month':report_month}

def save_before_writing(store,state,parameters,expected_revision):
    if state.kind!='report' or state.phase not in ('awaiting_review','facts_frozen','failed','analysis_pending'):
        raise ValueError('report_parameters_not_editable')
    if state.revision!=expected_revision:raise ValueError('stale_task_revision')
    if parameters.get('publication_date'):date.fromisoformat(parameters['publication_date'])
    state.metadata.setdefault('report_parameters',{}).update(parameters)
    state.metadata['report_parameters_ref']=store.put_artifact(state.id,'report_parameters',{
        'fact_ref':state.fact_ref,'parameters':state.metadata['report_parameters'],'source':'human_provided'})
    store.put_task(state,state.revision)
    store.append_event(state.id,{'type':'report_parameters_saved','stage':state.phase,'model_called':False})
    return state
