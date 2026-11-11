"""Deterministic checks that run before model reviews or human final approval."""
from __future__ import annotations
from .schemas import DraftVersion,ReviewIssue

def validate_draft(draft:DraftVersion,facts:dict,template:dict|None=None)->list[ReviewIssue]:
    issues=[]
    if draft.fact_ref!=facts.get('artifact_ref',draft.fact_ref):
        issues.append(ReviewIssue(field_id='fact_ref',severity='blocking',description='稿件事实引用与当前事实版本不一致'))
    allowed=set(facts.get('input_refs',[]))|set(facts.get('result_refs',{}).values())
    for ref in draft.source_refs:
        if ref not in allowed:
            issues.append(ReviewIssue(field_id='source_refs',severity='blocking',description=f'不存在于当前事实版本的来源引用：{ref}'))
    for i,section in enumerate(draft.sections):
        text=str(section.get('text',''))
        if not text.strip(): issues.append(ReviewIssue(field_id=f'sections.{i}',severity='blocking',description='正文为空'))
        if '{{' in text or '}}' in text: issues.append(ReviewIssue(field_id=f'sections.{i}',severity='blocking',description='正文仍含未填占位符'))
        if not section.get('locked') and text.strip() and not section.get('source_refs'):
            issues.append(ReviewIssue(field_id=f'sections.{i}',severity='blocking',description='可生成正文缺少来源引用'))
    if not draft.recommendations:
        description=('研究依据不足，自动流程未能形成有依据的工作建议，保持零条并转人工补全。' if draft.missing_recommendation_evidence
                     else '建议写作/校验未完成，保持零条并转人工补全。')
        issues.append(ReviewIssue(field_id='recommendations',severity='warning',description=description))
    return issues

def apply_writer_patch(draft:DraftVersion,changes:dict[int,str],allowed_fields:set[int])->DraftVersion:
    updated=draft.model_copy(deep=True)
    for index,text in changes.items():
        if index not in allowed_fields or index<0 or index>=len(updated.sections): raise ValueError('field_not_authorized')
        if updated.sections[index].get('locked'): raise ValueError('locked_field')
        updated.sections[index]['text']=text
    updated.content_hash=''
    return updated
