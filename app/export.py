"""Minimal editable Word output for the verifiable draft path."""
from __future__ import annotations
import html,io,zipfile,re,base64,copy
from pathlib import Path
from core import paths

def _package_of(draft=None,facts=None,store=None):
    if facts and facts.get('package'): return facts.get('package')
    if draft and draft.get('package'): return draft.get('package')
    if store is not None and callable(getattr(store,'package',None)):
        try: return store.package()
        except Exception: pass
    return None

def _export_cfg(package=None):
    from core.packages import load_package
    return dict((load_package(package).template or {}).get('export') or {})

def template_values(draft,facts,issues=None,store=None):
    """模板 99 个占位符的「计算结果」字典——从 `_source_template_draft` 原样抽出。

    抽出只为复用（终稿 A4 页要显示同一批值），算法一行未改：
    - `store=None` 时仍用 `Store(DATA)`（`DATA` 在调用期取自 `app.config`，测试可注入数据根）；
    - 没有 `calculate_metrics` 工件时返回 `{}`，调用方据此走原来的「无模板」分支。
    """
    from .config import DATA
    from .storage import Store
    ref=facts.get('result_refs',{}).get('calculate_metrics')
    if not ref: return {}
    store=store or Store(DATA)
    metrics=store.get_artifact(ref)
    total=metrics['record_count']; sentiment=metrics['sentiment']
    def pct(x): return f'{x/total*100:.2f}' if total else '缺失'
    month=facts.get('report_month') or '2026-10'
    try: year,m=month.split('-'); m=int(m)
    except Exception: year,m='2026',10
    package=_package_of(draft,facts,store)
    cfg=_export_cfg(package)
    values={}
    if not cfg:
        for slot_id,answer in draft.get('slot_values',{}).items():
            if isinstance(answer,dict) and answer.get('source_refs') and isinstance(answer.get('value'),str):
                values[slot_id]=answer['value']
        return values
    values={'B17_RED_01':f'{total/10000:.2f}','B17_RED_02':str(sentiment.get('正面',0)),'B17_RED_03':pct(sentiment.get('正面',0)),'B17_RED_04':str(sentiment.get('中性',0)),'B17_RED_05':pct(sentiment.get('中性',0)),'B17_RED_06':str(sentiment.get('负面',0)),'B17_RED_07':pct(sentiment.get('负面',0))+'%','B26_RED_01':str(m),'B29_RED_01':str(m)}
    cover=cfg.get('cover') or {}
    if cover.get('issue_slot'):
        values[cover['issue_slot']]=str(cover.get('issue') or '{year}年第{m}期').format(year=year,m=m)
    if cover.get('title_slot'):
        values[cover['title_slot']]=str(cover.get('title') or '').format(year=year,m=m)
    platform_slots=list(cfg.get('platform_slots') or ())
    if platform_slots:
        names=[item['name'] for item in platform_slots]
        suffix=cfg.get('platform_list_suffix')
        if cfg.get('platform_list_slot'):
            values[cfg['platform_list_slot']]='、'.join(names[:-1])+ (suffix if suffix is not None else ('、'+names[-1] if names else ''))
        for item in platform_slots:
            label=item['name']
            if item.get('label_slot'): values[item['label_slot']]=label
            if item.get('count_slot'): values[item['count_slot']]=str(metrics['platform'].get(label,0))
            if item.get('percent_slot'): values[item['percent_slot']]=pct(metrics['platform'].get(label,0))+str(item.get('percent_suffix') or '')
    dedup_path=facts.get('deduplicated_path')
    if dedup_path:
        from collections import Counter
        from .ooxml import read_xlsx
        sheet=facts.get('deduplicated_sheet_index', facts.get('sheet_index'))
        if sheet is None:
            from core.tools import vocabulary
            sheet=vocabulary.sheet_index(facts.get('package'))
        workbook=read_xlsx(Path(dedup_path),sheet_index=int(sheet))
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
        for item in (cfg.get('localities') or ()):
            label,index=item['name'],int(item['index'])
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
    return values

