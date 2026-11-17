"""图表呈现契约：图表族/样式枚举/实例投影与原图提取。客户实例数据一律取自 registry。"""
from __future__ import annotations

import hashlib,zipfile,posixpath
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
    ids=registry.ids() or list(DEFAULT_DRAWING_IDS)
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

def _drawings(path:Path):
    """版式 docx 里的 `<w:drawing>` 列表；`drawing_index` 的语义就是「模板里的第 N 个图形」。

    `.doc` 走不了 zipfile：整个 definition 的主体（块/字段/图表实例）都不依赖版式，
    只有**图形数量**依赖它，所以这里按「版式不可用」降级为空，而不是让 `BadZipFile`
    冒到路由层变成 500。坏 ZIP 则显式报 `template_layout_unavailable`——它是真错误，
    不能被静默当成 0 张图。
    """
    if is_legacy_doc(path):return []
    if not zipfile.is_zipfile(path):
        raise ValueError(f'template_layout_unavailable: 模板的基准报告不是可读的 .docx（OOXML ZIP）：{path.name}')
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read('word/document.xml')).xpath('//*[local-name()="drawing"]')

def definitions(template,data_root:Path):
    if template.get('charts'):return template['charts']
    drawings=_drawings(_layout_path(template,data_root))
    # 逐键显式赋值：键集必须仍是这 7 个（用 **item 会把 draft_title 等带进模板工件，改其哈希）
    return [{'id':item['id'],'drawing_index':i+1,'title':item['title'],'style':item['style'],
             'style_basis':STYLE_BASIS_TEMPLATE,'scope':item['scope'],'unit':item['unit']}
            for i,item in enumerate(registry.charts()[:len(drawings)])]

def styles_for(template,overrides=None,*,data_root:Path):
    declared={c['id']:c for c in registry.charts()}
    for item in definitions(template,data_root):
        declared[item['id']]=item
    values={**{key:ChartStyles().model_dump()[key] for key in ChartStyles.model_fields},
            **{key:item['style'] for key,item in declared.items()}}
    for key,style in (overrides or {}).items():
        if key not in declared and key not in ChartStyles.model_fields:
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
    kinds=[item['id'] for item in ordered_template_charts(template)]
    if not kinds and template and template.get('layout_source'):
        kinds=[item['id'] for item in definitions(template,data_root)]
    if not kinds:
        kinds=registry.ids()
    if kind not in kinds:raise ValueError('unknown_chart')
    source=template['source_reports'][source_index];path=Path(source['path'])
    if not path.exists() and (data_root/'uploads'/path.name).exists():path=data_root/'uploads'/path.name
    # `.doc` 的图形是 OLE2 里的 EMF 对象，不是 ZIP 内的 media 条目——本函数不做 OLE2 图片提取，
    # 提前按「不可预览」拒绝，而不是让 zipfile 抛 BadZipFile 变成 500。
    if is_legacy_doc(path):raise ValueError('source_chart_unavailable')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=source['sha256']:raise ValueError('template_source_changed')
    with zipfile.ZipFile(path) as z:
        drawings=ET.fromstring(z.read('word/document.xml')).xpath('//*[local-name()="drawing"]')
        drawing=drawings[kinds.index(kind)];blip=drawing.xpath('.//*[local-name()="blip"]')[0]
        rid=blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
        rels=ET.fromstring(z.read('word/_rels/document.xml.rels'))
        rel=next(r for r in rels if r.get('Id')==rid and r.get('TargetMode')!='External')
        target=rel.get('Target','');name=target.lstrip('/') if target.startswith('/') else posixpath.normpath('word/'+target)
        if not name.startswith('word/media/'):raise ValueError('not_embedded_chart_image')
        data=z.read(name)
    mime='image/png' if data.startswith(b'\x89PNG') else 'image/jpeg' if data.startswith(b'\xff\xd8') else None
    if not mime:
        # Historical Word reports contain EMF, which browsers cannot display.
        # Pillow uses Windows GDI to rasterize it without altering the document.
        import io
        from PIL import Image
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format=='WMF':image.load(dpi=160)
                out=io.BytesIO();image.convert('RGB').save(out,format='PNG');data=out.getvalue()
            mime='image/png'
        except (OSError,ValueError) as exc:raise ValueError('source_image_format_not_previewable') from exc
    return data,mime
