# -*- coding: utf-8 -*-
"""Step 12: a test-only minimal package can be wired without new base special-cases."""
from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.packages import registry
from core.layout import docx_path
from core.charts.spec import styles_for, chart_slots, declared_charts
from app.export import template_values
from app.template_review import available_bindings
from app.storage import Store
from core.tools.records import import_records
from core.agent import get_prompt, provenance


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "acceptance_probe"


def _xlsx(headers, rows, sheet_index=2):
    def cell(col, row, value):
        return f'<c r="{chr(65 + col)}{row}" t="inlineStr"><is><t>{value}</t></is></c>'

    body = "".join(
        f'<row r="{i}">' + "".join(cell(j, i, v) for j, v in enumerate(row)) + "</row>"
        for i, row in enumerate([headers] + rows, 1)
    )
    xml = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{body}</sheetData></worksheet>"
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(f"xl/worksheets/sheet{sheet_index}.xml", xml)
    return out.getvalue()


@pytest.fixture
def probe_root(tmp_path, monkeypatch):
    target = tmp_path / "packages" / "acceptance_probe"
    target.parent.mkdir(parents=True)
    shutil = __import__("shutil")
    shutil.copytree(FIXTURE, target)
    monkeypatch.setenv("REPORT_PACKAGES_ROOT", str(tmp_path / "packages"))
    registry.invalidate()
    yield tmp_path / "packages"
    registry.invalidate()


def test_acceptance_probe_is_listed_and_usable(probe_root):
    names = registry.discover()
    assert "acceptance_probe" in names
    entries = {item["package"]: item for item in registry.catalog()}
    assert entries["acceptance_probe"]["usable"] is True
    assert entries["acceptance_probe"]["sheet_index"] == 2


def test_acceptance_probe_imports_own_sheet(probe_root, tmp_path):
    path = tmp_path / "probe.xlsx"
    path.write_bytes(_xlsx(
        ["标题", "舆情调性", "信息日期", "摘要"],
        [["探针标题", "正面", "2026-09-01", "摘要文字"]],
        2,
    ))
    captured = {}

    class Store:
        def put_artifact(self, task_id, kind, payload):
            captured["payload"] = payload
            return "ref"

    import_records(
        {"path": str(path), "sheet_index": 2},
        SimpleNamespace(store=Store(), package="acceptance_probe", task_id="probe"),
    )
    records = captured["payload"]["records"]
    assert records[0]["title"] == "探针标题"
    assert records[0]["published"] == "2026-09-01"
    blob = " ".join(str(v) for v in records[0].values())
    assert "安顺" not in blob and "西秀" not in blob


def test_acceptance_probe_has_no_anshun_export_or_top10(probe_root, tmp_path):
    store = Store(tmp_path / "store")
    metrics = {"record_count": 3, "sentiment": {"正面": 3}, "platform": {"网站": 3}, "peak_day": "2026-09-01"}
    ref = store.put_artifact("t", "metrics", metrics)
    values = template_values({}, {"package": "acceptance_probe", "report_month": "2026-09", "result_refs": {"calculate_metrics": ref}}, store=store)
    blob = " ".join(str(v) for v in values.values()) + " ".join(values)
    for word in ("安顺市", "西秀区", "黄果树", "B12_COVER", "B5_COVER"):
        assert word not in blob
    bindings = available_bindings("acceptance_probe")
    tools = {item.get("tool") for item in bindings}
    assert "top10_events" not in tools
    assert "top10" not in {item.get("metric") for item in bindings}


def test_acceptance_probe_missing_layout_is_explicit(probe_root):
    with pytest.raises(RuntimeError) as exc:
        docx_path("acceptance_probe")
    assert "template_dir_missing" in str(exc.value)


def test_acceptance_probe_charts_and_base_prompts_are_neutral(probe_root):
    template = registry.load("acceptance_probe").template
    styles = styles_for(template, data_root=Path("."))
    assert set(styles) == {"daily", "platform"}
    assert "sentiment" not in styles and "locality" not in styles
    assert chart_slots(package="acceptance_probe") == {"CHART_1": "daily", "CHART_2": "platform"}
    assert [item["id"] for item in declared_charts(package="acceptance_probe")] == ["daily", "platform"]
    text = get_prompt("template_analyst.template", package="acceptance_probe")
    assert provenance("acceptance_probe")["template_analyst.template"] == "base"
    assert "必须整段设为一个 kind=analysis" not in text
    assert "梗概15—35字" not in text
