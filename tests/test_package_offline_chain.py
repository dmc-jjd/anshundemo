"""Synthetic offline chain, NOT a formal customer report or live workbench test.

Reuses frozen rows and historical prose from test_frozen_writer. No model,
spreadsheet import, real task, production template, or shared data is touched.
"""
import asyncio
import base64
import posixpath
import copy
import hashlib
import io
import zipfile
from types import SimpleNamespace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from lxml import etree as ET
from PIL import Image

import app.main as main
import app.workflow as workflow
from app.export import export_docx
from app.frozen_report import FrozenReport
from app.writer_tools import chart_payload
from core.packages import load_package
from core.packages.context import package_context
from test_frozen_writer import fixture as frozen_fixture
from test_report_package_regressions import isolated


@pytest.mark.parametrize("package", ["anshun_monthly", "ruyuan_yuebao"])
def test_package_api_planner_frozen_compute_charts_snapshot_docx(tmp_path, monkeypatch, isolated, package):
    source = tmp_path / "neutral-fixed-fixture"
    source.mkdir()
    store, template = frozen_fixture(source)
    store.package = package
    original = store.get_task("r")
    facts = store.get_artifact(original.fact_ref)
    template["charts"] = copy.deepcopy(load_package(package).template["charts"])
    chart_ids = [chart["id"] for chart in template["charts"]]
    # Rebuild only this neutral TEMP fixture's geometry for the selected package.
    # This is not an Anshun layout copied to Ruyuan or a confirmed-template edit.
    layout = Path(template["layout_source"])
    with zipfile.ZipFile(layout) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    root = ET.fromstring(entries["word/document.xml"])
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    body = root.find("w:body", ns)
    drawings = [paragraph for paragraph in body if paragraph.find(".//w:drawing", ns) is not None]
    for paragraph in drawings[len(chart_ids):]:
        body.remove(paragraph)
    entries["word/document.xml"] = ET.tostring(root)
    with zipfile.ZipFile(layout, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    template["source_reports"][0]["sha256"] = hashlib.sha256(layout.read_bytes()).hexdigest()
    template_ref = store.put_artifact("r", "template", template)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "fixture.xlsx").write_bytes(b"not imported: frozen records fixture is reused")
    planned, queued = [], []
    async def planner(role, payload, *args, **kwargs):
        assert role == "data_processor"
        planned.append(payload)
        return SimpleNamespace(action="finish_processing")
    async def background(deps, task_id):
        queued.append(task_id)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "UPLOADS", uploads)
    monkeypatch.setattr(main, "run_report_graph", background)
    monkeypatch.setattr(workflow, "invoke_agent", planner)
    with package_context("ruyuan_yuebao" if package == "anshun_monthly" else "anshun_monthly"), TestClient(main.app) as client:
        response = client.post("/api/report-tasks", json={"package": package, "file_ids": ["fixture"], "template_ref": template_ref, "mode": "dynamic", "report_month": "2026-10", "issue_number": 7})
    assert response.status_code == 200, response.text
    state = store.get_task(response.json()["id"])
    assert state.package == package and state.template_ref == template_ref and queued == [state.id]
    features = workflow.effective_features(store, state)
    refs = {name: ref for name, ref in facts["result_refs"].items() if name not in workflow._disabled_steps(features)}
    seed = store.put_artifact(state.id, "empty-processing-fixture", {"records": []})
    state.result_refs = {**{name: seed for name in workflow._needed_refs(features)}, **refs}
    store.put_task(state, state.revision)
    with package_context(package):
        asyncio.run(workflow._process_records(workflow.Dependencies(store, planner), state.id))
        assert len(planned) == 1 and planned[0]["template_id"] == template_ref
        assert [goal["id"] for goal in planned[0]["slot_goals"]] == [field["id"] for field in template["fields"]]
        state = store.get_task(state.id)
        facts = {**facts, "package": package, "result_refs": state.result_refs}
        state.fact_ref = store.put_artifact(state.id, "frozen-fixture-facts", facts)
        state.phase = "facts_frozen"
        store.put_task(state, state.revision)
        report = FrozenReport(store, state.id)
        assert report.calculate({"metric": "count", "scope": "confirmed_events"})["value"] == "2"
        assert report.calculate({"metric": "sentiment_percentage", "sentiment": "负面"})["value"] == "75.00%"
        values = {}
        for field in template["fields"]:
            if field["owner"] == "writer":
                value = field["sources"][0]["text"]  # unchanged existing fixture prose snapshot
            else:
                spec = {"metric": "issue_number"} if field["id"] == "b5_issue_no" else {"metric": "count", "scope": "negative_warning_events"}
                value = report.calculate(spec)["value"]
            values[field["id"]] = {"value": value, "source_refs": [state.fact_ref]}
        assert values["b5_issue_no"]["value"] == "7" and values["b17_warning_count"]["value"] == "1"
        chart_refs = {}
        for chart_id in chart_ids:
            payload = chart_payload(report, chart_id)
            assert payload["fact_ref"] == state.fact_ref
            png = base64.b64decode(payload["png_base64"], validate=True)
            with Image.open(io.BytesIO(png)) as image:
                assert image.format == "PNG"
                image.verify()
            with Image.open(io.BytesIO(png)) as image:
                image.load()
                assert image.width > 0 and image.height > 0
            chart_refs[chart_id] = store.put_artifact(state.id, "offline-chart", payload)
        draft = {"id": "offline-fixed-snapshot", "package": package, "template_ref": template_ref,
                 "structured_template_ref": template_ref, "fact_ref": state.fact_ref,
                 "sections": [], "slot_values": values, "chart_refs": chart_refs,
                 "evidence_refs": [state.fact_ref, *chart_refs.values()]}
        state.draft_ref = store.put_artifact(state.id, "offline-draft-snapshot", draft)
        store.put_task(state, state.revision)
        content = export_docx(draft, facts, None, "final", [], local_store=store, features=features)
    assert list(chart_refs) == chart_ids
    if package == "ruyuan_yuebao":
        assert "locality" not in chart_ids and "sentiment" not in chart_ids
        assert "resolve_locality" not in state.result_refs and features["locality"] is False
        assert store.get_artifact(chart_refs["platform_warning"])["counts"] == {"网站": 2}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert archive.testzip() is None
        document = archive.read("word/document.xml")
        ET.fromstring(document)
        assert "历史" in document.decode("utf-8") and b"{{" not in document
        chart_files = [name for name in archive.namelist() if "frozen_chart_" in name]
        assert len(chart_files) == len(chart_ids)
        assert archive.read("word/_rels/document.xml.rels").count(b"rIdFrozenChart") == len(chart_ids)
        rel_root = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        relationships = {relationship.get("Id"): relationship for relationship in rel_root}
        document_root = ET.fromstring(document)
        blips = document_root.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip")
        embed_key = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
        embeds = [blip.get(embed_key) for blip in blips]
        assert len(embeds) == len(chart_ids) and len(set(embeds)) == len(chart_ids)
        targets = set()
        for relationship_id in embeds:
            assert relationship_id.startswith("rIdFrozenChart") and relationship_id in relationships
            relationship = relationships[relationship_id]
            assert relationship.get("Type").endswith("/image")
            assert relationship.get("TargetMode") != "External"
            target = posixpath.normpath(posixpath.join("word", relationship.get("Target").replace("\\", "/")))
            assert target.startswith("word/media/") and target in archive.namelist()
            targets.add(target)
            with Image.open(io.BytesIO(archive.read(target))) as image:
                assert image.format == "PNG"
                image.verify()
            with Image.open(io.BytesIO(archive.read(target))) as image:
                image.load()
                assert image.width > 0 and image.height > 0
        assert targets == set(chart_files)
    (tmp_path / (package + "-offline-synthetic.docx")).write_bytes(content)
