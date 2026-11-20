"""Template-specific writing relationships. Client facts live in package sidecars."""
from __future__ import annotations
import copy
import hashlib
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class WritingGroup(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(min_length=1)
    label:str=Field(min_length=1)
    members:dict[str,str]=Field(min_length=2)
    instruction:str=Field(min_length=1)
    query:dict=Field(default_factory=lambda:{'focus':'all','limit':10})
    example_bindings:dict[str,str]=Field(default_factory=dict)
    event_list_fields:list[str]=Field(default_factory=list)
    allow_external_research:bool=False
    context_scope:Literal['all_records','confirmed_events','warning_events','negative_warning_events']|None=None
    count_unit:Literal['events','records']='events'
    include_statistics:bool=True

class WritingContract(BaseModel):
    model_config=ConfigDict(extra='forbid')
    groups:list[WritingGroup]=Field(default_factory=list)
    calculations:dict[str,dict]=Field(default_factory=dict)
    feature_overrides:dict[str,bool]=Field(default_factory=dict)
    note:str=''

def validate_contract(raw,fields):
    contract=WritingContract.model_validate(raw).model_dump()
    seen=set();names=set()
    from .frozen_report import Calculation,MaterialQuery
    for group in contract['groups']:
        if group['id'] in names:raise ValueError('duplicate_writing_group')
        names.add(group['id'])
        if not set(group['members'])<=fields.keys():raise ValueError('writing_group_field_missing')
        if seen&group['members'].keys():raise ValueError('overlapping_writing_groups')
        seen.update(group['members'])
        if not any(fields[key]['owner']=='writer' for key in group['members']):raise ValueError('writing_group_requires_writer')
        MaterialQuery.model_validate(group['query'])
        for writer,data in group['example_bindings'].items():
            if writer not in group['members'] or data not in group['members'] or fields[writer]['owner']!='writer' or fields[data]['owner']!='data':
                raise ValueError('invalid_group_example_binding')
        if not set(group['event_list_fields'])<=group['members'].keys():raise ValueError('event_list_field_not_in_group')
    for key,spec in contract['calculations'].items():
        if key not in fields or fields[key]['owner']!='data':raise ValueError('writing_calculation_field_missing')
        Calculation.model_validate(spec)
    if set(contract['feature_overrides'])-{'dedup'}:raise ValueError('unsupported_writing_feature_override')
    return contract

def resolve(template,package=None,template_ref=None):
    fields={f['id']:f for f in template.get('fields',[])}
    for group in (template.get('rules') or {}).get('optional_field_groups',[]):
        if not isinstance(group,list) or len(group)<2 or len(group)!=len(set(group)) or any(k not in fields or not fields[k].get('optional') for k in group):raise ValueError('invalid_optional_field_group')
    raw={'groups':(template.get('rules') or {}).get('writing_groups',[])}
    if package:
        from .packages.registry import load
        import yaml
        path=load(package).directory/'writing_contracts.yaml'
        if path.exists():
            doc=yaml.safe_load(path.read_text(encoding='utf-8-sig')) or {}
            if doc.get('schema_version')!=1:raise ValueError('invalid_writing_contract_version')
            matches=[p for p in doc.get('profiles',[]) if template_ref and template_ref in p.get('template_refs',[])]
            if len(matches)>1:raise ValueError('ambiguous_writing_contract')
            if matches:raw.update(matches[0]['contract'])
    result=validate_contract(raw,fields)
    result['sha256']=hashlib.sha256(json.dumps(result,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return result

def expand_fields(ids,contract,fields):
    result=list(ids)
    for group in contract.get('groups',[]):
        if set(result)&group['members'].keys():
            result=list(dict.fromkeys([*(k for k in group['members'] if fields[k]['owner']=='writer'),*result]))
    return result

def group_context(ids,contract,values):
    def visible(value):
        if 'human_edit' in value.get('source_refs',[]):
            return {'value':'[已人工确认字段，保持原样]','source_refs':[],'human_confirmed':True}
        return copy.deepcopy(value)
    return [{**copy.deepcopy(group),'existing_values':{key:visible(values[key]) for key in group['members'] if key in values}}
            for group in contract.get('groups',[]) if set(ids)&group['members'].keys()]

def validate_group_answers(contexts,answers):
    import re
    for group in contexts:
        for key in group.get('event_list_fields',[]):
            if key not in answers:continue
            titles=[s.strip('“” "') for s in str(answers[key]['value']).split('”“') if s.strip('“” "')]
            mapping=group.get('allowed_event_titles',{})
            if not titles or any(t not in mapping for t in titles):raise ValueError('事件举例必须逐字使用本组不同事件的候选标题：'+key)
            ids=[mapping[t] for t in titles]
            if len(ids)!=len(set(ids)):raise ValueError('同一事件不能重复举例：'+key)
        for key,names in group.get('allowed_examples',{}).items():
            if key not in answers:continue
            selected=[s.strip() for s in re.split('[、，,]',str(answers[key]['value'])) if s.strip()]
            if not selected or not set(selected)<=set(names):raise ValueError('媒体示例必须来自同口径规范机构列表：'+key)

def repair_allowed(field_id,issues,contract,field,source_refs):
    return bool(field.get('owner')=='writer' and source_refs and
                any(i.get('kind') in ('logic','fact') for i in issues) and
                any(field_id in g['members'] for g in contract.get('groups',[])))

def writing_blocks(template,contract):
    """Schedule each related writing unit once, retaining all original fixed text."""
    fields={f['id']:f for f in template['fields']};emitted=set();result=[]
    for block in template['blocks']:
        ids=[p['field'] for p in block['parts'] if p.get('field') in fields]
        related=[g for g in contract.get('groups',[]) if set(ids)&g['members'].keys()]
        for group in related:
            if group['id'] in emitted:continue
            members=set(group['members']);parts=[]
            for original in template['blocks']:
                if any(p.get('field') in members for p in original['parts']):
                    # Only group members are editable; other placeholders stay in layout context.
                    parts.extend(copy.deepcopy(p) for p in original['parts'] if not p.get('field') or p['field'] in members)
                    parts.append({'text':'\n'})
            result.append({**block,'parts':parts,'writing_group':group['id']});emitted.add(group['id'])
        grouped={key for group in related for key in group['members']}
        if any(key not in grouped and fields[key]['owner']=='writer' for key in ids):
            result.append({**block,'parts':[copy.deepcopy(p) for p in block['parts'] if p.get('field') not in grouped]})
    return result
