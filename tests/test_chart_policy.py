# -*- coding: utf-8 -*-
"""Chart order / family / scope come from the package or confirmed template, not a hardcoded list."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.charts.spec import (
    drawing_ids,
    family_of,
    resolve_chart,
    styles_for,
    chart_title,
    ordered_template_charts,
)
from test_frozen_writer import fixture
from app.frozen_report import FrozenReport
from app.writer_tools import chart_payload, CHARTS


CUSTOM_CHARTS = [
    {"id": "platform", "family": "platform", "drawing_index": 1, "title": "全网信源分布",
     "style": "pie", "scope": "all_records", "unit": "条", "binding": {"source": "metrics.platform"}},
    {"id": "daily", "family": "daily", "drawing_index": 2, "title": "负面预警传播趋势",
     "style": "line", "scope": "negative_warning_events", "unit": "条", "binding": {"source": "metrics.daily_count"}},
    {"id": "platform_warning", "family": "platform", "drawing_index": 3, "title": "负面预警信源分布",
     "style": "pie", "scope": "negative_warning_events", "unit": "条", "binding": {"source": "metrics.platform"}},
    {"id": "theme", "family": "theme", "drawing_index": 4, "title": "负面预警内容分类",
     "style": "bar", "scope": "negative_warning_events", "unit": "件", "binding": {"source": "theme_clusters.groups"}},
]


def test_anshun_family_ignores_style_stored_as_family():
    assert family_of({"id": "sentiment", "family": "pie"}) == "sentiment"
    assert family_of({"id": "daily", "family": "line"}) == "daily"
    assert family_of({"id": "platform_warning", "family": "platform"}) == "platform"
    assert family_of({"id": "platform_warning", "family": "pie"}) == "platform"
    assert family_of({"id": "source", "family": "pie"}) == "source"
    assert family_of({"id": "source", "family": "source"}) == "source"


def test_drawing_ids_follow_template_not_default_list():
    template = {"charts": list(CUSTOM_CHARTS)}
    assert drawing_ids(template) == {1: "platform", 2: "daily", 3: "platform_warning", 4: "theme"}
    assert [item["id"] for item in ordered_template_charts(template)] == [
        "platform", "daily", "platform_warning", "theme",
    ]


def test_styles_for_allows_declared_extra_id_and_keeps_anshun_rejections(tmp_path):
    _, template = fixture(tmp_path)
    assert styles_for(template, data_root=tmp_path) == {
        "sentiment": "pie", "daily": "line", "platform": "pie", "theme": "bar", "locality": "barh",
    }
    custom = dict(template, charts=list(CUSTOM_CHARTS))
    styles = styles_for(custom, data_root=tmp_path)
    assert styles["platform"] == "pie"
    assert styles["platform_warning"] == "pie"
    assert styles["daily"] == "line"
    assert styles["theme"] == "bar"
    with pytest.raises(ValueError):
        styles_for(template, {"daily": "pie"}, data_root=tmp_path)
    with pytest.raises(ValueError):
        styles_for(template, {"made_up": "pie"}, data_root=tmp_path)
    with pytest.raises(ValueError):
        styles_for(custom, {"made_up": "pie"}, data_root=tmp_path)


def test_metric_counts_honor_scope(tmp_path):
    store, _ = fixture(tmp_path)
    report = FrozenReport(store, "r")
    assert report.metric_counts("platform", "all_records") == {"网站": 4}
    assert report.metric_counts("daily_count", "all_records") == {"2026-10-02": 4}
    assert report.metric_counts("platform", "negative_warning_events") == {"网站": 2}
    assert report.metric_counts("daily_count", "negative_warning_events") == {"2026-10-02": 2}
    assert report.categories_for("negative_warning_events") == {"市场监管": 1}
    assert sum(report.categories_for().values()) == 2


def test_payload_uses_template_scope_title_and_second_platform(tmp_path):
    store, template = fixture(tmp_path)
    template["charts"] = list(CUSTOM_CHARTS)
    # The store holds a copy; refresh the artifact so chart_payload can resolve it.
    state = store.get_task("r")
    state.template_ref = store.put_artifact("r", "template", template)
    store.put_task(state, state.revision)
    report = FrozenReport(store, "r")

    all_platform = chart_payload(report, "platform")
    warn_platform = chart_payload(report, "platform_warning")
    daily = chart_payload(report, "daily")
    theme = chart_payload(report, "theme")

    assert all_platform["scope"] == "all_records"
    assert all_platform["counts"] == {"网站": 4}
    assert warn_platform["scope"] == "negative_warning_events"
    assert warn_platform["counts"] == {"网站": 2}
    assert daily["scope"] == "negative_warning_events"
    assert daily["counts"] == {"2026-10-02": 2}
    assert daily["x_axis"] == "日期"
    assert theme["scope"] == "negative_warning_events"
    assert theme["counts"] == {"市场监管": 1}
    assert theme["unit"] == "件"
    assert chart_title(CUSTOM_CHARTS[0]) == "全网信源分布"
    assert resolve_chart("platform_warning", template)["binding"]["source"] == "metrics.platform"


def test_anshun_default_payload_unchanged(tmp_path):
    store, _ = fixture(tmp_path)
    report = FrozenReport(store, "r")
    assert list(CHARTS) == ["sentiment", "daily", "platform", "theme", "locality"]
    daily = chart_payload(report, "daily")
    assert daily["scope"] == "all_records"
    assert daily["counts"] == {"2026-10-02": 4}
    assert daily["x_axis"] == "日期"
    sentiment = chart_payload(report, "sentiment")
    assert sentiment["counts"] == {"负面": 3, "正面": 1}
    theme = chart_payload(report, "theme")
    assert theme["scope"] == "confirmed_events"
    assert sum(theme["counts"].values()) == 2


def test_ruyuan_styles_for_excludes_undeclared_ids():
    from core.packages import load_package
    from core.charts.spec import chart_slots, display_titles

    template = load_package("ruyuan_yuebao").template
    styles = styles_for(template, data_root=Path("."))
    assert list(styles) == ["platform", "daily", "platform_warning", "theme"]
    assert set(styles) == {"platform", "daily", "platform_warning", "theme"}
    assert "sentiment" not in styles and "locality" not in styles
    assert chart_slots(template=template, package="ruyuan_yuebao") == {
        "CHART_1": "platform",
        "CHART_2": "daily",
        "CHART_3": "platform_warning",
        "CHART_4": "theme",
    }
    titles = display_titles(template=template, package="ruyuan_yuebao")
    assert list(titles) == ["platform", "daily", "platform_warning", "theme"]
    assert titles["platform"].startswith("图1")
    assert "全网信源分布" in titles["platform"]
    assert "舆情情绪分布图" not in titles["platform"]
    assert "各区县" not in "".join(titles.values())


def test_anshun_chart_slots_and_titles_stay_five():
    from core.packages import load_package
    from core.charts.spec import chart_slots, display_titles

    template = load_package("anshun_monthly").template
    styles = styles_for(template, data_root=Path("."))
    assert set(styles) == {"sentiment", "daily", "platform", "theme", "locality"}
    assert styles == {
        "sentiment": "pie", "daily": "line", "platform": "pie", "theme": "bar", "locality": "barh",
    }
    assert chart_slots(package="anshun_monthly") == {
        "CHART_1": "sentiment",
        "CHART_2": "daily",
        "CHART_3": "platform",
        "CHART_4": "theme",
        "CHART_5": "locality",
    }
    titles = display_titles(package="anshun_monthly")
    assert titles["sentiment"] == "图1 舆情情绪分布图"
    assert titles["daily"] == "图2 舆情信息数量图"
    assert titles["platform"] == "图3 舆情信源分布图"
    assert titles["theme"] == "图4 负面舆情分类分布情况"
    assert titles["locality"] == "图5 各区县舆情分布情况"


def test_new_chart_id_maps_to_final_slots_and_passes_styles(tmp_path):
    template = {
        "charts": [
            {"id": "warning_trend", "family": "line", "drawing_index": 1, "title": "预警走势", "style": "line"},
            {"id": "source", "family": "source", "drawing_index": 2, "title": "信源分布", "style": "pie"},
        ]
    }
    styles = styles_for(template, data_root=tmp_path)
    assert styles == {"warning_trend": "line", "source": "pie"}
    assert "sentiment" not in styles and "locality" not in styles
    from core.charts.spec import chart_slots, display_titles
    assert chart_slots(template=template) == {"CHART_1": "warning_trend", "CHART_2": "source"}
    titles = display_titles(template=template)
    assert titles["warning_trend"].startswith("图1")
    assert "预警走势" in titles["warning_trend"]


def test_styles_for_custom_charts_do_not_keep_undeclared_defaults():
    styles = styles_for({"charts": list(CUSTOM_CHARTS)}, data_root=Path("."))
    assert set(styles) == {"platform", "daily", "platform_warning", "theme"}
    assert "sentiment" not in styles and "locality" not in styles
