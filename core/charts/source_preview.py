"""历史报告原图预览：有嵌入图片就直接取出；Word 统计图则按缓存数据重画。"""
from __future__ import annotations

import io
import posixpath
import threading
from pathlib import Path

from lxml import etree as ET

_PLOT_LOCK = threading.Lock()
_R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
_PALETTE = ['#5b9bd5', '#ed7d31', '#a5a5a5', '#ffc000', '#4472c4', '#70ad47', '#8064a2', '#c0504d']


def preview_source_drawing(archive, drawing):
    """Return (png_or_jpeg_bytes, mime) for one chart slot in a historical docx."""
    blips = drawing.xpath('.//*[local-name()="blip"]')
    if blips:
        return _embedded_image(archive, blips[0])
    if drawing.xpath('.//*[local-name()="chart"]'):
        return _render_word_chart(archive, drawing)
    raise ValueError('source_chart_unavailable')


def _rels(archive, rels_name):
    root = ET.fromstring(archive.read(rels_name))
    return {item.get('Id'): item for item in root}


def _target_name(rel, base='word/'):
    if rel is None or rel.get('TargetMode') == 'External':
        raise ValueError('source_chart_unavailable')
    target = rel.get('Target', '')
    if target.startswith('/'):
        return target.lstrip('/')
    return posixpath.normpath(base + target)


def _embedded_image(archive, blip):
    rid = blip.get(_R + 'embed')
    rels = _rels(archive, 'word/_rels/document.xml.rels')
    name = _target_name(rels.get(rid))
    if not name.startswith('word/media/'):
        raise ValueError('not_embedded_chart_image')
    data = archive.read(name)
    mime = 'image/png' if data.startswith(b'\x89PNG') else 'image/jpeg' if data.startswith(b'\xff\xd8') else None
    if mime:
        return data, mime
    # Historical Word reports contain EMF, which browsers cannot display.
    # Pillow uses Windows GDI to rasterize it without altering the document.
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format == 'WMF':
                image.load(dpi=160)
            out = io.BytesIO()
            image.convert('RGB').save(out, format='PNG')
            return out.getvalue(), 'image/png'
    except (OSError, ValueError) as exc:
        raise ValueError('source_image_format_not_previewable') from exc


def _render_word_chart(archive, drawing):
    node = drawing.xpath('.//*[local-name()="chart"]')[0]
    rid = node.get(_R + 'id')
    rels = _rels(archive, 'word/_rels/document.xml.rels')
    name = _target_name(rels.get(rid))
    if not name.startswith('word/charts/'):
        raise ValueError('source_chart_unavailable')
    series = _chart_series(ET.fromstring(archive.read(name)))
    if not series or not series['labels'] or not series['series']:
        raise ValueError('source_chart_unavailable')
    return _draw_series(series), 'image/png'


def _cache_values(parent):
    if parent is None:
        return []
    cache = None
    for item in parent.xpath('.//*[local-name()="strCache" or local-name()="numCache"]'):
        cache = item
        break
    if cache is None:
        return []
    points = []
    for pt in cache.xpath('.//*[local-name()="pt"]'):
        idx = pt.get('idx')
        value = ''.join(pt.xpath('.//*[local-name()="v"]/text()'))
        try:
            index = int(idx)
        except (TypeError, ValueError):
            continue
        points.append((index, value))
    points.sort()
    return [value for _, value in points]


def _as_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _hex_color(node):
    colors = node.xpath('.//*[local-name()="srgbClr"]/@val')
    if not colors:
        return None
    val = colors[0].strip()
    if not val:
        return None
    if not val.startswith('#'):
        val = '#' + val
    return val


