"""Preserve the supplied Word package while replacing variable runs with named slots."""
from __future__ import annotations
import hashlib,json,re,zipfile
from pathlib import Path
from lxml import etree as ET

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'templates/anshun-colored/source-2026-08.docx'
TARGET=ROOT/'templates/anshun-colored/template-with-placeholders.docx'
MANIFEST=ROOT/'templates/anshun-colored/report.template.json'
NS='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
W=lambda x:f'{{{NS}}}{x}'
COLORS={'red':'计算数据','green':'表格内原文内容概要','yellow':'所有事件聚类','magenta':'数据现有字段下内容','lightGray':'事件原文概述','unmarked':'未着色表格动态项'}
FIELD_BY_BLOCK={17:'舆情调性、发布时间、是否预警、标题、摘要；负面预警表的事件分类仅供对照',26:'媒体环节、标题、摘要',29:'媒体级别、媒体属性、来源信息、标题、摘要',30:'全量表舆情调性、是否预警、标题、摘要；独立聚类与属地候选；817 行表仅供对照'}
SCOPE_BY_BLOCK={17:'全量记录；第一部分（一）重点预警事件另待确认',26:'全量记录',29:'央省级与重要媒体筛选记录',30:'舆情调性=负面 OR 已预警的去重行并集，经人工确认的事件组'}
slots=[]

def add_slot(slot_id,color,original,block,kind='highlight'):
    if block in (40,42,43,44,45):
        fields='本月确认事实、事件原文、补充的天气/活动/政策来源；外部资料须单独授权与核验'
        scope='本月风险研判与下一预测窗口'; method='人工核对每项事实、日期、预测条件和出处'
    elif kind=='chart':
        fields='已冻结指标及对应来源记录'; scope='相应图表统计范围'; method='图表数值逐项对照同一事实版本'
    elif kind=='table':
        fields='负面预警表标题、原文内容、热度规则（热度来源待确认）'; scope='人工确认并按已确认规则排序的 TOP10 事件'; method='核对来源行、事件成员与人工排序决定'
    else:
        fields=FIELD_BY_BLOCK.get(block,'报告月份、发布日期及已冻结事实')
        scope=SCOPE_BY_BLOCK.get(block,'报告月份或未来预测窗口')
        method='按来源行及事实版本复算；历史数值仅作源文证据'
    red_text=(color=='red' and bool(re.search(r'较去年同期|景区管理|游客体验',original)))
    uncertain=red_text or (color=='yellow' and block in (26,29) and '事件分类' not in fields)
    slot_type=('computed_judgement' if '较去年同期' in original else 'narrative_from_sources') if red_text else ('number' if color=='red' else 'source_text' if color in ('green','lightGray') else 'theme_cluster' if color=='yellow' else 'existing_field' if color=='magenta' else 'table_dynamic')
    display='百分数，保留百分号并复核分母' if '%' in original else ('整数条数' if color=='red' and original.isdigit() else '沿用源 Word 该位置的文字格式；单位按原句复核')
    slots.append({'id':slot_id,'color':color,'color_meaning':COLORS.get(color,'动态内容'),'slot_type':slot_type,'original_text':original,'source_block_index':block,'kind':kind,'semantic':f'{COLORS.get(color,"动态内容")}：{original[:70]}','source_fields_or_calculation':fields,'statistical_unit':'记录' if color in ('red','magenta') else '确认事件或来源原文','scope':scope,'time_window':'报告月份；预测文本另由人工指定未来窗口','missing_policy':'显示缺失并阻断对应正式事实，不沿用 2026 年 8 月历史值','display_format':display,'verification':method,'review_required':uncertain or color in ('green','yellow','lightGray'),'review_note':'源 Word 红色误标，已改为文字判断或主题概述槽位' if red_text else ('来源与业务语义需人工确认' if uncertain or color in ('green','yellow','lightGray') else '')})
    return '{{'+slot_id+'}}'

def set_run(r,value):
    for t in r.findall('.//'+W('t')): r.remove(t) if t.getparent() is r else t.getparent().remove(t)
    # Remove drawings and text-bearing descendants, keeping run properties.
    for child in list(r):
        if child.tag!=W('rPr'): r.remove(child)
    t=ET.SubElement(r,W('t')); t.text=value; t.set('{http://www.w3.org/XML/1998/namespace}space','preserve')

