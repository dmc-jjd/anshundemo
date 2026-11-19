"""图表呈现契约：图表族/样式枚举/实例投影与原图提取。客户实例数据一律取自 registry。"""
from __future__ import annotations

import hashlib,zipfile
from pathlib import Path
from typing import Literal
from pydantic import BaseModel,ConfigDict
from lxml import etree as ET

from core.charts import registry
from core.tools.doc97 import is_legacy_doc

STYLE_NAMES={'pie':'饼图','line':'折线图','bar':'纵向柱状图','barh':'横向条形图'}
STYLE_BASIS_TEMPLATE='用户确认的月报图形规则，可在模板审核时更换'
STYLE_BASIS_HUMAN='人工选择'
DEFINITION_KEYS=('id','drawing_index','title','style','style_basis','scope','unit')

DEFAULT_DRAWING_IDS=('sentiment','daily','platform','theme','locality')
FAMILY_STYLES={
    'sentiment':('pie','bar','barh'),
    'daily':('line','bar'),
    'platform':('pie','bar','barh'),
    'theme':('pie','bar','barh'),
    'locality':('pie','bar','barh'),
    'source':('pie','bar','barh'),
}

# Existing client packages historically stored the style name (pie/line/bar/barh)
# in `family`. New instances may set `family` to the chart kind so two platform
# (or daily) drawings can share palette/axis rules under different ids.
DEFAULT_BINDINGS={
    'sentiment':{'source':'metrics.sentiment'},
    'daily':{'source':'metrics.daily_count'},
    'platform':{'source':'metrics.platform'},
    'theme':{'source':'theme_clusters.groups'},
    'locality':{'source':'locality.items'},
    'source':{'source':'metrics.source'},
}

def family_of(chart):
    kind=str(chart.get('id') or '')
    raw=str(chart.get('family') or '')
    if raw in FAMILY_STYLES:
        return raw
    if raw in STYLE_NAMES:
        if kind in FAMILY_STYLES:
            return kind
        for name in FAMILY_STYLES:
            if kind==name or kind.startswith(name+'_'):
                return name
        return kind or raw
    if kind in FAMILY_STYLES:
        return kind
    for name in FAMILY_STYLES:
        if kind==name or kind.startswith(name+'_'):
            return name
    return raw or kind


def chart_title(chart):
    return chart.get('final_title') or chart.get('title') or chart.get('draft_title') or ''

def resolve_chart(kind,template=None,package=None):
    """Merge package registry defaults with a confirmed-template instance."""
    pack={item['id']:dict(item) for item in registry.charts(package)}
    inst={}
    for item in (template or {}).get('charts') or []:
        if item.get('id')==kind:
            inst=dict(item)
            break
    if kind not in pack and not inst:
        raise ValueError('unknown_chart_type')
    merged={**pack.get(kind,{}),**inst}
    merged['id']=kind
    if not merged.get('family'):
        merged['family']=family_of(merged)
    if not (merged.get('binding') or {}).get('source'):
        family=family_of(merged)
        for item in pack.values():
            if family_of(item)==family and (item.get('binding') or {}).get('source'):
                merged['binding']=item['binding']
                break
        else:
            if family in DEFAULT_BINDINGS:
                merged['binding']=dict(DEFAULT_BINDINGS[family])
    return merged

def declared_ids(template=None,package=None):
    ids=[]
    seen=set()
    for item in list(registry.charts(package))+list((template or {}).get('charts') or []):
        key=item.get('id')
        if key and key not in seen:
            seen.add(key)
            ids.append(key)
    return ids

def ordered_template_charts(template):
    """Charts from a confirmed or package template, in drawing order."""
    declared=list((template or {}).get('charts') or [])
    if not declared:
        return []
    decorated=[]
    for index,item in enumerate(declared):
        order=item.get('drawing_index')
        decorated.append((int(order) if order else index+1,index,dict(item)))
    decorated.sort()
    result=[]
    for order,_,item in decorated:
        item.setdefault('drawing_index',order)
        result.append(item)
    return result

