"""Collect independent issues together before asking the model to repair."""
import json
import re
from pydantic import ValidationError
from .state import TemplateReviewResult
from .template_review import compile_review


def collect_errors(raw,packet,comparison_ref,targets=None):
    errors=[]
    def add(code,message,field=None,block=None,expected=None,actual=None,sources=None):
        item={'code':code,'message':message,'field_id':field,'block':block,
              'expected':expected,'actual':actual,'sources':sources or []}
        if item not in errors:errors.append(item)
    try:result=TemplateReviewResult.model_validate(raw)
    except ValidationError as exc:
        for issue in exc.errors(include_input=False,include_url=False):
            add('schema_validation','输出结构不完整或属性类型错误：'+issue['msg'],actual=list(issue['loc']))
        return errors
    reports=packet['source_reports'];lookup={(d['id'],b['index']):b for d in reports for b in d['blocks']}
    base={b['index']:b for b in reports[0]['blocks']}
    expected=list(base) if targets is None else list(targets)
    actual=[b.index for b in result.blocks]
    if actual!=expected:
        add('template_block_coverage_or_order','本批返回的段落范围或顺序不正确。只返回指定段落，不能输出整篇模板。',expected=expected,actual=actual)
    fields={f.id:f for f in result.fields}
    if len(fields)!=len(result.fields):add('duplicate_template_field','字段编号重复。')
    referenced=[];covered=set();bad_fields=set()
    for f in result.fields:
        sources=[s.model_dump() for s in f.sources];label='字段「'+f.display_name+'」'
        if f.source_type in ('statistics','task_metadata') and f.owner!='data':
            add('statistics_owned_by_data',label+'被标记为统计结果或任务信息，应交给数据工具，当前却交给Writer。',f.id,
                expected='data',actual=f.owner,sources=sources);bad_fields.add(f.id)
        if f.source_type in ('materials','analysis') and f.owner!='writer':
            add('narrative_owned_by_writer',label+'是材料文字或分析段，应由Writer根据本期证据填写。',f.id,
                expected='writer',actual=f.owner,sources=sources);bad_fields.add(f.id)
        if f.binding and (f.owner!='data' or f.binding.model_dump() not in packet['available_bindings']):
            add('unsupported_template_binding',label+'的数据绑定不在可用目录中；不明确的绑定应留空。',f.id,
                actual=f.binding.model_dump(),sources=sources);bad_fields.add(f.id)
        if f.kind=='table_rows' and f.owner!='data':
            add('table_owned_by_data',label+'是数据表格，应由数据工具负责。',f.id,expected='data',actual=f.owner);bad_fields.add(f.id)
        if f.kind=='list' and re.search(r'固定参照|固定类别|始终包含|必须保留.*类别',f.rule):
            add('historical_category_fixed_in_rule',label+'的规则将历史类别固定为必含项；类别必须随当月结果变化。',f.id,actual=f.rule,sources=sources);bad_fields.add(f.id)
        for source in f.sources:
            key=(source.report_id,source.block)
            if key not in lookup:
                add('unknown_source_block',label+'引用了不存在的报告段落。',f.id,source.block,actual=source.model_dump());bad_fields.add(f.id)
            elif source.text not in lookup[key]['text']:
                add('source_text_mismatch',label+'的来源片段与指定原文不一致。',f.id,source.block,
                    expected=lookup[key]['text'],actual=source.text,sources=[source.model_dump()]);bad_fields.add(f.id)
    for block in result.blocks:
        for source in block.sources:
            key=(source.report_id,source.block)
            if key in lookup:covered.add(key)
            else:add('unknown_source_block','段落对应关系引用了不存在的来源。',block=block.index,actual=source.model_dump())
        if block.index not in base or block.index not in expected:continue
        original=base[block.index];block_errors=[];restored='';ids=[]
        if block.kind!=original['kind']:add('template_block_kind','段落与原文的类型不一致。',block=block.index,expected=original['kind'],actual=block.kind)
        if ('r1',block.index) not in {(s.report_id,s.block) for s in block.sources}:
            add('base_block_source_missing','缺少基准报告的段落来源。',block=block.index)
        for part in block.parts:
            if (part.text is None)==(part.field is None):
                add('template_part_requires_text_or_field','正文片段必须是固定文字或动态字段中的一种。',block=block.index);continue
            if part.text is not None:restored+=part.text;continue
            referenced.append(part.field);ids.append(part.field)
            if part.field not in fields:
                add('unknown_template_field','正文引用了未定义的字段。',part.field,block.index);continue
            f=fields[part.field]
            sample=[s for s in f.sources if s.report_id=='r1' and s.block==block.index]
            if len(sample)!=1:
                add('field_base_source_required_once','每个字段必须有且只有一个本段基准原文片段。',f.id,block.index)
            else:restored+=sample[0].text
            allowed={(s.report_id,s.block) for s in block.sources}
            if not {(s.report_id,s.block) for s in f.sources}<=allowed:
                add('field_source_outside_block','字段来源超出了其所属段落的对应关系。',f.id,block.index)
        strip=lambda text:re.sub(r'[\s，。、；：“”‘’（）()"\'等]','',text)
        if strip(restored)!=strip(original['text']):
            at=next((i for i,(a,b) in enumerate(zip(original['text'],restored)) if a!=b),min(len(restored),len(original['text'])))
            add('template_source_reconstruction','用字段来源还原正文时，与基准原文不一致。',block=block.index,
                expected=original['text'][max(0,at-20):at+80],actual=restored[max(0,at-20):at+80])
        if re.search(r'从平台上看|网民主要|等平台发表诉求',original['text']):
            fixed=''.join(p.text or '' for p in block.parts)
            if re.search(r'网站|移动客户端|微博|微信|短视频|视频号|纸媒|电视',fixed):
                add('monthly_platform_left_fixed','本月平台名称仍被留作固定文字；所有出现位置均须按完整列表动态填写。',block=block.index,actual=fixed)
        if re.match(r'^从\d+月份网络舆情监测信息来看',original['text']):
            if len(block.parts)!=1 or not block.parts[0].field or fields.get(block.parts[0].field) is None or fields[block.parts[0].field].kind!='analysis':
                add('whole_risk_paragraph_required','研判分析正文须使用一个覆盖全文的analysis字段，由Writer填写。',block=block.index)
        # The compiler covers remaining structural invariants. Only skip it when
        # a field already has an error, to avoid reporting the first issue twice.
        if not set(ids)&bad_fields:
            partial={'summary':result.summary,'blocks':[block.model_dump()],
                     'fields':[fields[key].model_dump() for key in dict.fromkeys(ids) if key in fields],
                     'unresolved_items':[]}
            try:compile_review(partial,packet,comparison_ref,[block.index])
            except (ValueError,KeyError) as exc:
                code=str(exc).split(':')[0]
                if not any(e['code']==code and e['block']==block.index for e in errors):
                    add(code,'该段结构还未符合模板规范：'+str(exc),block=block.index)
    if len(referenced)!=len(set(referenced)):add('repeated_template_field','同一个字段被用于多个位置。')
    if set(fields)-set(referenced):add('unused_template_fields','存在未被正文使用的字段。',actual=sorted(set(fields)-set(referenced)))
    for q in result.unresolved_items:
        for s in q.sources:
            if (s.report_id,s.block) not in lookup:add('unknown_source_block','待定问题引用了不存在的来源。',actual=s.model_dump())
            else:covered.add((s.report_id,s.block))
    if targets is None and covered!=set(lookup):
        add('historical_report_blocks_not_covered','有历史报告段落未参与模板研判。',actual=sorted(set(lookup)-covered))
    if not errors:
        try:compile_review(raw,packet,comparison_ref,targets)
        except (ValueError,KeyError) as exc:add(str(exc).split(':')[0],'模板整体校验未通过：'+str(exc))
    return errors


def batch_schema(targets):
    schema=TemplateReviewResult.model_json_schema()
    schema['properties']['blocks'].update(minItems=len(targets),maxItems=len(targets))
    schema['$defs']['TemplateBlock']['properties']['index']={'type':'integer','enum':targets}
    return schema
