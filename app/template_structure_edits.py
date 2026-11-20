"""Explicit manual candidate edits, anchored to existing historical source paragraphs."""
import copy
import re
from jsonschema import Draft202012Validator
from .structured_template import _schema
from pydantic import BaseModel, ConfigDict, Field

class NewStructureField(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str
    display_name:str=Field(min_length=1,max_length=100)
    semantic:str=Field(min_length=1,max_length=3000)
    rule:str=Field(min_length=1,max_length=5000)

class SourceParagraph(BaseModel):
    model_config=ConfigDict(extra='forbid')
    prefix:str=''
    text:str|None=None
    field:NewStructureField|None=None
    optional:bool=False

class SourceInsertion(BaseModel):
    model_config=ConfigDict(extra='forbid')
    after_index:int
    style_from_index:int
    source_report:int=Field(ge=0)
    source_blocks:list[int]=Field(min_length=1,max_length=20)
    paragraphs:list[SourceParagraph]=Field(min_length=1,max_length=20)

class StructureEdits(BaseModel):
    model_config=ConfigDict(extra='forbid')
    reason:str=Field(min_length=1,max_length=4000)
    field_updates:dict[str,dict]=Field(default_factory=dict)
    insertions:list[SourceInsertion]=Field(default_factory=list,max_length=20)
    block_updates:list[dict]=Field(default_factory=list,max_length=100)
    binding_updates:dict[str,dict]=Field(default_factory=dict)
    chart_updates:dict[str,dict]=Field(default_factory=dict)

def apply_structure_edits(template,edits,documents):
    edits=StructureEdits.model_validate(edits).model_dump(exclude_none=True)
    if not str(edits.get('reason','')).strip():raise ValueError('structure_edit_reason_required')
    if set(edits)-{'reason','field_updates','insertions','block_updates','binding_updates','chart_updates'}:raise ValueError('unsupported_structure_edit')
    result=copy.deepcopy(template)
    fields={f['id']:f for f in result['fields']}
    for key,patch in edits.get('field_updates',{}).items():
        if key not in fields or fields[key]['owner']!='writer' or fields[key].get('binding'):raise ValueError('structure_field_not_editable')
        if set(patch)-{'display_name','semantic','rule','value_schema','missing_policy','category_coverage_scope','count_unit','optional'}:raise ValueError('unsupported_structure_field_edit')
        if 'count_unit' in patch and patch['count_unit'] not in ('records','events'):raise ValueError('invalid_category_count_unit')
        if 'category_coverage_scope' in patch and (patch['category_coverage_scope'] not in ('confirmed_events','warning_events','negative_warning_events') or fields[key]['value_schema'].get('type')!='array'):
            raise ValueError('invalid_category_coverage_scope')
        if 'value_schema' in patch:
            Draft202012Validator.check_schema(patch['value_schema'])
            if patch['value_schema'].get('type')!=fields[key]['value_schema'].get('type'):raise ValueError('structure_field_type_change')
        fields[key].update(copy.deepcopy(patch))
    from core.frozen_report import Calculation
    for key,patch in edits['binding_updates'].items():
        if key not in fields or fields[key]['owner']!='data':raise ValueError('binding_requires_data_field')
        if set(patch)!={'expected_binding','binding'} or patch['expected_binding']!=fields[key].get('binding'):raise ValueError('stale_structure_binding')
        fields[key]['binding']=Calculation.model_validate(patch['binding']).model_dump(exclude_unset=True)
    blocks={b['index']:b for b in result['blocks']}
    for patch in edits['block_updates']:
        if set(patch)-{'index','expected_parts','parts','optional'}:raise ValueError('unsupported_structure_block_edit')
        block=blocks.get(patch.get('index'))
        if not block or patch.get('expected_parts')!=block['parts']:raise ValueError('stale_structure_parts')
        parts=patch.get('parts',block['parts'])
        if not parts or any(not isinstance(p,dict) or set(p) not in ({'text'},{'field'}) or not isinstance(next(iter(p.values())),str) for p in parts):raise ValueError('invalid_structure_parts')
        if [p['field'] for p in parts if 'field' in p]!=[p['field'] for p in block['parts'] if 'field' in p]:raise ValueError('structure_field_order_change')
        if block['kind']!='paragraph':raise ValueError('structure_paragraph_required')
        block.update(parts=copy.deepcopy(parts),render_rebuild=True)
        if 'optional' in patch:
            if type(patch['optional']) is not bool:raise ValueError('invalid_optional_flag')
            block['optional']=patch['optional']
    charts={c['id']:c for c in result.get('charts',[])}
    for key,patch in edits['chart_updates'].items():
        if key not in charts or set(patch)-{'scope','count_unit','unit'}:raise ValueError('unsupported_structure_chart_edit')
        if patch.get('scope','all_records') not in ('all_records','confirmed_events','warning_events','negative_warning_events') or patch.get('count_unit','events') not in ('records','events'):raise ValueError('invalid_chart_scope')
        charts[key].update(copy.deepcopy(patch))
    next_index=max([b['index'] for b in result['blocks']]+[999])+1
    for insertion in edits.get('insertions',[]):
        if set(insertion)-{'after_index','style_from_index','source_report','source_blocks','paragraphs'}:raise ValueError('unsupported_structure_insertion')
        report_index=insertion['source_report']
        if not isinstance(report_index,int) or not 0<=report_index<len(template['source_reports']) or report_index>=len(documents):raise ValueError('structure_source_report_missing')
        sources={b['index']:b for b in documents[report_index]['blocks']}
        if len(insertion['source_blocks'])!=len(insertion['paragraphs']):raise ValueError('structure_source_count_mismatch')
        after=insertion['after_index'];style=insertion['style_from_index']
        if style not in {b['index'] for b in template['blocks'] if b['kind']=='paragraph'}:
            # A repeat's first source paragraph is also a legitimate style exemplar.
            if style not in {b['index'] for b in template['blocks'] if b['kind']=='repeat'}:raise ValueError('structure_style_missing')
        for source_index,paragraph in zip(insertion['source_blocks'],insertion['paragraphs']):
            source=sources.get(source_index)
            if not source or source.get('kind','paragraph')!='paragraph':raise ValueError('structure_source_paragraph_missing')
            if set(paragraph)-{'prefix','text','field','optional'}:raise ValueError('unsupported_structure_paragraph')
            block={'index':next_index,'kind':'paragraph','insert_after_index':after,'style_from_index':style,'parts':[],
                   'optional':bool(paragraph.get('optional')),'manual_source':{'report':report_index,'block':source_index}}
            if 'field' in paragraph:
                spec=paragraph['field']
                if set(spec)!={'id','display_name','semantic','rule'} or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',spec['id']):raise ValueError('invalid_structure_field')
                if spec['id'] in fields:raise ValueError('duplicate_structure_field')
                prefix=paragraph.get('prefix','')
                if not source['text'].startswith(prefix) or len(prefix)>=len(source['text']):raise ValueError('structure_source_prefix_mismatch')
                ref=template['source_reports'][report_index]
                field={**spec,'owner':'writer','kind':'text','binding':None,'block':next_index,'optional':block['optional'],
                       'missing_policy':'omit' if block['optional'] else 'block',
                       'value_schema':{'type':'string','minLength':0 if block['optional'] else 1},
                       'sources':[{'file':ref['path'],'sha256':ref['sha256'],'block':source_index,'text':source['text'][len(prefix):]}]}
                result['fields'].append(field);fields[field['id']]=field
                if prefix:block['parts'].append({'text':prefix})
                block['parts'].append({'field':field['id']})
            else:
                if paragraph.get('text')!=source['text']:raise ValueError('structure_fixed_text_source_mismatch')
                block['parts']=[{'text':source['text']}]
            positions=[i for i,b in enumerate(result['blocks']) if b['index']==after]
            if len(positions)!=1:raise ValueError('structure_anchor_missing')
            result['blocks'].insert(positions[0]+1,block)
            after=next_index;next_index+=1
    result['output_schema']=_schema(result['fields']);result['writer_schema']=_schema(result['fields'],True)
    result.setdefault('manual_structural_edits',[]).append(copy.deepcopy(edits))
    return result