def _source_template_draft(draft,facts,issues,overrides=None,local_store=None):
    from lxml import etree as ET
    from .config import DATA
    from .storage import Store
    package=_package_of(draft,facts,local_store)
    from core.layout import docx_path
    try: path=docx_path(package)
    except RuntimeError: return None
    if not path.exists(): return None
    values=template_values(draft,{**facts,'package':package} if package else facts,issues)
    if not values: return None
    if overrides:
        # 人工覆盖优先于计算结果：终稿以人工研判提交值为准（见 app/final_document.py）。
        # 只替换模板里真实出现的 {{key}}，未知 key 是空操作，不改变任何既有输出。
        values.update({str(key):str(value) for key,value in overrides.items()})
    with zipfile.ZipFile(path) as zin:
        root=ET.fromstring(zin.read('word/document.xml'))
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        for cell in root.xpath('//w:tbl/w:tr[1]/w:tc',namespaces=ns):
            for text in cell.xpath('.//w:t',namespaces=ns):
                if text.text=='热度':text.text='负面预警条数'
        for t in root.xpath('//w:t',namespaces=ns):
            if t.text:
                for key,value in values.items(): t.text=t.text.replace('{{'+key+'}}',value)
        from core.charts.spec import declared_charts
        from core.layout import source_docx_path
        chart_names=[item['id'] for item in declared_charts(package=package)]
        original=ET.fromstring(zin.read('word/document.xml'))
        source_path=source_docx_path(package)
        if source_path is None or not source_path.exists(): return None
        with zipfile.ZipFile(source_path) as source_zip:
            source_root=ET.fromstring(source_zip.read('word/document.xml'))
        old_drawings=source_root.xpath('//w:drawing',namespaces=ns)
        rel_path='word/_rels/document.xml.rels'
        rels=ET.fromstring(zin.read(rel_path))
        rel_ns='http://schemas.openxmlformats.org/package/2006/relationships'
        chart_files={}
        for i,name in enumerate(chart_names,1):
            ref=facts.get('result_refs',{}).get('render_chart:'+name)
            if not ref or i>len(old_drawings): continue
            payload=(local_store if local_store is not None else Store(paths.data_root(package))).get_artifact(ref)
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

def export_docx(draft:dict,facts:dict,template:dict|None,mode:str,issues:list[dict],local_store=None,overrides:dict|None=None,features:dict|None=None)->bytes:
    """导出 Word。

    `overrides` 是终稿人工审核页保存的槽位覆盖：键为占位符 id（如 `B17_RED_01`），
    优先级**高于**计算结果。`overrides=None`（默认）时输出与引入该参数前逐字节相同。
    说明：结构化模板分支（`draft['structured_template_ref']`）不消费该参数——它的槽位
    来源是 `draft['slot_values']`，覆盖语义由终稿页自身承担。

    `features` 是本任务**生效**的四个处理开关（模板级 AND 客户包级，建任务时由
    `workflow.task_feature_snapshot` 落盘、`workflow.effective_features` 读出）。
    模板是在开关还开着时确认的，之后（或客户包级）关掉的段落必须在渲染前剪掉，
    否则题注/表头照出（B7-2）。全开时 `omit_disabled_sections` 原样返回同一对象，
    输出与不传该参数逐字节相同；`features=None`（历史调用方/普通模板）不剪枝。
    """
    if mode=='final' and issues: raise ValueError('unresolved_blockers')
    if draft.get('structured_template_ref'):
        from .structured_template import load_confirmed_template,render_structured_docx
        from .storage import Store
        from .config import DATA
        active_store=local_store or Store(DATA)
        version=load_confirmed_template(active_store,draft['structured_template_ref'])
        if features is not None:
            from .api_views.template import omit_disabled_sections
            version=omit_disabled_sections(version,features)
        charts={}
        for name,ref in draft.get('chart_refs',{}).items():
            if ref not in draft.get('evidence_refs',[]):raise ValueError('unauthorized_chart_ref')
            chart=active_store.get_artifact(ref)
            if chart.get('fact_ref')!=draft['fact_ref'] or chart.get('chart_type')!=name:raise ValueError('stale_chart_fact')
            charts[name]=chart
        return render_structured_docx(version,draft.get('slot_values',{}),set(draft.get('evidence_refs',[])),require_complete=mode=='final',charts=charts)
    if mode=='draft':
        source=_source_template_draft(draft,facts,issues,overrides,local_store)
        if source is not None: return source
    package=_package_of(draft,facts,local_store)
    demo_title=(_export_cfg(package).get('demo_title') or '结构演示稿')
    parts=[_p(demo_title,'Title'),_p('报告状态：'+('终稿' if mode=='final' else '草稿')),_p('正式事实引用：'+draft['fact_ref'])]
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

