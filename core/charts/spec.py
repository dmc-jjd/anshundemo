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
    values={**{c['id']:c['style'] for c in registry.charts()},
            **{c['id']:c['style'] for c in definitions(template,data_root)},
            **(overrides or {})}
    return ChartStyles.model_validate(values).model_dump()

def with_styles(template,styles,*,data_root:Path):
    import copy
    result=copy.deepcopy(template)
    chosen=ChartStyles.model_validate({**styles_for(template,data_root=data_root),**styles}).model_dump()
    result['charts']=[{**c,'style':chosen[c['id']],'style_basis':STYLE_BASIS_HUMAN} for c in definitions(template,data_root)]
    return result

def source_image(template,kind,source_index=0,*,data_root:Path):
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