def paragraph_runs(p,block):
    runs=p.xpath('.//w:r',namespaces={'w':NS}); i=0; local=0
    while i<len(runs):
        r=runs[i]; hl=r.find(W('rPr')+'/'+W('highlight'))
        color=hl.get(W('val')) if hl is not None else None
        if color not in COLORS: i+=1; continue
        group=[r]; j=i+1
        while j<len(runs):
            next_hl=runs[j].find(W('rPr')+'/'+W('highlight'))
            if next_hl is None or next_hl.get(W('val'))!=color: break
            group.append(runs[j]); j+=1
        original=''.join(''.join(t.text or '' for t in x.findall('.//'+W('t'))) for x in group)
        if re.search(r'[\w\u4e00-\u9fff]',original):
            local+=1; slot_id=f'B{block}_{color.upper()}_{local:02}'
            set_run(group[0],add_slot(slot_id,color,original,block))
            for rest in group[1:]: set_run(rest,'')
        i=j

with zipfile.ZipFile(SOURCE) as zin:
    root=ET.fromstring(zin.read('word/document.xml'))
    body=root.find(W('body'))
    for bi,block in enumerate(list(body)):
        if block.tag==W('p'):
            if bi==26:
                for r in block.findall('.//'+W('r')):
                    for t in r.findall('.//'+W('t')):
                        if t.text=='“《经济日报》关注：': t.text='“'
            if bi==29:
                for t in block.findall('.//'+W('t')):
                    if t.text=='月份，央': t.text='月份，'
            if bi==30:
                for t in block.findall('.//'+W('t')):
                    if t.text=='（详见图4）。其中，安顺涉交': t.text='（详见图4）。其中，安顺涉'
            if bi in (40,42,43,44,45):
                original=''.join(t.text or '' for t in block.findall('.//'+W('t')))
                first=block.find('.//'+W('r'))
                if first is not None:
                    slot_id=f'B{bi}_NARRATIVE'; set_run(first,add_slot(slot_id,'lightGray',original,bi,'narrative'))
                    for r in block.findall('.//'+W('r')):
                        if r is not first: set_run(r,'')
            else:
                paragraph_runs(block,bi)
            if bi in (5,8,12):
                original=''.join(t.text or '' for t in block.findall('.//'+W('t')))
                first=block.find('.//'+W('r'))
                if first is not None:
                    slot_id=f'B{bi}_COVER'; set_run(first,add_slot(slot_id,'red',original,bi,'cover'))
                    for r in block.findall('.//'+W('r')):
                        if r is not first: set_run(r,'')
        elif block.tag==W('tbl'):
            rows=block.findall(W('tr'))
            for row_number,row in enumerate(rows[1:],1):
                cells=row.findall(W('tc'))
                for ci,col in ((1,'EVENT'),(2,'HEAT')):
                    if ci>=len(cells): continue
                    original=''.join(t.text or '' for t in cells[ci].findall('.//'+W('t')))
                    r=cells[ci].find('.//'+W('r'))
                    if r is None: continue
                    slot_id=f'TOP10_{row_number:02}_{col}'
                    set_run(r,add_slot(slot_id,'unmarked',original,bi,'table'))
                    for rest in cells[ci].findall('.//'+W('r')):
                        if rest is not r: set_run(rest,'')
        for drawing in block.findall('.//'+W('drawing')):
            parent=drawing.getparent(); idx=parent.index(drawing)
            slot_id=f'CHART_{len([s for s in slots if s["kind"]=="chart"])+1}'
            original='2026 年 8 月原图'
            parent.remove(drawing)
            text=ET.Element(W('t')); text.text=add_slot(slot_id,'red',original,bi,'chart'); parent.insert(idx,text)
    def refine(s):
        key=s['id']; base={'denominator':None,'calculation':None}
        if key=='B17_RED_01': base.update(semantic='境内全网涉安顺原始记录数，按万条显示',source_fields_or_calculation='全量表第 3 工作表去空标题后原始行数 / 10000',statistical_unit='原始记录',calculation='COUNT(全量记录)/10000')
        elif key in ('B17_RED_02','B17_RED_04','B17_RED_06'):
            sentiment={'B17_RED_02':'正面','B17_RED_04':'中性','B17_RED_06':'负面'}[key]
            base.update(semantic=f'{sentiment}原始记录数',source_fields_or_calculation=f'全量表舆情调性={sentiment} 的记录数',statistical_unit='原始记录',calculation=f'COUNTIF(舆情调性,{sentiment})')
        elif key in ('B17_RED_03','B17_RED_05','B17_RED_07'):
            sentiment={'B17_RED_03':'正面','B17_RED_05':'中性','B17_RED_07':'负面'}[key]
            base.update(semantic=f'{sentiment}原始记录占比',source_fields_or_calculation=f'{sentiment}原始记录数 / 全量原始记录数 × 100',statistical_unit='原始记录',denominator='全量原始记录数',calculation=f'COUNTIF(舆情调性,{sentiment}) / COUNT(全量记录) × 100')
        elif key=='B17_RED_08': base.update(semantic='本月信息量峰值日期',source_fields_or_calculation='全量表发布时间按自然日分组计数，取最大日；并列规则待确认',statistical_unit='原始记录/自然日',calculation='argmax(每日原始记录数)')
        elif key=='B17_RED_10': base.update(semantic='负面单一重点预警去重事件数',source_fields_or_calculation='源报告第一部分（一）称“负面单一重点预警数据”；负面与预警是否取交集、是否另有敏感范围须业务确认，确认范围后两轮事件候选及人工归并',statistical_unit='人工确认事件组',calculation='COUNT(按该槽位确认范围的事件组)')
        elif key=='B30_RED_01': base.update(semantic='敏感及负面舆情已去重事件数',source_fields_or_calculation='用户确认：全量行中舆情调性=负面 OR 是否预警=已预警，行并集去重；再经两轮候选和人工归并形成事件组',statistical_unit='人工确认事件组',calculation='COUNT(并集范围内确认事件组)')
        elif key=='B17_RED_11': base.update(semantic='重点预警已确认事件数占全量原始记录比例',source_fields_or_calculation='本槽位确认的重点预警事件组数 / 全量原始记录数 × 100；混合统计单位沿用原报告口径，待业务确认',statistical_unit='确认事件组 / 原始记录',denominator='全量原始记录数',calculation='COUNT(本槽位确认事件组) / COUNT(全量记录) × 100')
        elif key=='B17_GREEN_09': base.update(semantic='峰值日代表事件的来源概要',source_fields_or_calculation='峰值日记录的标题、摘要、来源；按业务确认的代表材料规则选取',statistical_unit='原始报道及已确认事件',calculation='人工选择后有来源的摘要')
        elif key=='B17_YELLOW_12': base.update(semantic='第一部分（一）重点预警事件的主要聚类主题',source_fields_or_calculation='对应槽位的确认事件范围 + cluster_event_themes 候选 + 人工确认类别；全量表事件分类原字段为空',statistical_unit='人工确认事件组',calculation='按确认事件组计数排序后取主要主题')
        elif key.startswith('B26_RED_') and key!='B26_RED_01':
            number=int(key.rsplit('_',1)[1]); order=['移动客户端','微信公众号','网站','微博','视频','纸媒','电视']
            idx=(number-4)//3
            if 0<=idx<len(order):
                platform=order[idx]; is_ratio=(number-4)%3==1
                base.update(semantic=f'{platform}原始记录'+('占比' if is_ratio else '数'),source_fields_or_calculation=f'全量表媒体环节={platform} 的记录数'+(' / 全量记录数 × 100' if is_ratio else ''),statistical_unit='原始记录',denominator='全量原始记录数' if is_ratio else None,calculation=f'COUNTIF(媒体环节,{platform})'+(' / COUNT(全量记录) × 100' if is_ratio else ''))
        elif key=='B30_RED_02': base.update(semantic='负面重点预警事件同比变化的文字判断',source_fields_or_calculation='本月与去年同月同口径确认事件数比较；缺去年同期数据时不得生成下降/上升判断',statistical_unit='确认事件组',calculation='同比差值与方向；缺数据时待审')
        elif key=='B30_RED_04': base.update(semantic='文化旅游类敏感及负面确认事件占比',source_fields_or_calculation='负面 OR 已预警行并集归并后，文化旅游类确认事件组数 / 该范围全部确认事件组数 × 100',statistical_unit='确认事件组',denominator='并集范围全部确认事件组数',calculation='COUNT(并集文化旅游确认事件) / COUNT(并集全部确认事件) × 100')
        elif key=='B30_RED_05': base.update(semantic='文化旅游类突出问题概述',source_fields_or_calculation='文化旅游类确认事件的标题、摘要、原文及人工研判',statistical_unit='确认事件与来源原文',calculation='有来源文字概述，不按数字计算')
        elif key.startswith('B30_RED_'):
            num=int(key.rsplit('_',1)[1]); districts=['市区','西秀区','黄果树旅游区','关岭县','平坝区','紫云县','普定县','镇宁县','安顺经开区']
            idx=(num-7)//2
            if 0<=idx<len(districts):
                district=districts[idx]; ratio=(num-7)%2==1
                base.update(semantic=f'{district}敏感及负面确认事件'+('占比' if ratio else '数'),source_fields_or_calculation=f'负面 OR 已预警行并集归并后属地={district} 的确认事件组数'+(' / 并集全部确认事件组数 × 100' if ratio else ''),statistical_unit='确认事件组',denominator='并集全部确认事件组数' if ratio else None,calculation=f'COUNT(并集属地={district} 的确认事件组)'+(' / COUNT(并集全部确认事件组) × 100' if ratio else ''))
        elif key.startswith('TOP10_'):
            rank=int(key.split('_')[1]); col=key.split('_')[-1]
            base.update(semantic=f'TOP10 第 {rank} 位'+('代表事件标题' if col=='EVENT' else '热度标识'),source_fields_or_calculation='负面 OR 已预警行并集的确认事件组，成员来源标题；排序与热度规则待业务确认',statistical_unit='确认事件组',calculation='按已确认排序规则取第 '+str(rank)+' 位')
        elif key.startswith('CHART_'):
            chart={'CHART_1':'舆情调性分布','CHART_2':'每日信息量','CHART_3':'媒体环节分布','CHART_4':'负面事件类别分布','CHART_5':'确认事件属地分布'}[key]
            base.update(semantic=chart+'图',source_fields_or_calculation='同一事实版本中的对应指标与来源行',statistical_unit='原始记录' if key in ('CHART_1','CHART_2','CHART_3') else '确认事件组',calculation='与对应正文统计保持一致')
        elif key.startswith(('B17_YELLOW','B26_YELLOW','B29_YELLOW','B30_YELLOW')):
            base.update(semantic='事件聚类主题候选及确认名称',source_fields_or_calculation='cluster_event_themes 候选、成员原文与人工确认；原始事件分类字段为空',statistical_unit='确认事件组或来源记录',calculation='按确认主题与对应成员生成文字')
        elif key.startswith('B26_MAGENTA'): base.update(semantic='媒体环节现有字段的名称或列表',source_fields_or_calculation='全量表媒体环节字段；列表项和顺序按本期记录核对',statistical_unit='原始记录',calculation='去重、排序并人工确认展示项')
        elif key.startswith('B29_MAGENTA'): base.update(semantic='媒体级别或来源媒体名称',source_fields_or_calculation='全量表媒体级别、媒体属性、来源信息；央省媒体名单需来源核验',statistical_unit='来源媒体/记录',calculation='按已确认媒体级别及名单筛选')
        elif key.startswith(('B26_LIGHTGRAY','B29_LIGHTGRAY')): base.update(semantic='本月代表事件原文概述',source_fields_or_calculation='选中来源记录的标题、摘要、原文、网址及人工确认事件成员',statistical_unit='来源原文/确认事件',calculation='有来源摘要，不承袭 8 月案例')
        s.update(base)
        return s
    slots[:]=[refine(s) for s in slots]
    definitions=[]
    head=ET.Element(W('p')); r=ET.SubElement(head,W('r')); ET.SubElement(r,W('t')).text='占位符定义与核验口径（先阅读，再使用后续模板）'; definitions.append(head)
    intro=ET.Element(W('p')); r=ET.SubElement(intro,W('r')); ET.SubElement(r,W('t')).text='来源：2026 年 8 月安顺市网络舆情分析报告。历史数字、事件和预测文字均为源文证据，不能作为本期默认值。红=计算数据；绿=表格内原文内容概要；黄=所有事件聚类；粉紫=数据现有字段下内容；灰=事件原文概述。'; definitions.append(intro)
    for slot in slots:
        p=ET.Element(W('p')); r=ET.SubElement(p,W('r')); t=ET.SubElement(r,W('t'))
        t.text=f"{{{{{slot['id']}}}}} 类型：{slot['slot_type']}；语义：{slot['semantic']}；来源：{slot['source_fields_or_calculation']}；计算：{slot['calculation'] or '按原文及人工核验'}；分母：{slot['denominator'] or '不适用'}；统计对象：{slot['statistical_unit']}；范围：{slot['scope']}；时间：{slot['time_window']}；缺失：{slot['missing_policy']}；格式：{slot['display_format']}；核验：{slot['verification']}。"+((' 待审：'+slot['review_note']) if slot['review_required'] else '')
        definitions.append(p)
    for i,p in enumerate(definitions): body.insert(i,p)
    xml=ET.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
    with zipfile.ZipFile(TARGET,'w') as zout:
        for item in zin.infolist(): zout.writestr(item,xml if item.filename=='word/document.xml' else zin.read(item.filename))