def _chart_series(root):
    plot = None
    for name in ('pieChart', 'doughnutChart', 'ofPieChart', 'lineChart', 'line3DChart',
                 'barChart', 'bar3DChart', 'areaChart', 'area3DChart'):
        found = root.xpath('.//*[local-name()="%s"]' % name)
        if found:
            plot = found[0]
            break
    if plot is None:
        raise ValueError('source_chart_unavailable')
    tag = plot.tag.split('}')[-1]
    if tag in ('pieChart', 'doughnutChart', 'ofPieChart'):
        style = 'pie'
    elif tag in ('lineChart', 'line3DChart'):
        style = 'line'
    elif tag in ('barChart', 'bar3DChart'):
        direction = plot.xpath('.//*[local-name()="barDir"]/@val')
        style = 'barh' if direction and direction[0] == 'bar' else 'bar'
    else:
        style = 'bar'
    labels = []
    series = []
    colors = []
    for ser in plot.xpath('.//*[local-name()="ser"]'):
        cats = _cache_values(next(iter(ser.xpath('.//*[local-name()="cat"]')), None))
        vals = [_as_number(v) for v in _cache_values(next(iter(ser.xpath('.//*[local-name()="val"]')), None))]
        if cats and not labels:
            labels = cats
        if not labels:
            labels = [str(i + 1) for i in range(len(vals))]
        if len(vals) < len(labels):
            vals = vals + [0.0] * (len(labels) - len(vals))
        series.append(vals[:len(labels)] if labels else vals)
        point_colors = []
        for pt in ser.xpath('.//*[local-name()="dPt"]'):
            color = _hex_color(pt)
            if color:
                point_colors.append(color)
        if point_colors:
            colors = point_colors
        elif not colors:
            color = _hex_color(ser)
            if color:
                colors = [color]
    return {'style': style, 'labels': labels, 'series': series, 'colors': colors}


def _font():
    from matplotlib.font_manager import FontProperties
    fontpath = Path('C:/Windows/Fonts/msyh.ttc')
    if fontpath.exists():
        return FontProperties(fname=str(fontpath), size=12)
    return FontProperties(family='DejaVu Sans', size=12)


def _draw_series(spec):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    style = spec['style']
    labels = list(spec['labels'])
    series = spec['series']
    counts = series[0]
    colors = list(spec['colors'] or [])
    palette = (colors + _PALETTE)[:max(len(labels), 1)]
    font = _font()
    with _PLOT_LOCK:
        if style == 'pie':
            from core.charts.pie_labels import draw_pie_with_around_labels
            if sum(counts) <= 0:
                raise ValueError('source_chart_unavailable')
            fig = Figure(figsize=(8.0, 6.8), dpi=160)
            FigureCanvasAgg(fig)
            ax = fig.subplots()
            draw_pie_with_around_labels(ax, counts, labels, font=font, colors=palette)
        else:
            fig = Figure(figsize=(10, 4.8), dpi=160, layout='constrained')
            FigureCanvasAgg(fig)
            ax = fig.subplots()
            if style == 'line':
                for index, values in enumerate(series):
                    ax.plot(range(len(labels)), values, color=palette[index % len(palette)], linewidth=2)
                ax.set_xticks(range(len(labels)), labels, fontproperties=font, rotation=40, ha='right')
                ax.spines[['top', 'right']].set_visible(False)
                ax.grid(axis='y', alpha=.15)
            elif style == 'barh':
                bars = ax.barh(range(len(labels)), counts, color=palette[0] if len(set(palette[:len(labels)])) == 1 else palette)
                ax.set_yticks(range(len(labels)), labels, fontproperties=font)
                ax.invert_yaxis()
                ax.bar_label(bars, padding=3, fontsize=10)
                ax.margins(x=.16)
                ax.spines[['top', 'right']].set_visible(False)
                ax.grid(axis='x', alpha=.15)
            else:
                bars = ax.bar(range(len(labels)), counts, color=palette[0] if len(set(palette[:len(labels)])) == 1 else palette)
                ax.set_xticks(range(len(labels)), labels, fontproperties=font, rotation=40, ha='right')
                ax.bar_label(bars, padding=3, fontsize=10)
                ax.margins(y=.15)
                ax.spines[['top', 'right']].set_visible(False)
                ax.grid(axis='y', alpha=.15)
        out = io.BytesIO()
        fig.savefig(out, format='png', **({'bbox_inches': 'tight', 'pad_inches': .2} if style == 'pie' else {}))
        fig.clear()
    return out.getvalue()