def declared_charts(template=None,package=None):
    """包或确认模板里声明的图表，按 drawing_index（缺省为列表序）排列。无声明则空。"""
    if template and template.get('charts'):
        return ordered_template_charts(template)
    try:
        from core.packages import load_package
        return ordered_template_charts(load_package(package).template)
    except Exception:
        return []

def chart_slots(template=None,package=None):
    return {f"CHART_{item['drawing_index']}":item['id'] for item in declared_charts(template,package) if item.get('id')}

def display_titles(template=None,package=None):
    """终稿展示标题：包 export.chart_titles 优先，否则「图n + 包内 title」。"""
    titles={}
    try:
        from core.packages import load_package
        cfg=dict((load_package(package).template or {}).get('export') or {})
        titles={str(k):str(v) for k,v in (cfg.get('chart_titles') or {}).items()}
    except Exception:
        titles={}
    result={}
    for item in declared_charts(template,package):
        key=item.get('id')
        if not key: continue
        if key in titles:
            result[key]=titles[key]
        else:
            result[key]=f"图{item.get('drawing_index') or ''} {item.get('title') or key}".strip()
    return result

def drawing_ids(template,data_root:Path|None=None):
    """Map 1-based drawing_index to chart instance id.

    Declared template charts win. Otherwise use the package registry
    (same order the writer uses), then the built-in default drawing list.
    """
    declared=ordered_template_charts(template)
    if declared:
        return {int(item['drawing_index']):item['id'] for item in declared if item.get('id')}
    root=data_root
    if root is None:
        try:
            from core import paths
            root=paths.data_root()
        except Exception:
            root=None
    if template and root is not None:
        try:
            generated=definitions(template,root)
        except Exception:
            generated=[]
        if generated:
            return {int(item['drawing_index']):item['id'] for item in generated}
    ids=list(registry.ids())
    if not ids:
        return {}
    return {index+1:name for index,name in enumerate(ids)}

def allowed_styles(chart):
    family=family_of(chart)
    return FAMILY_STYLES.get(family,('pie','line','bar','barh'))


class ChartStyles(BaseModel):
    # 与 S2 的 core/tools/registry.BASE_ARGUMENTS 同口径：这 5 个 id 是基座枚举，具体实例数据在客户包
    model_config=ConfigDict(extra='forbid')
    sentiment:Literal['pie','bar','barh']='pie'
    daily:Literal['line','bar']='line'
    platform:Literal['pie','bar','barh']='pie'
    theme:Literal['pie','bar','barh']='bar'
    locality:Literal['pie','bar','barh']='barh'

def _layout_path(template,data_root:Path)->Path:
    """版式源文件：优先工件里的路径，找不到才回落到当前项目的 uploads（换项目后仍能解析）。"""
    path=Path(template['layout_source'])
    if not path.exists() and (data_root/'uploads'/path.name).exists():path=data_root/'uploads'/path.name
    return path

def layout_available(template,data_root:Path)->bool:
    """基准报告能否给出版式图信息：只有可读的 OOXML ZIP 能。

    `.doc` 的图形是 OLE2 里的 EMF 对象、坏 ZIP 没有 `word/document.xml`——两者都给不出
    「图形数量」，故一律按版式不可用处理。这是给调用方的显式判据，不是异常探测。
    `charts` 已就绪的旧工件可能没有 `layout_source`：那种情况同样没有版式可用，不抛错。
    """
    if not template.get('layout_source'):return False
    path=_layout_path(template,data_root)
    return not is_legacy_doc(path) and zipfile.is_zipfile(path)

def is_chart_drawing(drawing)->bool:
    """Word 统计图（带 ``c:chart``），不是封面图或文本框。"""
    return bool(drawing.xpath('.//*[local-name()="chart"]'))


