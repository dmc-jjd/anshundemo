"""Versioned report templates derived from at least two readable source reports."""
from __future__ import annotations
import copy,hashlib,io,json,re,zipfile
from difflib import SequenceMatcher
from .tools.template_compare import shared_paragraph_frames
from pathlib import Path
from jsonschema import Draft202012Validator

NUMBER=re.compile(r'\d+(?:\.\d+)?%?')
def top10_table_schema():
    return {'type':'array','maxItems':10,'items':{'type':'array','minItems':3,'maxItems':3,'items':False,
        'prefixItems':[{'type':'string'},{'type':'string','minLength':15,'maxLength':35},{'type':'string'}]}}
def _tokens(text):
    return re.findall(r'\d+(?:\.\d+)?%?|[^\d]',text)

def _pair_blocks(base_blocks,other_blocks):
    def normalized(b):return b.get('kind','paragraph')+':'+NUMBER.sub('#',b['text'])
    alignment=SequenceMatcher(None,[normalized(b) for b in base_blocks],
                             [normalized(b) for b in other_blocks],autojunk=False)
    pairs={}
    for tag,a0,a1,b0,b1 in alignment.get_opcodes():
        if a1-a0==b1-b0 and tag in ('equal','replace'):
            for a,b in zip(base_blocks[a0:a1],other_blocks[b0:b1]):
                if a.get('kind')==b.get('kind') and SequenceMatcher(None,normalized(a),normalized(b),autojunk=False).ratio()>=.3:
                    pairs[a['index']]=b
    return pairs

def _token_parts(base_text,other_text,base_doc,other_doc,a,b,fields,source):
    parts=[]
    tokens_a,tokens_b=_tokens(base_text),_tokens(other_text)
    for tag,a0,a1,b0,b1 in SequenceMatcher(None,tokens_a,tokens_b,autojunk=False).get_opcodes():
        left=''.join(tokens_a[a0:a1]);right=''.join(tokens_b[b0:b1])
        if tag=='equal':
            if left:parts.append({'text':left})
            continue
        fid=f'block_{a["index"]}_field_{len(fields)+1}'
        numeric=bool(NUMBER.fullmatch(left.strip() or right.strip()))
        fields.append({'id':fid,'owner':'data' if numeric else 'writer','kind':'number' if numeric else 'text',
                       'semantic':'根据两份原文差异提出，含义与来源规则待确认',
                       'value_schema':{'type':'string','minLength':1,**({'pattern':r'^\d+(?:\.\d+)?%?$'} if numeric else {})},
                       'block':a['index'],'binding':None,
                       'sources':[source(base_doc,a,left),source(other_doc,b,right)]})
        parts.append({'field':fid})
    return parts

def _locate_frame_spans(text,frames):
    pos=0
    spans=[]
    for item in frames:
        index=text.find(item['text'],pos)
        if index<0:return None
        spans.append((index,index+len(item['text'])))
        pos=index+len(item['text'])
    return spans

def _append_span_field(fields,a,base_doc,other_doc,b,left,right,source):
    fid=f'block_{a["index"]}_field_{len(fields)+1}'
    numeric=bool(NUMBER.fullmatch((left or '').strip() or (right or '').strip()))
    fields.append({'id':fid,'owner':'data' if numeric else 'writer','kind':'number' if numeric else 'text',
                   'semantic':'根据两份原文差异提出，含义与来源规则待确认',
                   'value_schema':{'type':'string','minLength':1,**({'pattern':r'^\d+(?:\.\d+)?%?$'} if numeric else {})},
                   'block':a['index'],'binding':None,
                   'sources':[source(base_doc,a,left),source(other_doc,b,right)]})
    return {'field':fid}

