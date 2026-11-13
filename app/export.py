"""Minimal editable Word output for the verifiable draft path."""
from __future__ import annotations
import html,io,zipfile,re,base64,copy
from pathlib import Path
from core import paths

def _source_template_draft(draft,facts,issues):
    from lxml import etree as ET
    from .config import DATA
    path=paths.template_dir()/'template-with-placeholders.docx'
    if not path.exists(): return None
    ref=facts.get('result_refs',{}).get('calculate_metrics')
    if not ref: return None
    from .storage import Store
    metrics=Store(DATA).get_artifact(ref)
    total=metrics['record_count']; sentiment=metrics['sentiment']
    def pct(x): return f'{x/total*100:.2f}' if total else '缺失'
    month=facts.get('report_month') or '2026-10'
    try: year,m=month.split('-'); m=int(m)
    except Exception: year,m='2026',10
    values={'B5_COVER':f'{year}年第{m}期','B12_COVER':f'安顺市{year}年{m}月网络舆情分析报告','B17_RED_01':f'{total/10000:.2f}','B17_RED_02':str(sentiment.get('正面',0)),'B17_RED_03':pct(sentiment.get('正面',0)),'B17_RED_04':str(sentiment.get('中性',0)),'B17_RED_05':pct(sentiment.get('中性',0)),'B17_RED_06':str(sentiment.get('负面',0)),'B17_RED_07':pct(sentiment.get('负面',0))+'%','B26_RED_01':str(m),'B29_RED_01':str(m)}
    platforms=['移动客户端','网站','微信公众号','视频','微博','纸媒','电视','互动栏目']
    values['B26_MAGENTA_02']='、'.join(platforms[:-1])+'、互动栏目平台'
    for index,label in enumerate(platforms):
        start=3+index*3 if index<7 else 26
        values[f'B26_MAGENTA_{start:02}']=label
        count_slot=start+1 if index<7 else 22
        percent_slot=start+2 if index<7 else 23
        values[f'B26_RED_{count_slot:02}']=str(metrics['platform'].get(label,0))
        values[f'B26_RED_{percent_slot:02}']=pct(metrics['platform'].get(label,0))+('%' if index==7 else '')
    dedup_path=facts.get('deduplicated_path')
    if dedup_path:
        from collections import Counter
        from .ooxml import read_xlsx
        workbook=read_xlsx(Path(dedup_path),sheet_index=int(facts.get('deduplicated_sheet_index',3)))
        header=workbook['rows'][0]['cells']
        required=('区县','事件分类')
        if not all(name in header for name in required): raise ValueError('deduplicated_source_missing_columns')
        rows=workbook['rows'][1:]
        n=len(rows)
        values.update({'B17_RED_10':str(n),'B17_RED_11':f'{n/total*100:.2f}%',
                       'B30_RED_01':str(n)})
        categories=Counter(r['cells'][header.index('事件分类')] for r in rows)
        if categories:
            category,count=categories.most_common(1)[0]
            values['B30_YELLOW_03']=category
            values['B30_RED_04']=f'{count/n*100:.2f}'
            values['B17_YELLOW_12']='、'.join(name for name,_ in categories.most_common(6))
        localities=Counter(r['cells'][header.index('区县')] for r in rows)
        locality_slots=[('市区',7),('西秀区',9),('黄果树旅游区',11),('关岭县',13),('平坝区',15),('紫云县',17),('普定县',19),('镇宁县',21),('安顺经开区',23)]
        for label,index in locality_slots:
            count=localities.get(label,0)
            values[f'B30_RED_{index:02}']=str(count)
            values[f'B30_RED_{index+1:02}']=f'{count/n*100:.2f}' if n else '缺失'
    peak=metrics.get('peak_day')
    if peak:
        try: values['B17_RED_08']=f'{int(peak[5:7])}月{int(peak[8:10])}日'
        except Exception: pass
    for slot_id,answer in draft.get('slot_values',{}).items():
        if not isinstance(answer,dict) or not answer.get('source_refs') or not isinstance(answer.get('value'),str):
            continue
        if slot_id in values: continue
        values[slot_id]=answer['value']
    for row in facts.get('top10',[]):
        values[f'TOP10_{row["rank"]:02}_EVENT']=row['summary']
        values[f'TOP10_{row["rank"]:02}_HEAT']=str(row['negative_warning_count'])
    with zipfile.ZipFile(path) as zin:
        root=ET.fromstring(zin.read('word/document.xml'))
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        for cell in root.xpath('//w:tbl/w:tr[1]/w:tc',namespaces=ns):
            for text in cell.xpath('.//w:t',namespaces=ns):
                if text.text=='热度':text.text='负面预警条数'
        for t in root.xpath('//w:t',namespaces=ns):
            if t.text:
                for key,value in values.items(): t.text=t.text.replace('{{'+key+'}}',value)
        chart_names=['sentiment','daily','platform','theme','locality']
        original=ET.fromstring(zin.read('word/document.xml'))
        # The template carries no old drawing, so use the supplied source's five drawing geometries.
        with zipfile.ZipFile(paths.template_dir()/'source-2026-08.docx') as source_zip:
            source_root=ET.fromstring(source_zip.read('word/document.xml'))
        old_drawings=source_root.xpath('//w:drawing',namespaces=ns)
        rel_path='word/_rels/document.xml.rels'
        rels=ET.fromstring(zin.read(rel_path))
        rel_ns='http://schemas.openxmlformats.org/package/2006/relationships'
        chart_files={}
        for i,name in enumerate(chart_names,1):
            ref=facts.get('result_refs',{}).get('render_chart:'+name)
            if not ref or i>len(old_drawings): continue
            payload=Store(DATA).get_artifact(ref)
            png=base64.b64decode(payload['png_base64']); chart_files[f'word/media/chart_{i}.png']=png
            rid=f'rIdChart{i}'
            relation=ET.SubElement(rels,f'{{{rel_ns}}}Relationship'); relation.set('Id',rid); relation.set('Type','http://schemas.openxmlformats.org/officeDocument/2006/relationships/image'); relation.set('Target',f'media/chart_{i}.png')
            targets=root.xpath('//w:t',namespaces=ns)
            t=next((x for x in targets if x.text=='{{CHART_'+str(i)+'}}'),None)
            if t is None: continue
            run=t.getparent(); run.remove(t)
            drawing=copy.deepcopy(old_drawings[i-1])
            for blip in drawing.xpath('.//*[local-name()="blip"]'):
                blip.set('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed',rid)
            run.append(drawing)
        body=root.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}body')
        p=ET.Element('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p')
        r=ET.SubElement(p,'{http://schemas.openxmlformats.org/wordprocessingml/2006/main}r')
        t=ET.SubElement(r,'{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t')
        t.text=f'结构演示草稿。事实版本 {draft["fact_ref"]}；仍有 {len(issues)} 项待审。未填占位符不得视为正式内容。'
        body.insert(0,p)
        out=io.BytesIO()
        content_types=ET.fromstring(zin.read('[Content_Types].xml'))
        ct_ns='http://schemas.openxmlformats.org/package/2006/content-types'
        if chart_files and not any(x.get('Extension')=='png' for x in content_types):
            ET.SubElement(content_types,f'{{{ct_ns}}}Default',Extension='png',ContentType='image/png')
        with zipfile.ZipFile(out,'w') as zout:
            for item in zin.infolist():
                value=zin.read(item.filename)
                if item.filename=='word/document.xml': value=ET.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
                elif item.filename==rel_path: value=ET.tostring(rels,xml_declaration=True,encoding='UTF-8',standalone=True)
                elif item.filename=='[Content_Types].xml': value=ET.tostring(content_types,xml_declaration=True,encoding='UTF-8',standalone=True)
                zout.writestr(item,value)
            for name,data in chart_files.items(): zout.writestr(name,data)
        return out.getvalue()