def chart_slot_drawings(root):
    """渲染/编号用的图形槽：版式里有统计图时只收统计图，否则退回全部 ``w:drawing``（图片占位夹具）。"""
    drawings=list(root.xpath('//*[local-name()="drawing"]'))
    charts=[item for item in drawings if is_chart_drawing(item)]
    return charts if charts else drawings


def _drawing_extent(drawing, attr):
    extent=drawing.xpath('.//*[local-name()="extent"]')
    if not extent:
        return 0
    try:
        return int(extent[0].get(attr) or 0)
    except (TypeError, ValueError):
        return 0


def source_chart_drawings(root):
    """历史报告原图对照用的图表槽。

    有 Word 统计图时只收统计图，封面图和文本框不占位。没有统计图、只有嵌入图片时，
    去掉没有图片的文本框，并丢掉明显高于其它图的整页封面，避免图 1 对上封面。
    安顺这类五张接近的图片夹具保持原样，五张都会留下。
    """
    slots=chart_slot_drawings(root)
    if any(is_chart_drawing(item) for item in slots):
        return slots
    # Legacy .doc-to-.docx exports use VML pict/imagedata rather than drawing/blip.
    # Keep document order across both structures; skip AlternateContent fallbacks
    # when the same container already has a modern drawing.
    candidates=root.xpath('//*[local-name()="drawing" or local-name()="pict"]')
    pictures=[]
    for item in candidates:
        if item.xpath('ancestor::*[local-name()="drawing" or local-name()="pict"]'):
            continue
        if item.tag.split('}')[-1]=='pict':
            alternatives=item.xpath('ancestor::*[local-name()="AlternateContent"]')
            if any(parent.xpath('.//*[local-name()="drawing"]') for parent in alternatives):
                continue
        if item.xpath('.//*[local-name()="blip" or local-name()="imagedata"][@r:embed or @r:id]',namespaces={'r':_R}):
            pictures.append(item)
    if len(pictures)<=1:
        return pictures or slots
    heights=[_drawing_extent(item,'cy') for item in pictures]
    median=sorted(heights)[len(heights)//2]
    kept=[item for item,height in zip(pictures,heights)
          if not (height>=8_000_000 and height>=2*max(median,1))]
    return kept or pictures


_A='http://schemas.openxmlformats.org/drawingml/2006/main'
_PIC='http://schemas.openxmlformats.org/drawingml/2006/picture'
_R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
_PIC_URI=_PIC


def resize_drawing_image(drawing, pixel_width, pixel_height):
    """Preserve image width and intrinsic aspect for both DrawingML and legacy VML."""
    import re
    ratio=pixel_height/pixel_width
    for extent in drawing.xpath('.//*[local-name()="extent" or local-name()="ext"]'):
        if extent.get('cx') and extent.get('cy'):
            extent.set('cy',str(round(int(extent.get('cx'))*ratio)))
    for shape in drawing.xpath('.//*[local-name()="shape"][.//*[local-name()="imagedata"]]'):
        style=shape.get('style','')
        width=re.search(r'(?:^|;)\s*width\s*:\s*([\d.]+)(pt|in|cm|mm|px)\s*(?:;|$)',style)
        if not width:raise ValueError('chart_vml_width_missing')
        height=f'height:{float(width[1])*ratio:g}{width[2]}'
        if re.search(r'(?:^|;)\s*height\s*:',style):
            style=re.sub(r'(^|;)\s*height\s*:[^;]*',lambda m:m[1]+height,style)
        else:style=style.rstrip(';')+';'+height
        shape.set('style',style)
    for crop in drawing.xpath('.//*[local-name()="srcRect"]'):
        for edge in ('l','t','r','b'):crop.set(edge,'0')
    for image in drawing.xpath('.//*[local-name()="imagedata"]'):
        for edge in ('cropleft','croptop','cropright','cropbottom'):
            image.attrib.pop(edge,None)


def bind_drawing_image(drawing, rid:str)->None:
    """把一张 PNG 绑到图形槽：已有 blip 的改引用；Word 统计图则改成图片，保留位置和尺寸。"""
    ET.register_namespace('a', _A)
    ET.register_namespace('pic', _PIC)
    ET.register_namespace('r', _R)
    rel=f'{{{_R}}}embed'
    legacy=drawing.xpath('.//*[local-name()="imagedata"]')
    if legacy:
        for item in legacy:item.set(f'{{{_R}}}id',rid)
        return
    blips=drawing.xpath('.//*[local-name()="blip"]')
    if blips:
        for blip in blips:
            blip.set(rel, rid)
        return
    graphic=drawing.xpath('.//*[local-name()="graphic"]')
    if not graphic:
        return
    data=graphic[0].xpath('./*[local-name()="graphicData"]')
    if not data:
        data=[ET.SubElement(graphic[0], f'{{{_A}}}graphicData')]
    graphic_data=data[0]
    for child in list(graphic_data):
        graphic_data.remove(child)
    graphic_data.set('uri', _PIC_URI)
    docPr=drawing.xpath('.//*[local-name()="docPr"]')
    name=(docPr[0].get('name') if docPr else '') or 'Chart'
    nid=(docPr[0].get('id') if docPr else '') or '1'
    extent=drawing.xpath('.//*[local-name()="extent"]')
    cx=(extent[0].get('cx') if extent else '') or '5486400'
    cy=(extent[0].get('cy') if extent else '') or '3200400'
    pic=ET.SubElement(graphic_data, f'{{{_PIC}}}pic')
    nv=ET.SubElement(pic, f'{{{_PIC}}}nvPicPr')
    ET.SubElement(nv, f'{{{_PIC}}}cNvPr', id=str(nid), name=name)
    ET.SubElement(nv, f'{{{_PIC}}}cNvPicPr')
    fill=ET.SubElement(pic, f'{{{_PIC}}}blipFill')
    blip=ET.SubElement(fill, f'{{{_A}}}blip')
    blip.set(rel, rid)
    stretch=ET.SubElement(fill, f'{{{_A}}}stretch')
    ET.SubElement(stretch, f'{{{_A}}}fillRect')
    spPr=ET.SubElement(pic, f'{{{_PIC}}}spPr')
    xfrm=ET.SubElement(spPr, f'{{{_A}}}xfrm')
    ET.SubElement(xfrm, f'{{{_A}}}off', x='0', y='0')
    ET.SubElement(xfrm, f'{{{_A}}}ext', cx=cx, cy=cy)
    geom=ET.SubElement(spPr, f'{{{_A}}}prstGeom', prst='rect')
    ET.SubElement(geom, f'{{{_A}}}avLst')


def _drawings(path:Path):
    """版式 docx 里用于给图表编号的 `<w:drawing>` 列表。

    有真正的 Word 统计图时，封面图和文本框不占 ``drawing_index``；没有统计图时
    （测试夹具用图片占位）仍按全部图形编号。`drawing_index` 的语义是「第 N 个图表槽」。

    `.doc` 走不了 zipfile：整个 definition 的主体（块/字段/图表实例）都不依赖版式，
    只有**图形数量**依赖它，所以这里按「版式不可用」降级为空，而不是让 `BadZipFile`
    冒到路由层变成 500。坏 ZIP 则显式报 `template_layout_unavailable`——它是真错误，
    不能被静默当成 0 张图。
    """
    if is_legacy_doc(path):return []
    if not zipfile.is_zipfile(path):
        raise ValueError(f'template_layout_unavailable: 模板的基准报告不是可读的 .docx（OOXML ZIP）：{path.name}')
    with zipfile.ZipFile(path) as z:
        return chart_slot_drawings(ET.fromstring(z.read('word/document.xml')))

def definitions(template,data_root:Path):
    if template.get('charts'):return template['charts']
    drawings=_drawings(_layout_path(template,data_root))
    # 版式读得出图形槽时，仍按槽数截取（测试夹具和有图 docx 的既有行为）。
    # 版式给不出槽（.doc 或 0 个 drawing）时不截成空清单，改用包内登记的全部图表，
    # 由系统按数据重画；具体客户名不进这段逻辑。
    items=registry.charts()
    if drawings:
        items=items[:len(drawings)]
    # 逐键显式赋值：键集必须仍是这 7 个（用 **item 会把 draft_title 等带进模板工件，改其哈希）
    return [{'id':item['id'],'drawing_index':i+1,'title':item['title'],'style':item['style'],
             'style_basis':STYLE_BASIS_TEMPLATE,'scope':item['scope'],'unit':item['unit']}
            for i,item in enumerate(items)]

def styles_for(template,overrides=None,*,data_root:Path):
    if template and template.get('charts'):
        items=list(template.get('charts') or ())
    else:
        items=list(definitions(template,data_root))
    declared={c['id']:c for c in items if c.get('id')}
    defaults=ChartStyles().model_dump()
    values={}
    for key,item in declared.items():
        values[key]=item.get('style') or defaults.get(key) or (allowed_styles(item) or ['pie'])[0]
    for key,style in (overrides or {}).items():
        if key not in declared:
            raise ValueError('unknown_chart_style:'+str(key))
        values[key]=style
    # Validate built-in families with the existing model (rejects e.g. daily=pie).
    classic={key:value for key,value in values.items() if key in ChartStyles.model_fields}
    ChartStyles.model_validate(classic)
    for key,style in values.items():
        if key in ChartStyles.model_fields:
            continue
        chart=declared.get(key) or {'id':key}
        if style not in allowed_styles(chart):
            raise ValueError('unsupported_chart_style:'+str(key))
    return values

def with_styles(template,styles,*,data_root:Path):
    import copy
    result=copy.deepcopy(template)
    chosen=styles_for(template,styles,data_root=data_root)
    result['charts']=[{**c,'style':chosen[c['id']],'style_basis':STYLE_BASIS_HUMAN} for c in definitions(template,data_root)]
    return result

def source_image(template,kind,source_index=0,*,data_root:Path):
    charts=list(ordered_template_charts(template))
    if not charts and template and template.get('layout_source'):
        charts=list(definitions(template,data_root))
    if not charts:
        charts=[{'id':name,'drawing_index':index} for index,name in enumerate(registry.ids(),1)]
    item=next((entry for entry in charts if entry['id']==kind),None)
    if item is None:raise ValueError('unknown_chart')
    try:
        slot=int(item.get('drawing_index') or 0)
    except (TypeError,ValueError):
        slot=0
    if slot<=0:
        slot=next(index for index,entry in enumerate(charts,1) if entry['id']==kind)
    source=template['source_reports'][source_index];path=Path(source['path'])
    if not path.exists() and (data_root/'uploads'/path.name).exists():path=data_root/'uploads'/path.name
    # `.doc` 的图形是 OLE2 里的 EMF 对象，不是 ZIP 内的 media 条目——本函数不做 OLE2 图片提取，
    # 提前按「不可预览」拒绝，而不是让 zipfile 抛 BadZipFile 变成 500。
    if is_legacy_doc(path):raise ValueError('source_chart_unavailable')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=source['sha256']:raise ValueError('template_source_changed')
    from core.charts.source_preview import preview_source_drawing
    with zipfile.ZipFile(path) as z:
        drawings=source_chart_drawings(ET.fromstring(z.read('word/document.xml')))
        try:
            drawing=drawings[slot-1]
        except IndexError as exc:
            raise ValueError('source_chart_unavailable') from exc
        return preview_source_drawing(z,drawing)