def _gap_parts(gap_a,gap_b,a,base_doc,other_doc,b,fields,source,other_gaps=None):
    if not gap_a and not gap_b:
        return []
    candidates=[gap_b]+[g for g in (other_gaps or []) if g is not None]
    ratios=[SequenceMatcher(None,gap_a,g).ratio() for g in candidates if g]
    long_dissimilar=((len(gap_a)>=40 and (not ratios or min(ratios)<0.75))
                     or (ratios and min(ratios)<0.5 and len(gap_a)>=12))
    if gap_a and (not gap_b or long_dissimilar):
        return [_append_span_field(fields,a,base_doc,other_doc,b,gap_a,gap_b,source)]
    return _token_parts(gap_a,gap_b,base_doc,other_doc,a,b,fields,source)

def _frame_parts(a,correspondences,base_doc,fields,source):
    texts=[a['text']]+[block['text'] for _,block in correspondences]
    frames=shared_paragraph_frames(texts)
    if not frames:
        return None
    locations=[]
    for _,block in correspondences:
        spans=_locate_frame_spans(block['text'],frames)
        if spans is None:
            return None
        locations.append(spans)
    primary_doc,primary_block=correspondences[0]
    primary_spans=locations[0]
    other_span_sets=list(zip(correspondences,locations))
    parts=[]
    pos=0
    for index,frame in enumerate(frames):
        if frame['start']>pos:
            gap_a=a['text'][pos:frame['start']]
            prev=0 if index==0 else primary_spans[index-1][1]
            gap_b=primary_block['text'][prev:primary_spans[index][0]]
            extra=[]
            for (doc,block),spans in other_span_sets[1:]:
                left=0 if index==0 else spans[index-1][1]
                extra.append(block['text'][left:spans[index][0]])
            parts.extend(_gap_parts(gap_a,gap_b,a,base_doc,primary_doc,primary_block,fields,source,extra))
        parts.append({'text':frame['text']})
        pos=frame['end']
    if pos<len(a['text']):
        gap_a=a['text'][pos:]
        gap_b=primary_block['text'][primary_spans[-1][1]:]
        extra=[block['text'][spans[-1][1]:] for (_,block),spans in other_span_sets[1:]]
        parts.extend(_gap_parts(gap_a,gap_b,a,base_doc,primary_doc,primary_block,fields,source,extra))
    return parts

def _schema(fields,writer_only=False):
    properties={}
    for field in fields:
        if writer_only and field['owner']!='writer': continue
        properties[field['id']]={'type':'object','additionalProperties':False,
            'properties':{'value':field['value_schema'],'source_refs':{'type':'array','items':{'type':'string'},'minItems':1}},
            'required':['value','source_refs']}
    schema={'$schema':'https://json-schema.org/draft/2020-12/schema',
            'type':'object','additionalProperties':False,'properties':properties}
    if not writer_only:schema['required']=list(properties)
    return schema

