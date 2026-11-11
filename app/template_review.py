"""Semantic template review, source validation and compilation of model decisions."""
from .agent import get_prompt,TEMPLATE_POLICY
from copy import deepcopy
import hashlib
import json
import re
from .state import TemplateModelInput, TemplateReviewResult
from .structured_template import apply_top10_rule

POLICY_VERSION = 'anshun-semantic-template-v1'



def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def make_input(documents, comparison, local):
    # Only actual keys supported by the current metrics tool may be bound.
    keys = ['record_count', 'warning_raw_count', 'negative_record_count',
            'warning_record_count', 'negative_or_warning_record_count']
    bindings = [{'tool': 'calculate_metrics', 'path': [key]} for key in keys]
    for sentiment in ('正面', '中性', '负面'):
        bindings.append({'tool': 'calculate_metrics', 'path': ['sentiment', sentiment]})
    bindings.append({'tool': 'top10_events', 'path': []})
    # The model needs the local hypothesis, not two redundant copies of generated
    # value schemas and source paragraphs already supplied in source_reports.
    def hypothesis(candidate):
        return {'blocks': candidate['blocks'],
                'charts':candidate.get('charts',[]),
                'fields': [{key: f.get(key) for key in ('id','owner','kind','semantic','block','binding','sources')}
                           for f in candidate['fields']]}
    local_view=hypothesis(local)
    local_view['other_report_hypotheses']=[hypothesis(c) for c in local.get('other_report_hypotheses',[])]
    comparison_view={'documents': comparison['documents'], 'method': comparison['method'],
                     'alignments': [{key: a[key] for key in ('base_file','other_file','type','base_blocks','other_blocks')}
                                    for a in comparison['alignments']]}
    return TemplateModelInput(
        policy={'version':POLICY_VERSION,**deepcopy(TEMPLATE_POLICY)},
        source_reports=[{'id': f'r{i+1}', **d} for i, d in enumerate(documents)],
        local_comparison=comparison_view, local_hypothesis=local_view,
        available_bindings=bindings, instruction=get_prompt('template_analyst.template')+get_prompt('template_analyst.charts')).model_dump()


