"""饼图标签画在扇区周围，格式与常见月报原图一致：名称, 数量单位, 占比。"""
from __future__ import annotations

import math


def format_pie_label(label, count, total, unit=''):
    if total <= 0:
        raise ValueError('pie_requires_positive_total')
    number = int(count) if float(count).is_integer() else count
    return f'{label}, {number}{unit}, {count / total * 100:.2f}%'


def draw_pie_with_around_labels(ax, counts, labels, *, unit='', font=None, colors=None, startangle=90):
    """在 ``ax`` 上画饼图：标签围在四周，不使用右侧图例。"""
    counts = list(counts)
    labels = list(labels)
    total = sum(counts)
    if total <= 0:
        raise ValueError('pie_requires_positive_total')
    radius = 0.72
    wedges, texts = ax.pie(
        counts, colors=colors, startangle=startangle,
        autopct=None, labels=None, radius=radius)
    for item in texts:
        item.set_text('')
        item.set_visible(False)
    n = len(counts)
    fontsize = 10 if n <= 8 else 9 if n <= 12 else 8
    min_dy = 0.12 if n <= 8 else 0.10 if n <= 12 else 0.075
    current = float(startangle)
    items = []
    for count, label in zip(counts, labels):
        sweep = 360.0 * count / total
        mid = current + sweep / 2.0
        current += sweep
        theta = math.radians(mid)
        x, y = math.cos(theta), math.sin(theta)
        items.append({
            'text': format_pie_label(label, count, total, unit),
            'edge_x': x * radius,
            'edge_y': y * radius,
            'x': x * (radius + 0.22),
            'y': y * (radius + 0.22),
            'ha': 'left' if x >= 0 else 'right',
        })
    limit = 1.35
    for ha in ('left', 'right'):
        group = [item for item in items if item['ha'] == ha]
        group.sort(key=lambda item: item['y'])
        for index in range(1, len(group)):
            if group[index]['y'] - group[index - 1]['y'] < min_dy:
                group[index]['y'] = group[index - 1]['y'] + min_dy
        if group:
            overflow = group[-1]['y'] - limit
            if overflow > 0:
                for item in group:
                    item['y'] -= overflow
            underflow = -limit - group[0]['y']
            if underflow > 0:
                for item in group:
                    item['y'] += underflow
            for index in range(1, len(group)):
                if group[index]['y'] - group[index - 1]['y'] < min_dy:
                    group[index]['y'] = group[index - 1]['y'] + min_dy
    for item in items:
        text_kw = dict(
            xy=(item['edge_x'], item['edge_y']),
            xytext=(item['x'], item['y']),
            ha=item['ha'], va='center', fontsize=fontsize,
            arrowprops=dict(arrowstyle='-', color='#555555', lw=0.6, shrinkA=0, shrinkB=0),
            annotation_clip=False)
        if font is not None:
            text_kw['fontproperties'] = font
        ax.annotate(item['text'], **text_kw)
    ax.set_aspect('equal')
    ax.set_xlim(-1.7, 1.7)
    ax.set_ylim(-1.55, 1.55)
    ax.axis('off')
    return wedges
