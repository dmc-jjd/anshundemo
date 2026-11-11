"""图表呈现契约：图表族/样式枚举/实例投影与原图提取。客户实例数据一律取自 registry。"""
from __future__ import annotations

import hashlib,zipfile,posixpath
from pathlib import Path
from typing import Literal
from pydantic import BaseModel,ConfigDict
from lxml import etree as ET

from core.charts import registry

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

def definitions(template,data_root:Path):
    if template.get('charts'):return template['charts']
    path=Path(template['layout_source'])
    if not path.exists() and (data_root/'uploads'/path.name).exists():path=data_root/'uploads'/path.name
    with zipfile.ZipFile(path) as z:
        drawings=ET.fromstring(z.read('word/document.xml')).xpath('//*[local-name()="drawing"]')
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
