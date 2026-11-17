"""饼图标签围在四周，不使用右侧图例。"""
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from core.charts.pie_labels import format_pie_label, draw_pie_with_around_labels


def test_format_pie_label_matches_original_report_style():
    assert format_pie_label('视频', 62, 141, '条') == '视频, 62条, 43.97%'
    assert format_pie_label('医疗卫生', 1, 141, '条') == '医疗卫生, 1条, 0.71%'


def test_pie_labels_sit_around_wedges_without_legend():
    fig = Figure(figsize=(8, 6.8), dpi=80)
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    labels = ['视频', '移动客户端', '微信公众号', '微博', '网站']
    counts = [62, 39, 28, 8, 4]
    draw_pie_with_around_labels(ax, counts, labels, unit='条')
    assert ax.get_legend() is None
    labels_texts = [item.get_text() for item in ax.texts if item.get_text()]
    assert labels_texts == [
        '视频, 62条, 43.97%',
        '移动客户端, 39条, 27.66%',
        '微信公众号, 28条, 19.86%',
        '微博, 8条, 5.67%',
        '网站, 4条, 2.84%',
    ]
    for item in ax.texts:
        if not item.get_text():
            continue
        position = item.get_position()
        radius = (position[0] ** 2 + position[1] ** 2) ** 0.5
        assert radius > 0.72