def compile_review(model_result, packet, comparison_ref, target_blocks=None):
    result = TemplateReviewResult.model_validate(model_result)
    reports = {d['id']: d for d in packet['source_reports']}
    base = packet['source_reports'][0]
    lookup = {(d['id'], b['index']): b for d in reports.values() for b in d['blocks']}
    def check_source(source, full=False):
        key = (source.report_id, source.block)
        if key not in lookup:
            raise ValueError(f'unknown_source_block:{key}')
        if hasattr(source, 'text') and source.text not in lookup[key]['text']:
            raise ValueError(f'source_text_mismatch:{key}')
        return key
    indexes = [b.index for b in result.blocks]
    base_blocks = [b for b in base['blocks'] if target_blocks is None or b['index'] in target_blocks]
    expected = [b['index'] for b in base_blocks]
    if indexes != expected:
        raise ValueError('template_block_coverage_or_order')
    fields = {f.id: f for f in result.fields}
    if len(fields) != len(result.fields):
        raise ValueError('duplicate_template_field')
    used = []; covered = set(); blocks = []; compiled_fields = []
    for block, original in zip(result.blocks, base_blocks):
        if block.kind != original['kind']:
            raise ValueError('template_block_kind')
        if re.match(r'^从\d+月份网络舆情监测信息来看',original['text']):
            # This is a contextual risk argument, not a numeric summary. Keeping
            # the whole paragraph dynamic avoids historical clauses between chips.
            if len(block.parts)!=1 or not block.parts[0].field:
                raise ValueError(f'whole_risk_paragraph_required:{block.index}:研判分析正文必须仅一个analysis字段，基准source.text覆盖本段全文，owner=writer；不要将月份、平台、类别拆开。')
            risk_field=fields.get(block.parts[0].field)
            if not risk_field or risk_field.kind!='analysis' or risk_field.owner!='writer':
                raise ValueError(f'whole_risk_paragraph_required:{block.index}:字段kind=analysis、owner=writer')
        block_sources = {check_source(s) for s in block.sources}
        if ('r1', block.index) not in block_sources:
            raise ValueError('base_block_source_missing')
        covered |= block_sources
        parts = []; restored = ''
        for part in block.parts:
            if (part.text is None) == (part.field is None):
                raise ValueError('template_part_requires_text_or_field')
            if part.text is not None:
                parts.append({'text': part.text}); restored += part.text
                continue
            if part.field not in fields or part.field in used:
                raise ValueError('unknown_or_repeated_template_field')
            field = fields[part.field]; used.append(field.id)
            source_keys = {check_source(s) for s in field.sources}
            if not source_keys <= block_sources:
                raise ValueError('field_source_outside_block')
            source = [s for s in field.sources if s.report_id == 'r1' and s.block == block.index]
            if len(source) != 1:
                raise ValueError('field_base_source_required_once')
            restored += source[0].text
            if field.binding and (field.owner != 'data' or field.binding.model_dump() not in packet['available_bindings']):
                raise ValueError('unsupported_template_binding')
            if field.source_type == 'statistics' and field.owner != 'data':
                raise ValueError(f'statistics_owned_by_data:{field.id}:source_type=statistics requires owner=data')
            if field.source_type in ('materials', 'analysis') and field.owner != 'writer':
                raise ValueError(f'narrative_owned_by_writer:{field.id}:source_type={field.source_type} requires owner=writer')
            if field.kind == 'table_rows' and field.owner != 'data':
                raise ValueError('table_owned_by_data')
            value = field.model_dump()
            value.update(block=block.index, sources=[{'file': reports[s.report_id]['path'],
                         'sha256': reports[s.report_id]['sha256'], 'block': s.block, 'text': s.text}
                         for s in sorted(field.sources, key=lambda s: s.report_id != 'r1')],
                         value_schema={'type': 'string', 'minLength': 1})
            if field.kind == 'table_rows':
                if block.kind != 'table': raise ValueError('table_field_in_paragraph')
                value['value_schema'] = {'type': 'array', 'items': {'type': 'array', 'items': {'type': 'string'}}}
            parts.append({'field': field.id}); compiled_fields.append(value)
        if restored != original['text']:
            # Restore punctuation/connectors from the original. The model owns
            # semantic field boundaries; it need not retype every Chinese quote
            # or "等" correctly. Never repair a missing substantive word.
            strip=lambda text:re.sub(r'[\s，。、；：“”‘’（）()"\'等]','',text)
            if strip(restored)==strip(original['text']):
                canonical=[];cursor=0
                for part in parts:
                    if 'field' not in part:continue
                    field=fields[part['field']]
                    sample=next(s.text for s in field.sources if s.report_id=='r1' and s.block==block.index)
                    start=original['text'].find(sample,cursor)
                    if start<0:raise ValueError(f'overlapping_field_sources:{block.index}:{field.id}')
                    if start>cursor:canonical.append({'text':original['text'][cursor:start]})
                    canonical.append(part);cursor=start+len(sample)
                if cursor<len(original['text']):canonical.append({'text':original['text'][cursor:]})
                parts=canonical
            else:
                at=next((i for i,(a,b) in enumerate(zip(original['text'],restored)) if a!=b),min(len(original['text']),len(restored)))
                raise ValueError(f'template_source_reconstruction:{block.index}:offset={at}:expected={original["text"][max(0,at-15):at+45]!r}:actual={restored[max(0,at-15):at+45]!r}')
        # A recurring error in the actual samples: model replaces one platform
        # list but leaves a second monthly channel conclusion fixed at the end.
        if block.kind=='paragraph' and re.search(r'从平台上看|网民主要|等平台发表诉求',original['text']):
            fixed=''.join(p.get('text','') for p in parts)
            if re.search(r'网站|移动客户端|微博|微信|短视频|视频号|纸媒|电视',fixed):
                raise ValueError(f'monthly_platform_left_fixed:{block.index}:所有当月平台名称含段尾传播渠道都必须纳入完整动态字段')
        if block.kind == 'table' and (len(parts) != 1 or parts[0].get('field') not in fields or fields[parts[0]['field']].kind != 'table_rows'):
            raise ValueError('table_requires_one_rows_field')
        blocks.append({'index': block.index, 'kind': block.kind, 'parts': parts, 'purpose': block.purpose,
                       'sources': [s.model_dump() for s in block.sources],
                       **({'headers': original['rows'][0]} if block.kind == 'table' else {})})
    if set(used) != set(fields): raise ValueError('unused_template_fields')
    for question in result.unresolved_items:
        covered |= {check_source(s) for s in question.sources}
    if target_blocks is None and covered != set(lookup):
        raise ValueError('historical_report_blocks_not_covered:'+str(sorted(set(lookup)-covered)))
    candidate = {'format_version': 2, 'status': 'candidate_requires_review', 'comparison_ref': comparison_ref,
                 'source_reports': [{'path': d['path'], 'sha256': d['sha256']} for d in reports.values()],
                 'layout_source': base['path'], 'blocks': blocks, 'fields': compiled_fields,
                 'review_items': [q.model_dump() for q in result.unresolved_items],
                 'review_summary': result.summary, 'policy_version': POLICY_VERSION,
                 'model_review_validated': True}
    from .chart_spec import definitions
    candidate['charts']=definitions(candidate)
    if target_blocks is None:
        candidate = normalize_recommendations(candidate,packet['source_reports'])
    candidate = apply_top10_rule(candidate)
    candidate['id'] = 'structured-' + digest(candidate)[:20]
    return candidate


