# -*- coding: utf-8 -*-
"""Package-declared source pie charts aggregate records.source via metrics.source."""
from __future__ import annotations

from core.charts.spec import family_of, resolve_chart, allowed_styles, styles_for
from app.storage import Store
from app.schemas import TaskState
from app.tool_executor import RunContext
from app.tool import calculate_metrics
from test_frozen_writer import fixture
from app.frozen_report import FrozenReport


SOURCE_CHART = {
    "id": "source",
    "title": "信源分布",
    "draft_title": "来源信息分布（原始记录）",
    "final_title": "信源分布",
    "family": "pie",
    "style": "pie",
    "binding": {"source": "metrics.source"},
    "unit": "条",
    "scope": "all_records",
    "axis_label": "信源",
}


def test_source_family_and_default_binding():
    assert family_of({"id": "source", "family": "pie"}) == "source"
    assert family_of({"id": "source", "family": "source"}) == "source"
    assert allowed_styles({"id": "source", "family": "pie"}) == ("pie", "bar", "barh")
    chart = resolve_chart("source", {"charts": [SOURCE_CHART]})
    assert chart["binding"]["source"] == "metrics.source"
    assert chart["style"] == "pie"
    assert chart["scope"] == "all_records"


def test_calculate_metrics_aggregates_source_field(tmp_path):
    rows = [
        {"id": "1", "title": "a", "published": "2026-10-01", "sentiment": "中性",
         "platform": "网站", "source": "南方日报"},
        {"id": "2", "title": "b", "published": "2026-10-01", "sentiment": "正面",
         "platform": "微信公众号", "source": "龙川发布"},
        {"id": "3", "title": "c", "published": "2026-10-02", "sentiment": "中性",
         "platform": "网站", "source": "南方日报"},
        {"id": "4", "title": "d", "published": "2026-10-02", "sentiment": "负面",
         "platform": "网站", "source": ""},
    ]
    store = Store(tmp_path)
    store.put_task(TaskState(id="t1", kind="report", phase="processing"))
    ref = store.put_artifact("t1", "records", {"records": rows})
    result = calculate_metrics({"records_ref": ref}, RunContext(store, "t1"))
    metrics = store.get_artifact(result.data_ref)
    assert metrics["source"] == {"南方日报": 2, "龙川发布": 1, "未知": 1}
    assert metrics["platform"] == {"网站": 3, "微信公众号": 1}


def test_metric_counts_source_honors_scope(tmp_path):
    # Build a frozen snapshot whose facts.result_refs point at these records.
    # A later put_artifact would not be visible to FrozenReport.
    store = Store(tmp_path / "store")
    tid = "r"
    rows = [
        {"id": "r0", "source": "南方日报", "sentiment": "负面", "warning": "是",
         "published": "2026-10-02", "platform": "网站"},
        {"id": "r1", "source": "省报", "sentiment": "负面", "warning": "是",
         "published": "2026-10-02", "platform": "网站"},
        {"id": "r2", "source": "其他", "sentiment": "负面", "warning": "否",
         "published": "2026-10-02", "platform": "网站"},
        {"id": "r3", "source": "南方日报", "sentiment": "正面", "warning": "否",
         "published": "2026-10-02", "platform": "网站"},
    ]
    metrics = {
        "record_count": 4,
        "source": {"南方日报": 2, "省报": 1, "其他": 1},
        "sentiment": {"负面": 3, "正面": 1},
        "platform": {"网站": 4},
    }
    refs = {
        "import_records": store.put_artifact(tid, "records", {"records": rows}),
        "calculate_metrics": store.put_artifact(tid, "metrics", metrics),
        "confirmed_event_groups": store.put_artifact(tid, "groups", {"groups": [
            {"id": "g1", "representative_id": "r0", "member_ids": ["r0", "r1"]},
            {"id": "g2", "representative_id": "r2", "member_ids": ["r2"]},
        ]}),
    }
    fact = store.put_artifact(tid, "facts", {"metrics": metrics, "result_refs": refs, "report_month": "2026-10"})
    store.put_task(TaskState(id=tid, kind="report", phase="facts_frozen", fact_ref=fact, result_refs=refs))
    report = FrozenReport(store, tid)
    assert report.metric_counts("source", "all_records") == {"南方日报": 2, "省报": 1, "其他": 1}
    counts = report.metric_counts("source", "negative_warning_events")
    assert counts == {"南方日报": 1, "省报": 1}


def test_styles_for_accepts_declared_source(tmp_path):
    _, template = fixture(tmp_path)
    custom = dict(template, charts=list(template.get("charts") or []) + [SOURCE_CHART])
    styles = styles_for(custom, data_root=tmp_path)
    assert styles["source"] == "pie"
    assert "source" not in styles_for(template, data_root=tmp_path)
