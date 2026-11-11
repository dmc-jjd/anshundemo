"""Versioned report templates derived from at least two readable source reports."""
from __future__ import annotations
import copy,hashlib,io,json,re,zipfile
from difflib import SequenceMatcher
from pathlib import Path
from jsonschema import Draft202012Validator

NUMBER=re.compile(r'\d+(?:\.\d+)?%?')
def top10_table_schema():
    return {'type':'array','maxItems':10,'items':{'type':'array','minItems':3,'maxItems':3,'items':False,
        'prefixItems':[{'type':'string'},{'type':'string','minLength':15,'maxLength':35},{'type':'string'}]}}
def _tokens(text):
    return re.findall(r'\d+(?:\.\d+)?%?|[^\d]',text)

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
        tokens_a,tokens_b=_tokens(a['text']),_tokens(b['text'])
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
                           'sources':[source(base,a,left),source(other,b,right)]})
            parts.append({'field':fid})
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

def load_confirmed_template(store,ref:str)->dict:
    template=store.get_artifact(ref)
    if template.get('status')!='confirmed_by_human' or len(template.get('source_reports',[]))<2:
        raise ValueError('confirmed_two_report_template_required')
    if not template.get('comparison_ref') or not template.get('writer_schema'):
        raise ValueError('structured_template_missing')
    return template

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

def render_structured_docx(template:dict,values:dict,allowed_refs:set[str],require_complete=False,charts:dict|None=None)->bytes:
    from lxml import etree as ET
    validate_values(template,values,allowed_refs,require_complete=require_complete)
    path=Path(template['layout_source'])
    if not path.exists():
        from .config import DATA
        if (DATA/'uploads'/path.name).exists():path=DATA/'uploads'/path.name
    if hashlib.sha256(path.read_bytes()).hexdigest()!=template['source_reports'][0]['sha256']:
        raise ValueError('template_layout_source_changed')
    W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    with zipfile.ZipFile(path) as zin:
        root=ET.fromstring(zin.read('word/document.xml'));body=root.find(W+'body')
        original=list(body)
        charts=charts or {};chart_files={}
        rel_path='word/_rels/document.xml.rels'
        rels=ET.fromstring(zin.read(rel_path)) if rel_path in zin.namelist() else ET.Element('{http://schemas.openxmlformats.org/package/2006/relationships}Relationships')
        content_types=ET.fromstring(zin.read('[Content_Types].xml')) if '[Content_Types].xml' in zin.namelist() else None
        chart_names=['sentiment','daily','platform','theme','locality']
        # Replace each old drawing's relationship, preserving its Word geometry.
        for i,drawing in enumerate(list(root.iter(W+'drawing')),1):
            name=chart_names[i-1] if i<=len(chart_names) else str(i)
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
                for blip in drawing.xpath('.//*[local-name()="blip"]'):
                    blip.set('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed',rid)
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
            else:
                cursor=0;spans=[];field_map={f['id']:f for f in template['fields']}
                for part in block['parts']:
                    if 'text' in part:cursor+=len(part['text']);continue
                    key=part['field'];length=len(field_map[key]['sources'][0]['text'])
                    value=str(values[key]['value']) if key in values else '{{'+key+'}}'
                    spans.append((cursor,cursor+length,value));cursor+=length
                replace_spans(element,spans)
        for paragraph in root.iter(W+'p'):
            text=''.join(n.text or '' for n in paragraph.iter(W+'t'))
            if (text.startswith('图4') and 'theme' in charts) or (text.startswith('图5') and 'locality' in charts):
                set_text(paragraph,re.sub(r'(单位[：:]\s*)条',r'\1件',text))
        out=io.BytesIO()
        if chart_files and content_types is not None and not any(e.get('Extension')=='png' for e in content_types):
            ET.SubElement(content_types,'{http://schemas.openxmlformats.org/package/2006/content-types}Default',Extension='png',ContentType='image/png')
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                replacement={'word/document.xml':root,rel_path:rels,'[Content_Types].xml':content_types}.get(item.filename)
                zout.writestr(item,ET.tostring(replacement,xml_declaration=True,encoding='UTF-8',standalone=True) if replacement is not None else zin.read(item.filename))
            for name,png in chart_files.items():zout.writestr(name,png)
        return out.getvalue()
