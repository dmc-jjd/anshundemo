# -*- coding: utf-8 -*-
"""Historical chart previews must skip cover art and redraw Word charts."""
from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from core.charts.spec import source_image

def test_legacy_vml_chart_is_replaced_in_report_export(tmp_path):
    import base64
    from core.structured_template import render_structured_docx,_schema
    path=tmp_path/'vml.docx'
    picture='<w:pict xmlns:v="urn:schemas-microsoft-com:vml"><v:shape style="width:400pt;height:200pt"><v:imagedata r:id="old"/></v:shape></w:pict>'
    _write_docx(path,[picture],{'word/media/old.png':_png('red')},[('old',R+'/image','media/old.png')])
    template={'layout_source':str(path),'source_reports':[{'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}],'fields':[],'blocks':[],'output_schema':_schema([]),'charts':[{'id':'daily','drawing_index':1}]}
    payload={'png_base64':base64.b64encode(_png('blue')).decode()}
    rendered=render_structured_docx(template,{},set(),require_complete=True,charts={'daily':payload})
    with zipfile.ZipFile(io.BytesIO(rendered)) as z:
        assert 'word/media/frozen_chart_1.png' in z.namelist()
        assert b'rIdFrozenChart1' in z.read('word/document.xml')

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def _png(color, size=(40, 30)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _pic(index, rid, name, cx, cy):
    return (
        f'<w:drawing><wp:inline>'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        f'<wp:docPr id="{index}" name="{name}"/>'
        f'<a:graphic><a:graphicData uri="{PIC}">'
        f'<pic:pic><pic:blipFill><a:blip r:embed="{rid}"/></pic:blipFill></pic:pic>'
        f'</a:graphicData></a:graphic></wp:inline></w:drawing>'
    )


def _textbox(index, name, cx, cy):
    return (
        f'<w:drawing><wp:inline>'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        f'<wp:docPr id="{index}" name="{name}"/>'
        f'<a:graphic><a:graphicData uri="{A}"/></a:graphic></wp:inline></w:drawing>'
    )


def _chart_drawing(index, rid, name, cx="5615940", cy="2983865"):
    return (
        f'<w:drawing><wp:inline>'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        f'<wp:docPr id="{index}" name="{name}"/>'
        f'<a:graphic><a:graphicData uri="{C}">'
        f'<c:chart r:id="{rid}"/>'
        f'</a:graphicData></a:graphic></wp:inline></w:drawing>'
    )


def _pie_chart_xml():
    pts = [("媒体报道", "10"), ("微信公众号", "5"), ("微博", "1")]
    cats = "".join(f'<c:pt idx="{i}"><c:v>{name}</c:v></c:pt>' for i, (name, _) in enumerate(pts))
    vals = "".join(f'<c:pt idx="{i}"><c:v>{value}</c:v></c:pt>' for i, (_, value) in enumerate(pts))
    colors = ["5B9BD5", "ED7D31", "A5A5A5"]
    dpts = "".join(
        f'<c:dPt><c:idx val="{i}"/><c:spPr><a:solidFill><a:srgbClr val="{color}"/></a:solidFill></c:spPr></c:dPt>'
        for i, color in enumerate(colors)
    )
    return (
        f'<c:chartSpace xmlns:c="{C}" xmlns:a="{A}">'
        f'<c:chart><c:plotArea><c:pieChart><c:ser>'
        f'{dpts}'
        f'<c:cat><c:strRef><c:strCache><c:ptCount val="{len(pts)}"/>{cats}</c:strCache></c:strRef></c:cat>'
        f'<c:val><c:numRef><c:numCache><c:ptCount val="{len(pts)}"/>{vals}</c:numCache></c:numRef></c:val>'
        f'</c:ser></c:pieChart></c:plotArea></c:chart></c:chartSpace>'
    )


def _write_docx(path, drawings, media, rels, extras=None):
    body = "".join(f"<w:p><w:r>{item}</w:r></w:p>" for item in drawings)
    document = (
        f'<w:document xmlns:w="{W}" xmlns:a="{A}" xmlns:r="{R}" '
        f'xmlns:wp="{WP}" xmlns:pic="{PIC}" xmlns:c="{C}">'
        f'<w:body>{body}</w:body></w:document>'
    )
    rel_xml = (
        f'<Relationships xmlns="{PKG}">'
        + "".join(
            f'<Relationship Id="{rid}" Type="{rtype}" Target="{target}"/>'
            for rid, rtype, target in rels
        )
        + "</Relationships>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", document)
        z.writestr("word/_rels/document.xml.rels", rel_xml)
        for name, data in media.items():
            z.writestr(name, data)
        for name, data in (extras or {}).items():
            z.writestr(name, data)


def _template(path, charts=None):
    return {
        "source_reports": [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}],
        "charts": charts or [
            {"id": "platform", "drawing_index": 1, "title": "全网信源分布", "style": "pie"},
            {"id": "daily", "drawing_index": 2, "title": "走势", "style": "line"},
        ],
    }


def test_source_image_skips_cover_when_word_charts_exist(tmp_path):
    path = tmp_path / "with-charts.docx"
    cover = _png((255, 0, 0), (80, 120))
    _write_docx(
        path,
        drawings=[
            _pic(1, "rId6", "图片 3", 7560310, 10692130),
            _textbox(2, "文本框 9", 7562215, 2751455),
            _chart_drawing(3, "rId7", "图表 1"),
            _chart_drawing(4, "rId8", "图表 2"),
        ],
        media={"word/media/image1.png": cover},
        rels=[
            ("rId6", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", "media/image1.png"),
            ("rId7", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart", "charts/chart1.xml"),
            ("rId8", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart", "charts/chart1.xml"),
        ],
        extras={"word/charts/chart1.xml": _pie_chart_xml()},
    )
    data, mime = source_image(_template(path), "platform", data_root=tmp_path)
    assert mime == "image/png" and data.startswith(b"\x89PNG")
    assert data != cover
    with Image.open(io.BytesIO(data)) as image:
        assert image.width > 40 and image.height > 40


def test_source_image_skips_page_cover_among_embedded_pictures(tmp_path):
    path = tmp_path / "pictures.docx"
    cover = _png((255, 0, 0), (20, 20))
    first = _png((0, 255, 0), (21, 21))
    second = _png((0, 0, 255), (22, 22))
    _write_docx(
        path,
        drawings=[
            _pic(1, "rId6", "图片 3", 7560310, 10692130),
            _textbox(2, "文本框 9", 7562215, 2751455),
            _pic(3, "rId7", "图片 4", 5612765, 2811145),
            _pic(4, "rId8", "图片 5", 5612765, 2811145),
        ],
        media={
            "word/media/image1.png": cover,
            "word/media/image2.png": first,
            "word/media/image3.png": second,
        },
        rels=[
            ("rId6", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", "media/image1.png"),
            ("rId7", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", "media/image2.png"),
            ("rId8", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", "media/image3.png"),
        ],
    )
    data, mime = source_image(_template(path), "platform", data_root=tmp_path)
    assert mime == "image/png" and data == first
    data2, _ = source_image(_template(path), "daily", data_root=tmp_path)
    assert data2 == second


def test_similar_placeholder_images_are_all_kept(tmp_path):
    path = tmp_path / "anshun-like.docx"
    images = [_png((i * 40, 10, 10), (30 + i, 30)) for i in range(5)]
    drawings = [_pic(i + 1, f"rId{i+10}", f"图片 {i+1}", 5708015, 2536825) for i in range(5)]
    media = {f"word/media/image{i+1}.png": images[i] for i in range(5)}
    rels = [
        (f"rId{i+10}", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", f"media/image{i+1}.png")
        for i in range(5)
    ]
    _write_docx(path, drawings, media, rels)
    template = {"source_reports": [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]}
    data, mime = source_image(template, "sentiment", data_root=tmp_path)
    assert mime == "image/png" and data == images[0]


def test_ruyuan_layout_source_is_not_the_cover():
    path = Path("data/packages/ruyuan_yuebao/uploads/file-dee9c61c0b8b799a5bdf.docx")
    if not path.exists():
        pytest.skip("ruyuan historical report not in this checkout")
    import zipfile
    with zipfile.ZipFile(path) as z:
        cover = z.read("word/media/image1.png")
    template = {
        "source_reports": [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}],
        "charts": [
            {"id": "platform", "drawing_index": 1, "style": "pie"},
            {"id": "daily", "drawing_index": 2, "style": "line"},
            {"id": "platform_warning", "drawing_index": 3, "style": "pie"},
            {"id": "theme", "drawing_index": 4, "style": "bar"},
        ],
    }
    data, mime = source_image(template, "platform", data_root=path.parents[2])
    assert mime == "image/png" and data.startswith(b"\x89PNG")
    assert data != cover
    with Image.open(io.BytesIO(data)) as image:
        assert image.width > 100 and image.height > 80


@pytest.mark.parametrize('mixed', [False, True])
def test_vml_source_pictures_in_document_order(tmp_path, mixed):
    path=tmp_path/'legacy-pictures.docx'
    first=_png((11,44,77));second=_png((77,44,11))
    def vml(rid):
        return f'<w:pict xmlns:v="urn:schemas-microsoft-com:vml"><v:shape><v:imagedata r:id="{rid}"/></v:shape></w:pict>'
    drawings=['<w:pict xmlns:v="urn:schemas-microsoft-com:vml"><v:imagedata/></w:pict>',vml('rId1'), _pic(2,'rId2','second',5000000,2500000) if mixed else vml('rId2')]
    _write_docx(path,drawings,{'word/media/first.png':first,'word/media/second.png':second},[
        ('rId1',R+'/image','media/first.png'),('rId2',R+'/image','media/second.png')])
    template=_template(path)
    assert source_image(template,'platform',data_root=tmp_path)==(first,'image/png')
    assert source_image(template,'daily',data_root=tmp_path)==(second,'image/png')


def test_vml_fallback_does_not_duplicate_modern_image(tmp_path):
    path=tmp_path/'alternate.docx';first=_png((10,20,30));second=_png((30,20,10))
    modern=_pic(1,'rId1','first',5000000,2500000)
    alternate=f'<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"><mc:Choice Requires="wps">{modern}</mc:Choice><mc:Fallback><w:pict xmlns:v="urn:schemas-microsoft-com:vml"><v:shape><v:imagedata r:id="rId1"/></v:shape></w:pict></mc:Fallback></mc:AlternateContent>'
    _write_docx(path,[alternate,_pic(2,'rId2','second',5000000,2500000)],
        {'word/media/first.png':first,'word/media/second.png':second},[
        ('rId1',R+'/image','media/first.png'),('rId2',R+'/image','media/second.png')])
    assert source_image(_template(path),'daily',data_root=tmp_path)==(second,'image/png')