manifest={'template_id':'anshun-monthly-colored','name':'安顺月报 · 五色逐项占位模板','status':'candidate_requires_review','source_file':SOURCE.name,'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'template_file':TARGET.name,'template_sha256':hashlib.sha256(TARGET.read_bytes()).hexdigest(),'color_mapping':COLORS,'placeholders':slots,'recommendations_max':5,'scope_requirements':{'B17_sentiment_peak':'全量原始记录','B17_negative_warning':'重点预警去重事件，负面与预警交集定义待业务确认','B26_platform':'全量原始记录','B29_media':'按媒体级别与来源筛选的原始记录','B30_categories_districts_top10':'用户确认：舆情调性=负面 OR 已预警的原始行并集，同一行只计一次；其上人工确认事件组','risk_and_recommendations':'已确认事实与单独核验的未来窗口证据'},'review_items':['正文绿色峰值事件示例的标色已由用户确认；TOP10 表格原本未标绿，现按未着色动态表格项处理','红色的同比判断与景区管理、游客体验等文字为源文误标，已改为文字槽位','8 月源报告数字无法用 10 月工作簿直接核验','10 月全量表事件分类整列为空；独立聚类工具产候选，817 行测试表仅供对照','第一部分（四）并集范围已确认；第一部分（一）重点预警槽位仍需单独规则，两个历史 272 数字不得强行等同','旧图表已替换为图表占位符，正式图表需同一事实版本重绘']}
MANIFEST.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'templates/anshun-colored/migration-manifest.json').write_text(json.dumps({'source_file':SOURCE.name,'source_sha256':manifest['source_sha256'],'output_file':TARGET.name,'output_sha256':manifest['template_sha256'],'transformations':['逐项占位符定义前置','动态高亮内容改为具名占位符','误标红色文字改为文字槽位','五张历史图像改为图表槽位','TOP10 保留原表格结构并替换事件/热度单元格'],'review_items':manifest['review_items']},ensure_ascii=False,indent=2),encoding='utf-8')
properties={s['id']:{'type':'number' if s['slot_type']=='number' and s['original_text'].replace('.','',1).isdigit() else 'string','description':s['semantic']} for s in slots}
(ROOT/'templates/anshun-colored/report-values.schema.json').write_text(json.dumps({'$schema':'https://json-schema.org/draft/2020-12/schema','title':'安顺月报五色模板逐项值','type':'object','properties':properties,'required':list(properties),'additionalProperties':False},ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'templates/anshun-colored/layout.json').write_text(json.dumps({'source_docx':SOURCE.name,'template_docx':TARGET.name,'preserve_original_styles':True,'editable_top10_table':True,'chart_slots':['CHART_1','CHART_2','CHART_3','CHART_4','CHART_5'],'visual_qa':'pending_renderer'},ensure_ascii=False,indent=2),encoding='utf-8')
print('slots',len(slots),'review',sum(s['review_required'] for s in slots),'source',manifest['source_sha256'])