def _p(text,style=None):
    value=html.escape(str(text))
    ppr=f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ''
    return f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{value}</w:t></w:r></w:p>'

def _table(rows):
    body=[]
    for row in rows:
        body.append('<w:tr>'+''.join('<w:tc><w:tcPr><w:tcW w:w="3000" w:type="dxa"/></w:tcPr>'+_p(v)+'</w:tc>' for v in row)+'</w:tr>')
    return '<w:tbl><w:tblPr><w:tblBorders><w:bottom w:val="single" w:sz="4"/></w:tblBorders></w:tblPr>'+''.join(body)+'</w:tbl>'

def export_docx(draft:dict,facts:dict,template:dict|None,mode:str,issues:list[dict],local_store=None)->bytes:
    if mode=='final' and issues: raise ValueError('unresolved_blockers')
    if draft.get('structured_template_ref'):
        from .structured_template import load_confirmed_template,render_structured_docx
        from .storage import Store
        from .config import DATA
        active_store=local_store or Store(DATA)
        version=load_confirmed_template(active_store,draft['structured_template_ref'])
        charts={}
        for name,ref in draft.get('chart_refs',{}).items():
            if ref not in draft.get('evidence_refs',[]):raise ValueError('unauthorized_chart_ref')
            chart=active_store.get_artifact(ref)
            if chart.get('fact_ref')!=draft['fact_ref'] or chart.get('chart_type')!=name:raise ValueError('stale_chart_fact')
            charts[name]=chart
        return render_structured_docx(version,draft.get('slot_values',{}),set(draft.get('evidence_refs',[])),require_complete=mode=='final',charts=charts)
    if mode=='draft':
        source=_source_template_draft(draft,facts,issues)
        if source is not None: return source
    parts=[_p('安顺月报工作台结构演示稿','Title'),_p('报告状态：'+('终稿' if mode=='final' else '草稿')),_p('正式事实引用：'+draft['fact_ref'])]
    for section in draft['sections']:
        parts.extend([_p(section['heading'],'Heading1'),_p(section['text'])])
    parts.append(_p('来源与处理结果','Heading1'))
    parts.append(_table([['工具','结果工件']]+[[k,v] for k,v in facts.get('result_refs',{}).items()]))
    if issues:
        parts.append(_p('待解决问题','Heading1'))
        parts.extend(_p(x['question']) for x in issues)
    doc='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+''.join(parts)+'<w:sectPr/></w:body></w:document>'
    styles='<?xml version="1.0" encoding="UTF-8"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:sz w:val="32"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style></w:styles>'
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
        z.writestr('_rels/.rels','<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr('word/document.xml',doc)
        z.writestr('word/styles.xml',styles)
    return out.getvalue()