def build_structured_template(documents:list[dict],comparison_ref:str)->dict:
    if len(documents)<2: raise ValueError('at_least_two_reports_required')
    if len({d['sha256'] for d in documents})!=len(documents): raise ValueError('two_distinct_reports_required: duplicate reports')
    base,other=documents[:2]
    fields=[]; blocks=[]; unresolved=[]
    def normalized(b):return b.get('kind','paragraph')+':'+NUMBER.sub('#',b['text'])
    alignment=SequenceMatcher(None,[normalized(b) for b in base['blocks']],
                             [normalized(b) for b in other['blocks']],autojunk=False)
    pairs={}
    for tag,a0,a1,b0,b1 in alignment.get_opcodes():
        if a1-a0==b1-b0 and tag in ('equal','replace'):
            for a,b in zip(base['blocks'][a0:a1],other['blocks'][b0:b1]):
                if a.get('kind')==b.get('kind') and SequenceMatcher(None,normalized(a),normalized(b),autojunk=False).ratio()>=.3:
                    pairs[a['index']]=b
        if tag not in ('equal',):
            unresolved.append({'kind':'alignment_review','base_blocks':[b['index'] for b in base['blocks'][a0:a1]],
                               'other_blocks':[b['index'] for b in other['blocks'][b0:b1]]})
    def source(doc,b,text):return {'file':doc['path'],'sha256':doc['sha256'],'block':b['index'],'text':text}
    for a in base['blocks']:
        b=pairs.get(a['index']); parts=[]
        if b is None:
            unresolved.append({'kind':'unmatched_block','block':a['index']})
            blocks.append({'index':a['index'],'kind':a.get('kind','paragraph'),'parts':[{'text':a['text']}],'unmatched':True})
            continue
        if a.get('kind')=='table':
            fid=f'block_{a["index"]}_rows'
            headers=a.get('rows',[[]])[0]
            is_top10=len(headers)==3 and any('事件' in h for h in headers)
            if is_top10:headers=['序号','事件梗概','负面预警条数']
            field={'id':fid,'owner':'data','kind':'table_rows','semantic':'去重后的负面且已预警事件 TOP10，按事件内符合条件的记录条数降序，使用严肃简明梗概' if is_top10 else '表格数据行；列定义与排序口径需确认',
                   'value_schema':top10_table_schema() if is_top10 else {'type':'array','items':{'type':'array','items':{'type':'string'},'minItems':len(headers),'maxItems':len(headers)}},
                   'sources':[source(base,a,a['text']),source(other,b,b['text'])],
                   'block':a['index'],'binding':{'tool':'top10_events','path':[]} if is_top10 else None}
            fields.append(field); blocks.append({'index':a['index'],'kind':'table','headers':headers,'parts':[{'field':fid}]})
            continue
        correspondences=[(other,b)]
        for extra in documents[2:]:
            mapped=_pair_blocks(base['blocks'],extra['blocks']).get(a['index'])
            if mapped is not None:
                correspondences.append((extra,mapped))
        framed=_frame_parts(a,correspondences,base,fields,source)
        parts=framed if framed is not None else _token_parts(a['text'],b['text'],base,other,a,b,fields,source)
        blocks.append({'index':a['index'],'kind':'paragraph','parts':parts})
    payload={'format_version':1,'status':'candidate_requires_review','comparison_ref':comparison_ref,
             'source_reports':[{'path':d['path'],'sha256':d['sha256']} for d in documents],
             'layout_source':base['path'],'blocks':blocks,'fields':fields,
             'review_items':unresolved+[{'kind':'semantic_review','question':'两份原文相同只构成固定文字候选；字段含义、来源、数据绑定与对齐均需确认。'}]}
    payload['output_schema']=_schema(fields)
    payload['writer_schema']=_schema(fields,True)
    from .chart_spec import definitions
    payload['charts']=definitions(payload)
    if len(documents)>2:
        payload['other_report_hypotheses']=[build_structured_template([base,d],comparison_ref) for d in documents[2:]]
    payload['id']='structured-'+hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:20]
    return payload

def validate_values(template:dict,values:dict,allowed_refs:set[str],writer_only=False,require_complete=False)->None:
    schema=copy.deepcopy(template['writer_schema' if writer_only else 'output_schema'])
    if not require_complete:schema.pop('required',None)
    Draft202012Validator(schema).validate(values)
    fields={f['id']:f for f in template['fields']}
    for key,answer in values.items():
        if not set(answer['source_refs'])<=allowed_refs: raise ValueError('invalid_template_source_ref')
        if '{{' in str(answer['value']): raise ValueError('nested_template_marker')
        if writer_only and fields[key]['owner']!='writer': raise ValueError('data_field_owned_by_tool')

class TemplateArtifactUnavailable(ValueError):
    """One health/error contract for management, generation and approval."""
    def __init__(self, code):
        self.code = code
        self.artifact_status = 'missing' if code == 'template_artifact_missing' else 'unreadable'
        super().__init__(code)


