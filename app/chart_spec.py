"""Chart presentation contracts, separate from frozen statistical facts."""
import hashlib,zipfile,posixpath
from pathlib import Path
from typing import Literal
from pydantic import BaseModel,ConfigDict
from lxml import etree as ET
from .config import DATA

KINDS=['sentiment','daily','platform','theme','locality']
DEFAULTS=dict(zip(KINDS,['pie','line','pie','bar','barh']))
TITLES=dict(zip(KINDS,['舆情调性分布','每日信息量','传播平台分布','事件分类','事件涉及属地']))
STYLE_NAMES={'pie':'饼图','line':'折线图','bar':'纵向柱状图','barh':'横向条形图'}

class ChartStyles(BaseModel):
    model_config=ConfigDict(extra='forbid')
    sentiment:Literal['pie','bar','barh']='pie'
    daily:Literal['line','bar']='line'
    platform:Literal['pie','bar','barh']='pie'
    theme:Literal['pie','bar','barh']='bar'
    locality:Literal['pie','bar','barh']='barh'

def definitions(template):
    if template.get('charts'):return template['charts']
    path=Path(template['layout_source'])
    if not path.exists() and (DATA/'uploads'/path.name).exists():path=DATA/'uploads'/path.name
    with zipfile.ZipFile(path) as z:
        drawings=ET.fromstring(z.read('word/document.xml')).xpath('//*[local-name()="drawing"]')
    return [{'id':kind,'drawing_index':i+1,'title':TITLES[kind],'style':DEFAULTS[kind],
             'style_basis':'用户确认的月报图形规则，可在模板审核时更换',
             'scope':'confirmed_events' if kind in ('theme','locality') else 'all_records',
             'unit':'件' if kind in ('theme','locality') else '条'} for i,kind in enumerate(KINDS[:len(drawings)])]

def styles_for(template,overrides=None):
    values={**DEFAULTS,**{c['id']:c['style'] for c in definitions(template)},**(overrides or {})}
    return ChartStyles.model_validate(values).model_dump()

def with_styles(template,styles):
    import copy
    result=copy.deepcopy(template);chosen=ChartStyles.model_validate({**styles_for(template),**styles}).model_dump()
    result['charts']=[{**c,'style':chosen[c['id']],'style_basis':'人工选择'} for c in definitions(template)]
    return result

def source_image(template,kind,source_index=0):
    if kind not in KINDS:raise ValueError('unknown_chart')
    source=template['source_reports'][source_index];path=Path(source['path'])
    if not path.exists() and (DATA/'uploads'/path.name).exists():path=DATA/'uploads'/path.name
    if hashlib.sha256(path.read_bytes()).hexdigest()!=source['sha256']:raise ValueError('template_source_changed')
    with zipfile.ZipFile(path) as z:
        drawings=ET.fromstring(z.read('word/document.xml')).xpath('//*[local-name()="drawing"]')
        drawing=drawings[KINDS.index(kind)];blip=drawing.xpath('.//*[local-name()="blip"]')[0]
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