def normalize_recommendations(candidate,reports):
    """Compile numbered advice paragraphs into one variable-length writer field."""
    def numbered(document):
        active=False;result=[]
        for block in document['blocks']:
            if '工作建议' in block['text'] and len(block['text'])<30:active=True;continue
            if active and block['kind']=='paragraph' and re.match(r'^\s*\d+[.、．]',block['text']):result.append(block)
        return result
    source_groups=[numbered(d) for d in reports]
    originals=source_groups[0]
    if not originals:return candidate
    indexes={b['index'] for b in originals}
    replaced_ids={p['field'] for b in candidate['blocks'] if b['index'] in indexes for p in b['parts'] if 'field' in p}
    source_keys={(d['id'],b['index']) for d,blocks in zip(reports,source_groups) for b in blocks}
    sources=[{'file':d['path'],'sha256':d['sha256'],'block':b['index'],'text':b['text']} for d,blocks in zip(reports,source_groups) for b in blocks]
    field={'id':'monthly_recommendations','display_name':'前瞻风险与工作建议（4—5类）','owner':'writer','kind':'paragraph_list',
           'source_type':'analysis','semantic':'根据本月风险研判生成完整的工作建议列表，不固定历史条数和历史主题',
           'rule':'比较5—8类未来风险候选，研究目标5类合格选题，至少4类方可进入写作；按本地历史、官方季节资料或已核实地方活动、明确模型季节机制分级补足依据，输出4至5类未来1至2个月风险。每类写选题依据、触发条件、演变后果、早期信号、前置措施及目标，不能逐条改写本月TOP10，不得编造地方事实或引用。列表不含编号，由程序编号。',
           'format':'字符串数组，一项对应一个建议段落','missing_policy':'block','reason':'历史报告建议条数不一；使用4至5条可变列表避免固定历史条数。',
           'binding':None,'block':originals[0]['index'],'sources':sources,
           'value_schema':{'type':'array','minItems':4,'maxItems':5,'items':{'type':'string','minLength':1}}}
    candidate['fields']=[f for f in candidate['fields'] if f['id'] not in replaced_ids]+[field]
    remaining=[]
    for block in candidate['blocks']:
        if block['index']==originals[0]['index']:
            remaining.append({'index':block['index'],'kind':'repeat','parts':[{'field':field['id']}],
                              'source_block_indexes':[b['index'] for b in originals],
                              'purpose':field['semantic'],'sources':[{'report_id':rid,'block':index} for rid,index in sorted(source_keys)]})
        elif block['index'] not in indexes:remaining.append(block)
    candidate['blocks']=remaining
    # Model findings about the number of advice paragraphs are resolved by the
    # Outlook size is a current business rule, not the historical advice count.
    unresolved=[];resolved=[]
    for question in candidate['review_items']:
        refs={(s['report_id'],s['block']) for s in question['sources']}
        if refs and refs<=source_keys and re.search(r'条数|三条|第四条|集合|子块|固定.*条|条目|序号|编号',question['question']):
            resolved.append({'rule':'工作建议为4—5类前瞻风险的可变列表，程序按顺序自动编号','sources':question['sources']})
        else:unresolved.append(question)
    candidate['review_items']=unresolved
    candidate['resolved_by_policy']=resolved
    return candidate