def read_template_artifact(store, ref):
    try:
        template = store.get_artifact(ref)
    except (KeyError, FileNotFoundError) as exc:
        raise TemplateArtifactUnavailable('template_artifact_missing') from exc
    except (OSError, ValueError) as exc:
        raise TemplateArtifactUnavailable('template_artifact_unreadable') from exc
    if not isinstance(template, dict):
        raise TemplateArtifactUnavailable('template_artifact_unreadable')
    return template


def load_confirmed_template(store,ref:str)->dict:
    template=read_template_artifact(store,ref)
    if template.get('status')!='confirmed_by_human' or len(template.get('source_reports',[]))<2:
        raise ValueError('confirmed_two_report_template_required')
    if not template.get('comparison_ref') or not template.get('writer_schema'):
        raise ValueError('structured_template_missing')
    return template

#: 模板级「跑不跑」开关；未声明或脏值一律当 True（老模板行为一字不变）。
FEATURE_SWITCHES=('dedup','classification','first_warning','top10')

def template_feature_switches(state,store)->dict:
    """本任务的四个处理开关（core 侧唯一读法：只读任务里已经落盘的值）。

    `metadata['template_rules']['features']` 由宿主在**建报告任务时**算好写入：宿主把
    「模板级 AND 客户包级」的生效结果落进任务（`app.workflow.task_feature_snapshot`），
    所以这里读到的是生效值，不是模板级原值——客户包级开关只有宿主看得见，core 不读包配置。
    同一份值也是宿主 `_template_features` 的任务级快照（快照对已建任务不可变）。
    只在该键缺失（老任务/老版本）时回读一次已确认模板：那是模板级原值，不含包级约束。
    任何读取失败都按「全开」处理，不静默关掉客户流程。
    """
    metadata=getattr(state,'metadata',None)
    rules=metadata.get('template_rules') if isinstance(metadata,dict) else None
    if not isinstance(rules,dict) or 'features' not in rules:
        ref=getattr(state,'template_ref',None)
        rules={}
        if ref:
            try:rules=load_confirmed_template(store,ref).get('rules') or {}
            except (KeyError,ValueError):rules={}
    raw=rules.get('features') if isinstance(rules,dict) else None
    raw=raw if isinstance(raw,dict) else {}
    return {name:raw.get(name) is not False for name in FEATURE_SWITCHES}

def apply_top10_rule(template:dict)->dict:
    result=copy.deepcopy(template)
    for block in result['blocks']:
        if block['kind']!='table' or len(block.get('headers',[]))!=3 or not any('事件' in h for h in block['headers']):continue
        block['headers']=['序号','事件梗概','负面预警条数']
        key=block['parts'][0].get('field')
        for field in result['fields']:
            if field['id']==key:
                field.update(binding={'tool':'top10_events','path':[]},display_name='负面预警事件 TOP10',value_schema=top10_table_schema(),
                    semantic='负面且已预警记录按事件去重后，按每个事件内符合条件的记录条数降序；展示15至35字的严肃、简明事件梗概')
    result['top10_rule']={'scope':'negative_and_warning','unit':'deduplicated_event','ranking':'negative_warning_member_count','direction':'descending','display':'serious_concise_summary','summary_min_chars':15,'summary_max_chars':35}
    result['output_schema']=_schema(result['fields']);result['writer_schema']=_schema(result['fields'],True)
    return result

