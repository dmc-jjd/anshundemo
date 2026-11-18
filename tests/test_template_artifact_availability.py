"""Explicit management-list contract migration and isolated input prerequisites.

Fixed temporary stores only. Missing rows remain manageable; unavailable
artifacts must not reach creation, approval, generation or any real model.
"""
import asyncio
import hashlib
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
import app.main as main
import app.workflow as workflow
from app.api_views.template_library import list_templates
from app.schemas import TaskState
from core.packages.context import package_context
from test_report_package_regressions import isolated, business_snapshot

PACKAGES = ("anshun_monthly", "ruyuan_yuebao")


def _write_api_input(path, package):
    """Real OOXML and package-required headers, never a production upload."""
    from core.tools import vocabulary
    from test_sheet_index import _xlsx
    columns = vocabulary.required_columns(package)
    sheet = vocabulary.sheet_index(package)
    path.write_bytes(_xlsx(columns, [[package] + [""] * (len(columns) - 1)], sheet))
    # Complete the existing worksheet fixture into a normal OPC XLSX package.
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet' + str(sheet) + '.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        archive.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="offline" sheetId="' + str(sheet) + '" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet' + str(sheet) + '.xml"/></Relationships>')


@pytest.fixture
def availability_env(isolated, tmp_path, monkeypatch):
    store, refs, queued = isolated
    from core.packages.context import default_package
    # Preserve the documented default-package host upload injection contract.
    # Without this, the default branch searches the real host UPLOADS, not tmp_path.
    monkeypatch.setattr(main, "UPLOADS", store.uploads_for(default_package()))
    for package in PACKAGES:
        _write_api_input(store.uploads_for(package) / "fixture.xlsx", package)
        local = store.store_for(package)
        layout = tmp_path / (package + "-availability.docx")
        with zipfile.ZipFile(layout, "w") as archive:
            archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>fixed snapshot</w:t></w:r></w:p></w:body></w:document>')
        template = local.get_artifact(refs[package])
        template["layout_source"] = str(layout)
        template["source_reports"][0]["sha256"] = hashlib.sha256(layout.read_bytes()).hexdigest()
        refs[package] = local.put_artifact("template-" + package, "availability-template", template)
        state = store.get_task("template-" + package)
        state.metadata["confirmed_template_ref"] = refs[package]
        state.metadata["template_name"] = package + " fixture"
        store.put_task(state, state.revision)
    return store, refs, queued


def damage_template(store, package, ref, damage):
    path = store.store_for(package).files / (ref + ".json")
    if damage == "missing":
        path.unlink()  # only a pytest temporary fixture file
    else:
        path.write_text("{invalid-json", encoding="utf-8")
    return "template_artifact_" + damage


@pytest.mark.parametrize('package', PACKAGES)
def test_api_template_list_filters_multi_package_store(availability_env, package):
    store, refs, _ = availability_env
    other = next(value for value in PACKAGES if value != package)
    with TestClient(main.app) as client:
        response = client.get('/api/templates', headers={'X-Report-Package': package})
    assert response.status_code == 200
    ids = {item['id'] for item in response.json()}
    assert refs[package] in ids
    assert refs[other] not in ids


@pytest.mark.parametrize('package', PACKAGES)
@pytest.mark.parametrize('damage', ['missing', 'unreadable'])
def test_template_preview_returns_explicit_unavailable_error(availability_env, package, damage):
    store, refs, _ = availability_env
    code = damage_template(store, package, refs[package], damage)
    with TestClient(main.app) as client:
        response = client.get('/api/templates/template-' + package + '/definition')
    assert response.status_code == 409
    assert response.json()['detail'] == code


def seed_report(store, package, ref, *, approval=False, structured=True):
    with package_context(package):
        state = TaskState(id="report-" + package, kind="report", package=package,
                          phase="awaiting_final_review" if approval else "facts_frozen", template_ref=ref)
        store.put_task(state)
        state.fact_ref = store.put_artifact(state.id, "availability-facts", {"metrics": {}})
        if approval:
            draft = {"id": "d", "template_ref": ref, "fact_ref": state.fact_ref, "content_hash": "hash",
                     "sections": [], "slot_values": {package + "_ONLY": {"value": "fixed snapshot", "source_refs": [state.fact_ref]}}}
            if structured:
                draft["structured_template_ref"] = ref
            state.draft_ref = store.put_artifact(state.id, "availability-draft", draft)
        store.put_task(state, state.revision)
    return state


