from core.charts.label_groups import apply_label_groups
from core.charts.renderers.matplotlib import _daily_tick_label


def test_apply_label_groups_merges_media_and_other():
    values = {
        "移动客户端": 1925, "纸媒": 111, "电视": 2,
        "微信公众号": 1113, "网站": 1362, "微博": 277, "视频": 388,
        "论坛": 10,
    }
    spec = {
        "groups": [
            {"label": "媒体报道", "platforms": ["移动客户端", "纸媒", "电视"]},
            {"label": "微信公众号", "platforms": ["微信公众号"]},
            {"label": "网页", "platforms": ["网站"]},
            {"label": "微博", "platforms": ["微博"]},
            {"label": "视频", "platforms": ["视频"]},
        ],
        "other_label": "其他",
    }
    assert apply_label_groups(values, spec) == {
        "媒体报道": 2038,
        "微信公众号": 1113,
        "网页": 1362,
        "微博": 277,
        "视频": 388,
        "其他": 10,
    }


def test_apply_label_groups_noop_without_spec():
    values = {"微博": 2, "网站": 3}
    assert apply_label_groups(values, None) is values
    assert apply_label_groups(values, {}) == values


def test_daily_tick_label_md_zh():
    assert _daily_tick_label("2026-10-01", {"date_label": "md_zh"}) == "10月1日"
    assert _daily_tick_label("2026-10-01", {}) == "10-01"