def revise_candidate(template:dict,changes:dict)->dict:
    if template.get('status')!='candidate_requires_review': raise ValueError('immutable_confirmed_template')
    result=copy.deepcopy(template);fields={f['id']:f for f in result['fields']}
    for key,patch in changes.items():
        if key not in fields or not set(patch)<={'semantic','display_name','binding','value_schema'}:
            raise ValueError('invalid_template_field_patch')
        if 'value_schema' in patch:Draft202012Validator.check_schema(patch['value_schema'])
        if patch.get('binding'):
            binding=patch['binding']
            if fields[key]['owner']!='data' or binding.get('tool')!='calculate_metrics' or not isinstance(binding.get('path'),list) or not all(isinstance(x,str) for x in binding['path']):
                raise ValueError('invalid_data_binding')
        fields[key].update(patch)
    result['output_schema']=_schema(result['fields'])
    result['writer_schema']=_schema(result['fields'],True)
    result['id']='structured-'+hashlib.sha256(json.dumps(result,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:20]
    return result

def _render_omissions(template,body,original,W):
    """渲染期直接删段/删字：`omitted_sections` 点名的块不再需要派生版式副本。

    `render_structured_docx` 是从**版式源文件**增量改写的：模板里没有的块，版式里那一段
    会原样留在成稿里。所以「整段不生成」要么落到版式本身（旧做法：生成派生副本），要么
    在渲染期按模板记录把这些块删掉（现做法，版式保持原始文件）。

    只对带 `render_trim` 标记的模板生效：历史上生成的确认版本把该段删在派生版式里，
    其 `omitted_sections.blocks` 是**原始版式**的下标、与派生版式偏移不一致，
    对它们重复删会删错段——没有标记时保持旧路径一字不动。
    """
    omitted=template.get('omitted_sections') or {}
    if not omitted.get('render_trim'):return
    dropped=set()
    for value in omitted.get('blocks') or []:
        try:index=int(value)
        except (TypeError,ValueError):continue
        if 0<=index<len(original):dropped.add(index)
    for index in sorted(dropped):body.remove(original[index])
    for key,ranges in (omitted.get('paragraph_edits') or {}).items():
        try:index=int(key)
        except (TypeError,ValueError):continue
        if index in dropped or not (0<=index<len(original)):continue
        spans=[]
        for item in ranges or []:
            try:start,end=int(item[0]),int(item[1])
            except (TypeError,ValueError,IndexError):continue
            if end>start>=0:spans.append((start,end))
        if not spans:continue
        # 与派生版式里「物理删字」等价：按字符区间把被删的字从各 run 里摘掉（保留格式）。
        cursor=0
        for node in original[index].iter(W+'t'):
            text=node.text or ''
            node.text=''.join(char for position,char in enumerate(text)
                              if not any(cursor+position>=start and cursor+position<end for start,end in spans))
            cursor+=len(text)

def render_structured_docx(template:dict,values:dict,allowed_refs:set[str],require_complete=False,charts:dict|None=None)->bytes:
    from lxml import etree as ET
    validate_values(template,values,allowed_refs,require_complete=require_complete)
    path=Path(template['layout_source'])
    if not path.exists():
        from . import paths
        current=paths.data_root()/'uploads'/path.name
        if current.exists():path=current
    if hashlib.sha256(path.read_bytes()).hexdigest()!=template['source_reports'][0]['sha256']:
        raise ValueError('template_layout_source_changed')
    W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    with zipfile.ZipFile(path) as zin:
        root=ET.fromstring(zin.read('word/document.xml'));body=root.find(W+'body')
        original=list(body)
        _render_omissions(template,body,original,W)
        charts=charts or {};chart_files={}
        rel_path='word/_rels/document.xml.rels'
        rels=ET.fromstring(zin.read(rel_path)) if rel_path in zin.namelist() else ET.Element('{http://schemas.openxmlformats.org/package/2006/relationships}Relationships')
        content_types=ET.fromstring(zin.read('[Content_Types].xml')) if '[Content_Types].xml' in zin.namelist() else None
        from core.charts.spec import drawing_ids as _drawing_ids,DEFAULT_DRAWING_IDS,chart_slot_drawings,bind_drawing_image
        chart_names=_drawing_ids(template)
        # 只替换图表槽，保留封面图和文本框的几何与关系。
        for i,drawing in enumerate(chart_slot_drawings(root),1):
            name=chart_names.get(i) or (DEFAULT_DRAWING_IDS[i-1] if i<=len(DEFAULT_DRAWING_IDS) else str(i))
            if name in charts:
                import base64
                png=base64.b64decode(charts[name]['png_base64'],validate=True)
                from PIL import Image
                with Image.open(io.BytesIO(png)) as image:
                    if image.format!='PNG':raise ValueError('chart_not_png')
                    pixel_width,pixel_height=image.size
                    image.verify()
                # Source images can have another aspect ratio. Preserve the
                # position and width while keeping current pies truly circular.
                for extent in drawing.xpath('.//*[local-name()="extent" or local-name()="ext"]'):
                    if extent.get('cx') and extent.get('cy'):
                        extent.set('cy',str(round(int(extent.get('cx'))*pixel_height/pixel_width)))
                for crop in drawing.xpath('.//*[local-name()="srcRect"]'):
                    for edge in ('l','t','r','b'):crop.set(edge,'0')
                filename=f'media/frozen_chart_{i}.png';chart_files['word/'+filename]=png
                rid=f'rIdFrozenChart{i}'
                if any(r.get('Id')==rid for r in rels):raise ValueError('chart_relationship_collision')
                ET.SubElement(rels,'{http://schemas.openxmlformats.org/package/2006/relationships}Relationship',Id=rid,Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/image',Target=filename)
                bind_drawing_image(drawing, rid)
            else:
                if require_complete:raise ValueError('missing_current_chart:'+name)
                parent=drawing.getparent();parent.remove(drawing)
                ET.SubElement(parent,W+'t').text='{{CHART_'+str(i)+'}}'
        def set_text(element,text):
            nodes=list(element.iter(W+'t'))
            if nodes:
                nodes[0].text=text
                for node in nodes[1:]:node.text=''
        def replace_spans(element,spans):
            # Replace only changed ranges so unchanged runs retain their Word formatting.
            for start,end,value in reversed(spans):
                nodes=list(element.iter(W+'t'));offset=0;locations=[]
                for node in nodes:
                    text=node.text or '';locations.append((node,offset,offset+len(text)));offset+=len(text)
                if not locations:continue
                first=next(((node,a,b) for node,a,b in locations if a<=start<b),locations[-1])
                last=next(((node,a,b) for node,a,b in locations if a<=end<=b and b>=start),locations[-1])
                if start==end:last=first
                node,a,_=first;tail_node,tail_start,_=last
                prefix=(node.text or '')[:start-a]
                suffix=(tail_node.text or '')[end-tail_start:]
                if node is tail_node:node.text=prefix+value+suffix
                else:
                    node.text=prefix+value;tail_node.text=suffix
                    active=False
                    for entry,_,_ in locations:
                        if entry is tail_node:break
                        if active:entry.text=''
                        if entry is node:active=True
        insert_cursors={}
        for block in template['blocks']:
            after=block.get('insert_after_index')
            if after is not None and block['index'] not in original:
                style_from=block.get('style_from_index', after)
                if style_from not in original:
                    raise ValueError('missing_insert_style_block:'+str(style_from))
                style_el=original[style_from]
                if style_el.tag!=W+'p':
                    raise ValueError('insert_style_must_be_paragraph:'+str(style_from))
                anchor=insert_cursors.get(after, original.get(after))
                if anchor is None:
                    raise ValueError('missing_insert_after_block:'+str(after))
                new_el=copy.deepcopy(style_el)
                set_text(new_el,'')
                parent=anchor.getparent()
                parent.insert(parent.index(anchor)+1,new_el)
                original[block['index']]=new_el
                insert_cursors[after]=new_el
        for block in template['blocks']:
            element=original[block['index']]
            if block.get('unmatched'):
                set_text(element,'{{UNMATCHED_BLOCK_'+str(block['index'])+'}}')
                continue
            if block['kind']=='repeat':
                key=block['parts'][0]['field'];answer=values.get(key)
                for index in block['source_block_indexes'][1:]:
                    body.remove(original[index])
                if answer is None:
                    set_text(element,'{{'+key+'}}')
                else:
                    exemplar=copy.deepcopy(element)
                    for index,text in enumerate(answer['value']):
                        row=element if index==0 else copy.deepcopy(exemplar)
                        set_text(row,str(index+1)+'. '+re.sub(r'^\s*\d+[.、．]\s*','',text))
                        if index:body.insert(body.index(element)+index,row)
                continue
            if block['kind']=='table':
                header_row=element.find(W+'tr')
                if header_row is not None:
                    for cell,value in zip(header_row.findall(W+'tc'),block.get('headers',[])):set_text(cell,value)
                key=block['parts'][0]['field'];answer=values.get(key)
                if answer is None:
                    for row in list(element.findall(W+'tr'))[1:]:
                        for cell in row.findall(W+'tc'):set_text(cell,'{{'+key+'}}')
                    continue
                rows=element.findall(W+'tr'); exemplar=copy.deepcopy(rows[1] if len(rows)>1 else rows[0])
                for row in rows[1:]:element.remove(row)
                for data in answer['value']:
                    row=copy.deepcopy(exemplar)
                    for cell,value in zip(row.findall(W+'tc'),data):set_text(cell,value)
                    element.append(row)
            elif block.get('unmatched'):
                set_text(element,'{{UNMATCHED_BLOCK_'+str(block['index'])+'}}')
            elif block.get('insert_after_index') is not None:
                chunks=[];missing=False
                for part in block['parts']:
                    if 'text' in part:chunks.append(part['text']);continue
                    key=part['field']
                    if key in values:chunks.append(str(values[key]['value']))
                    elif block.get('optional'):missing=True;break
                    else:chunks.append('{{'+key+'}}')
                if missing:
                    parent=element.getparent()
                    if parent is not None:parent.remove(element)
                else:
                    set_text(element,''.join(chunks))
            else:
                cursor=0;spans=[];field_map={f['id']:f for f in template['fields']}
                for part in block['parts']:
                    if 'text' in part:cursor+=len(part['text']);continue
                    key=part['field'];length=len(field_map[key]['sources'][0]['text'])
                    value=str(values[key]['value']) if key in values else '{{'+key+'}}'
                    spans.append((cursor,cursor+length,value));cursor+=length
                replace_spans(element,spans)
        unit_by_id={}
        for item in (template.get('charts') or []):
            if item.get('id') and item.get('unit'):
                unit_by_id[item['id']]=item['unit']
        for paragraph in root.iter(W+'p'):
            caption=''.join(n.text or '' for n in paragraph.iter(W+'t'))
            matched=re.match(r'图(\d+)',caption)
            if not matched:continue
            index=int(matched.group(1))
            name=chart_names.get(index) or (DEFAULT_DRAWING_IDS[index-1] if index<=len(DEFAULT_DRAWING_IDS) else None)
            if not name or name not in charts:continue
            unit=unit_by_id.get(name)
            if unit is None:
                try:
                    from core.charts import registry as _chart_registry
                    unit=_chart_registry.chart(name).get('unit')
                except Exception:
                    unit='件' if name in ('theme','locality') else None
            if unit=='件':
                set_text(paragraph,re.sub(r'(单位[：:]\s*)条',r'\1件',caption))
        out=io.BytesIO()
        if chart_files and content_types is not None and not any(e.get('Extension')=='png' for e in content_types):
            ET.SubElement(content_types,'{http://schemas.openxmlformats.org/package/2006/content-types}Default',Extension='png',ContentType='image/png')
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                replacement={'word/document.xml':root,rel_path:rels,'[Content_Types].xml':content_types}.get(item.filename)
                zout.writestr(item,ET.tostring(replacement,xml_declaration=True,encoding='UTF-8',standalone=True) if replacement is not None else zin.read(item.filename))
            for name,png in chart_files.items():zout.writestr(name,png)
        return out.getvalue()