@pytest.mark.parametrize("package", PACKAGES)
@pytest.mark.parametrize("damage", ["missing", "unreadable"])
def test_management_keeps_unavailable_and_healthy_confirmed_templates(availability_env, package, damage):
    store, refs, _ = availability_env
    other = next(value for value in PACKAGES if value != package)
    local = store.store_for(package)
    healthy = local.get_artifact(refs[package])
    healthy["id"] += "_HEALTHY"
    healthy_ref = local.put_artifact("healthy", "availability-template", healthy)
    local.put_task(TaskState(id="healthy", kind="template", package=package, phase="template_confirmed", metadata={"confirmed_template_ref": healthy_ref}))
    damage_template(store, package, refs[package], damage)
    before = business_snapshot(store)
    items = {item["id"]: item for item in list_templates(local, package=package)}
    assert items[refs[package]]["artifact_status"] == damage
    assert ("文件缺失" if damage == "missing" else "文件不可读") in items[refs[package]]["reason"]
    assert items[refs[package]]["task_id"] == "template-" + package
    assert items[refs[package]]["status"] == "confirmed_by_human"
    assert items[healthy_ref]["artifact_status"] == "available"
    assert items[healthy_ref]["status"] == "confirmed_by_human" and items[healthy_ref]["usable_for_final"] is False
    assert refs[other] not in items
    assert business_snapshot(store) == before


@pytest.mark.parametrize("package", PACKAGES)
@pytest.mark.parametrize("damage", ["missing", "unreadable"])
def test_unavailable_create_rejected_before_task_parameters_or_idempotency(availability_env, package, damage):
    store, refs, queued = availability_env
    code = damage_template(store, package, refs[package], damage)
    before = business_snapshot(store)
    with TestClient(main.app) as client:
        response = client.post("/api/report-tasks", headers={"Idempotency-Key": "unavailable-" + package},
                               json={"package": package, "file_ids": ["fixture"], "template_ref": refs[package], "issue_number": 7, "publication_date": "2026-11-01"})
    assert response.status_code == 409 and response.json()["detail"] == code
    assert queued == [] and business_snapshot(store) == before


@pytest.mark.parametrize("package", PACKAGES)
def test_healthy_same_package_still_creates_despite_unusable_for_final_flag(availability_env, package):
    store, refs, queued = availability_env
    item = next(item for item in list_templates(store.store_for(package), package=package) if item["id"] == refs[package])
    assert item["usable_for_final"] is False and item["artifact_status"] == "available"
    with TestClient(main.app) as client:
        response = client.post("/api/report-tasks", json={"package": package, "file_ids": ["fixture"], "template_ref": refs[package]})
    assert response.status_code == 200, response.text
    state = store.get_task(response.json()["id"])
    assert state.package == package and state.template_ref == refs[package] and queued == [state.id]


@pytest.mark.parametrize("package", PACKAGES)
@pytest.mark.parametrize("structured", [True, False])
@pytest.mark.parametrize("damage", ["missing", "unreadable"])
def test_unavailable_managed_template_never_approved_even_without_marker(availability_env, monkeypatch, package, structured, damage):
    store, refs, _ = availability_env
    state = seed_report(store, package, refs[package], approval=True, structured=structured)
    code = damage_template(store, package, refs[package], damage)
    def forbidden(*args, **kwargs):
        raise AssertionError("unavailable template must not reach validation/export")
    monkeypatch.setattr(main, "validate_draft", forbidden)
    monkeypatch.setattr(main, "export_docx", forbidden)
    before = business_snapshot(store)
    with TestClient(main.app) as client:
        response = client.post("/api/tasks/" + state.id + "/approve", json={"draft_hash": "hash"})
    assert response.status_code == 409 and response.json()["detail"] == "report_incomplete:" + code
    assert business_snapshot(store) == before


@pytest.mark.parametrize("package", PACKAGES)
@pytest.mark.parametrize("damage", ["missing", "unreadable"])
def test_unavailable_preview_rejected_before_writing_phase_or_background(availability_env, monkeypatch, package, damage):
    store, refs, _ = availability_env
    state = seed_report(store, package, refs[package])
    code = damage_template(store, package, refs[package], damage)
    def forbidden(*args, **kwargs):
        raise AssertionError("unavailable preview must not be queued")
    monkeypatch.setattr(main, "generate_draft", forbidden)
    before = business_snapshot(store)
    with TestClient(main.app) as client:
        response = client.post("/api/tasks/" + state.id + "/preview-draft")
    assert response.status_code == 409 and response.json()["detail"] == code
    assert business_snapshot(store) == before


