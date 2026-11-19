import base64
import io
from pathlib import Path

from PIL import Image
from core.charts.label_groups import apply_label_groups


def test_pie_labels_fit_even_when_small_slices_are_all_on_one_side():
    from matplotlib.figure import Figure
    from core.charts.pie_labels import draw_pie_with_around_labels
    counts=[1079,731,644,580,152,145,134,87,82,77,57,57,56,53,49,35,13,9,6]
    ax=Figure().subplots()
    draw_pie_with_around_labels(ax,counts,[str(i) for i in range(len(counts))],compact=True)
    annotations=[t for t in ax.texts if t.get_visible()]
    assert len(annotations)==len(counts)
    assert all(abs(t.xyann[1])<=1.200001 for t in annotations)


def test_source_chart_groups_explicit_channels_without_changing_total():
    values={'短视频':3,'短视频-新闻':4,'短视频号外':5,'网站':2,'长尾':1}
    grouped=apply_label_groups(values,{'groups':[{'label':'短视频','platforms':['短视频'],
        'prefixes':['短视频']}], 'other_label':'其他'})
    assert grouped=={'短视频':7,'其他':8}
    assert sum(grouped.values())==sum(values.values())
    assert values['短视频-新闻']==4


def test_longchuan_presentation_keeps_line_values_and_bounds_source_labels(tmp_path,monkeypatch):
    monkeypatch.setattr('core.paths.data_root',lambda:tmp_path)
    from core.packages.context import bind,unbind
    from core.charts.renderers.matplotlib import chart_payload
    from matplotlib.axes import Axes
    from unittest.mock import patch
    from types import SimpleNamespace
    from core.packages import load_package
    template=load_package('longchuan_yuebao').template
    class Report:
        state=SimpleNamespace(template_ref='template',metadata={})
        store=SimpleNamespace(get_artifact=lambda _:template)
        fact_ref='frozen'
        def metric_counts(self,key,scope):
            if key=='daily_count':return {f'2026-10-{i:02}':i for i in range(1,32)}
            return {'微信公众号':879,'微信视频号':200,'抖音':159,'抖音-广州':332,
                    **{f'小站{i}':1 for i in range(200)}}
    token=bind('longchuan_yuebao')
    try:
        labels=[];original=Axes.annotate
        def annotate(ax,text,*a,**kw):
            labels.append(str(text));return original(ax,text,*a,**kw)
        with patch.object(Axes,'annotate',annotate):
            daily=chart_payload(Report(),'daily')
        assert all(str(i) in labels for i in range(1,32))
        source=chart_payload(Report(),'source')
        assert source['counts']['微信公众号']==1079
        assert source['counts']['抖音']==491
        assert source['counts']['其他']==200
        assert sum(source['counts'].values())==1770
        with Image.open(io.BytesIO(base64.b64decode(source['png_base64']))) as image:
            assert image.height/image.width<1.1
    finally:unbind(token)
