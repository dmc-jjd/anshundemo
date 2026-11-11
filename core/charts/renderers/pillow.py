"""Pillow 直绘渲染器：草稿/候选图。画布与样式是产品既定规则；标题/单位/口径来自客户包 charts 段。"""
from __future__ import annotations
import base64, io
from collections import Counter
from core.tools.contracts import ToolResult
from core.charts import registry


def render_chart(args, ctx):
    from PIL import Image, ImageDraw, ImageFont
    chart_type = args['chart_type']
    metrics = ctx.store.get_artifact(args['metrics_ref'])
    if chart_type not in registry.ids():
        raise ValueError('unknown_chart_type')
    chart = registry.chart(chart_type)
    title = chart['draft_title']
    candidate = chart['scope'] == 'confirmed_events'
    artifact, _, key = chart['binding']['source'].partition('.')
    if artifact == 'metrics':
        values = metrics[key]
    elif artifact == 'theme_clusters':
        if not args.get('cluster_ref'):
            return ToolResult(status='needs_review', method='theme chart requires cluster input',
                              unresolved=[{'kind': 'chart_input', 'question': '分类候选缺失'}])
        groups = ctx.store.get_artifact(args['cluster_ref'])[key]
        values = {g['candidate_theme']: len(g['member_ids']) for g in groups}
    elif artifact == 'locality':
        if not args.get('locality_ref'):
            return ToolResult(status='needs_review', method='locality chart requires locality input',
                              unresolved=[{'kind': 'chart_input', 'question': '属地候选缺失'}])
        items = ctx.store.get_artifact(args['locality_ref'])[key]
        values = dict(Counter(x['candidates'][0] for x in items if len(x['candidates']) == 1))
    else:
        raise ValueError('unknown_chart_source')
    if not values:
        return ToolResult(status='needs_review', method='chart has no data',
                          unresolved=[{'kind': 'chart_input', 'question': '无可绘制数据'}])
    font_path = 'C:/Windows/Fonts/msyh.ttc'
    font = ImageFont.truetype(font_path, 24); small = ImageFont.truetype(font_path, 18)
    width, height = 1050, 640; img = Image.new('RGB', (width, height), '#ffffff'); d = ImageDraw.Draw(img)
    d.text((36, 22), title + (' · 未确认' if candidate else ''), font=font, fill='#17374b')
    if chart['family'] == 'line':
        ordered = sorted(values.items())
        maxval = max(values.values()) or 1; left, right, top, bottom = 85, 1000, 95, 550
        d.line((left, bottom, right, bottom), fill='#9fb2bb', width=2); d.line((left, top, left, bottom), fill='#9fb2bb', width=2)
        points = []
        for i, (label, value) in enumerate(ordered):
            x = left + int(i / max(1, len(ordered) - 1) * (right - left)); y = bottom - int(value / maxval * (bottom - top))
            points.append((x, y))
            if i % max(1, len(ordered) // 8) == 0: d.text((x - 18, bottom + 8), label[5:], font=small, fill='#5b6c77')
        if len(points) > 1: d.line(points, fill='#2d7895', width=4)
        for x, y in points: d.ellipse((x - 4, y - 4, x + 4, y + 4), fill='#2d7895')
        d.text((35, 75), f"峰值 {maxval} {chart['unit']}", font=small, fill='#334b5c')
    else:
        ordered = sorted(values.items(), key=lambda kv: kv[1], reverse=True)[:15]
        maxval = max(v for _, v in ordered) or 1
        step = min(165, (height - 155) / len(ordered)); bar_height = min(42, max(20, step - 12))
        for i, (label, value) in enumerate(ordered):
            y = int(80 + i * step); d.text((35, y), str(label)[:10], font=small, fill='#334b5c')
            bar = int(value / maxval * 600); d.rectangle((230, y + 4, 230 + bar, y + 4 + bar_height), fill='#2d7895')
            d.text((240 + bar, y), str(value), font=small, fill='#17374b')
    d.text((35, 603), '来源：本任务数据工件；候选图须人工确认后才能用于正式报告', font=small, fill='#6c7c86')
    buffer = io.BytesIO(); img.save(buffer, format='PNG')
    ref = ctx.store.put_artifact(ctx.task_id, 'chart', {'chart_type': chart_type, 'title': title,
        'values': values, 'candidate': candidate, 'metrics_ref': args['metrics_ref'],
        'source_refs': [x for x in (args.get('cluster_ref'), args.get('locality_ref')) if x],
        'png_base64': base64.b64encode(buffer.getvalue()).decode(), 'style_version': 2,
        'method': 'Pillow chart; candidate labels shown when unconfirmed'})
    return ToolResult(status='needs_review' if candidate else 'ok', data_ref=ref,
                      method='Pillow chart from referenced metrics; candidate watermark where applicable',
                      unresolved=[{'kind': 'chart_confirmation', 'question': '候选主题或属地图不能作为正式图表'}] if candidate else [])


HANDLERS = {render_chart.__name__: render_chart}