@pytest.mark.parametrize("package", PACKAGES)
@pytest.mark.parametrize("damage", ["missing", "unreadable"])
@pytest.mark.parametrize("entry", ["structured_writer", "writing_graph"])
def test_generation_entries_reject_before_body_artifacts_or_scope_writes(availability_env, monkeypatch, package, damage, entry):
    from app.structured_writer import write_structured_preview
    store, refs, _ = availability_env
    state = seed_report(store, package, refs[package])
    code = damage_template(store, package, refs[package], damage)
    def forbidden(*args, **kwargs):
        raise AssertionError("template validation must precede graph scope/model work")
    async def no_model(*args, **kwargs):
        raise AssertionError("real model forbidden")
    if entry == "writing_graph":
        monkeypatch.setattr(workflow, "_record_agent_scope", forbidden)
    before = business_snapshot(store)
    deps = workflow.Dependencies(store, no_model)
    with pytest.raises(ValueError, match="^" + code + "$"):
        with package_context(package):
            asyncio.run(write_structured_preview(deps, state.id) if entry == "structured_writer" else workflow.run_writing_graph(deps, state.id))
    assert business_snapshot(store) == before


@pytest.mark.parametrize("package", PACKAGES)
def test_healthy_preview_queues_only_stub_after_template_preflight(availability_env, monkeypatch, package):
    store, refs, _ = availability_env
    state = seed_report(store, package, refs[package])
    calls = []
    async def stub_generation(task_id):
        calls.append(task_id)
    monkeypatch.setattr(main, "generate_draft", stub_generation)
    with TestClient(main.app) as client:
        response = client.post("/api/tasks/" + state.id + "/preview-draft")
    assert response.status_code == 200, response.text
    assert calls == [state.id] and store.get_task(state.id).phase == "writing"
    assert store.get_task(state.id).draft_ref is None


@pytest.mark.parametrize("package", PACKAGES)
@pytest.mark.parametrize("damage", ["missing", "unreadable"])
def test_post_preflight_failure_keeps_explicit_error_without_body_artifacts(availability_env, package, damage):
    from app.api_views.writing import record_writing_failure
    from core.structured_template import TemplateArtifactUnavailable
    store, refs, _ = availability_env
    state = seed_report(store, package, refs[package])
    state.phase = "writing"
    store.put_task(state, state.revision)
    code = damage_template(store, package, refs[package], damage)
    before = business_snapshot(store)
    record_writing_failure(store, state, TemplateArtifactUnavailable(code))
    latest = store.get_task(state.id)
    after = business_snapshot(store)
    assert latest.phase == "facts_frozen" and latest.draft_ref is None
    assert latest.metadata["writing_error_code"] == code
    assert ("文件缺失" if damage == "missing" else "文件不可读") in latest.metadata["writing_error"]
    assert store.events(state.id)[-1]["error_code"] == code
    assert after["artifacts"] == before["artifacts"] and after["files"] == before["files"]
    assert after["auxiliary"] == before["auxiliary"]


@pytest.mark.parametrize("package", PACKAGES)
def test_creation_fixture_resolves_valid_input_in_requested_package(availability_env, package):
    from core.tools.ooxml import read_xlsx
    from core.tools import vocabulary
    store, _, _ = availability_env
    paths, resolved_package = main._resolve_files(["fixture"], package)
    expected = store.uploads_for(package) / "fixture.xlsx"
    assert resolved_package == package and paths == [str(expected)]
    book = read_xlsx(expected, sheet_index=vocabulary.sheet_index(package))
    assert book["rows"][0]["cells"] == vocabulary.required_columns(package)
    assert book["rows"][1]["cells"][0] == package



@pytest.mark.parametrize("package", PACKAGES)
@pytest.mark.parametrize("damage", ["missing", "unreadable"])
def test_source_precondition_precedes_template_preflight_without_writes(availability_env, monkeypatch, package, damage):
    from app.api_views import report_creation
    store, refs, queued = availability_env
    damage_template(store, package, refs[package], damage)
    def forbidden(*args, **kwargs):
        raise AssertionError("missing required input must reject before template preflight")
    monkeypatch.setattr(report_creation, "report_template", forbidden)
    before = business_snapshot(store)
    with TestClient(main.app) as client:
        response = client.post("/api/report-tasks", headers={"Idempotency-Key": "missing-source-" + package},
                               json={"package": package, "file_ids": ["absent-input"], "template_ref": refs[package],
                                     "issue_number": 7, "publication_date": "2026-11-01"})
    assert response.status_code == 404 and response.json()["detail"] == "file_not_found: absent-input"
    assert queued == [] and business_snapshot(store) == before


def test_frontend_filters_by_artifact_status_not_usable_for_final():
    source = (Path(__file__).resolve().parents[1] / "app/static/app.js").read_text(encoding="utf-8")
    helper = source.split("function templateArtifactUnavailable", 1)[1].split("async function loadTemplateLibrary", 1)[0]
    selector = source.split("async function loadTemplates", 1)[1].split("async function", 1)[0]
    assert "artifact_status" in helper and "missing" in helper and "unreadable" in helper
    assert "usable_for_final" not in helper and "usable_for_final" not in selector
    assert "!templateArtifactUnavailable(x)" in selector
    assert "文件缺失" in source and "edit.disabled=unavailable" in source
