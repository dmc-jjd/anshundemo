"""Offline routing regressions: temporary stores, no models or external network."""
import asyncio
import copy
import hashlib
import socket
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main
import app.workflow as workflow
from core.package_store import PackageStores
from core.packages.context import package_context
from core.schemas import TaskState
from core.structured_template import _schema

PACKAGES = ("anshun_monthly", "ruyuan_yuebao")

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    original = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_lookup = socket.getaddrinfo
    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost"):
            return original(sock, address)
        raise AssertionError("external network forbidden")
    def local_connect_ex(sock, address):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost"):
            return original_connect_ex(sock, address)
        raise AssertionError("external network forbidden")
    def local_lookup(host, *args, **kwargs):
        if host in ("127.0.0.1", "::1", "localhost", None):
            return original_lookup(host, *args, **kwargs)
        raise AssertionError("external DNS forbidden")
    monkeypatch.setattr(socket.socket, "connect", local_only)
    monkeypatch.setattr(socket.socket, "connect_ex", local_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", local_lookup)
    async def forbidden(*args, **kwargs):
        raise AssertionError("real agent/tool forbidden")
    monkeypatch.setattr(workflow, "execute_tool", forbidden)
    monkeypatch.setattr(workflow, "invoke_agent", forbidden)
    store = PackageStores(tmp_path / "stores")
    refs = {}
    for package in PACKAGES:
        with package_context(package):
            tid = "template-" + package
            store.put_task(TaskState(id=tid, kind="template", package=package, phase="template_confirmed"))
            field = {"id": package + "_ONLY", "owner": "writer", "semantic": package,
                     "display_name": "fixture", "kind": "text", "value_schema": {"type": "string", "minLength": 1}}
            template = {"id": package + "_TEMPLATE", "status": "confirmed_by_human",
                        "source_reports": [{"sha256": "a"}, {"sha256": "b"}], "comparison_ref": "fixture",
                        "fields": [field], "blocks": [{"index": 0, "kind": "paragraph", "parts": [{"field": field["id"]}]}],
                        "output_schema": _schema([field]), "writer_schema": _schema([field], True), "rules": {}}
            refs[package] = store.put_artifact(tid, "template_version", template)
        folder = store.uploads_for(package)
        folder.mkdir(parents=True)
        (folder / "fixture.xlsx").write_bytes(b"offline-stub-not-imported")
    queued = []
    async def background(deps, task_id):
        queued.append(task_id)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "deps", workflow.Dependencies(store))
    monkeypatch.setattr(main, "run_report_graph", background)
    return store, refs, queued


def counts(store):
    artifacts = 0
    for local in store._stores.values():
        with local.connect() as connection:
            artifacts += connection.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
    return len(store.list_tasks()), artifacts


def business_snapshot(store):
    """Warm stores first; compare business rows/events and non-SQLite bytes."""
    tasks = {t.id: t.model_dump(mode="json") for t in store.list_tasks()}
    events = {tid: store.events(tid) for tid in tasks}
    locals_ = list(store._stores.values()) if hasattr(store, "_stores") else [store]
    artifacts, files, auxiliary = {}, {}, {}
    for local in locals_:
        connection = local.connect()
        try:
            artifacts[str(local.db)] = [dict(r) for r in connection.execute("SELECT * FROM artifacts ORDER BY id")]
            auxiliary[str(local.db)] = {
                "idempotency": [dict(r) for r in connection.execute("SELECT * FROM idempotency ORDER BY key")],
                "review_drafts": [dict(r) for r in connection.execute("SELECT * FROM review_drafts ORDER BY task_id")],
            }
        finally:
            connection.close()
        for path in local.files.parent.rglob("*"):
            if not path.is_file() or path == local.db or path.name.startswith(local.db.name + "-"):
                continue
            files[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"tasks": tasks, "events": events, "artifacts": artifacts, "files": files, "auxiliary": auxiliary}


@pytest.mark.parametrize("package", PACKAGES)
@pytest.mark.parametrize("case", ["valid", "omitted", "null", "blank", "invalid", "unconfirmed_artifact", "cross_artifact", "local_builtin", "foreign_builtin"])
def test_api_reference_ownership_and_no_rejection_writes(isolated, monkeypatch, package, case):
    store, refs, queued = isolated
    other = next(p for p in PACKAGES if p != package)
    monkeypatch.setenv("REPORT_PACKAGE", other)
    monkeypatch.setattr(main, "UPLOADS", store.uploads_for(other))
    body = {"file_ids": ["fixture"], "package": package, "mode": "dynamic"}
    value = {"valid": refs[package], "null": None, "blank": "  ", "invalid": "missing-template",
             "cross_artifact": refs[other], "local_builtin": "anshun-monthly-colored" if package == "anshun_monthly" else "undeclared-builtin",
             "foreign_builtin": "anshun-monthly-colored" if package != "anshun_monthly" else "undeclared-builtin"}.get(case)
    if case == "unconfirmed_artifact":
        value = store.store_for(package).put_artifact("template-" + package, "unconfirmed-template", {"status": "candidate_requires_review"})
    if case != "omitted":
        body["template_ref"] = value
    accepted = case == "valid" or (case == "local_builtin" and package == "anshun_monthly")
    before = counts(store)
    before_business = business_snapshot(store)
    with TestClient(main.app) as client:
        response = client.post("/api/report-tasks", json=body)
    if accepted:
        assert response.status_code == 200, response.text
        state = store.get_task(response.json()["id"])
        assert state.package == package and state.template_ref == value
        assert state.metadata["sheet_index"] == (3 if package == "anshun_monthly" else 1)
        assert len(queued) == 1 and counts(store) == (before[0] + 1, before[1])
    else:
        if case == "null":
            assert response.status_code == 422, response.text
            assert response.json()["detail"][0]["type"] == "string_type"
        else:
            assert response.status_code == 409, response.text
            expected_code = ("template_artifact_missing" if case in
                             ("invalid", "cross_artifact", "local_builtin", "foreign_builtin")
                             else "confirmed_two_report_template_required")
            assert response.json()["detail"] == expected_code
        assert counts(store) == before and queued == []
        assert business_snapshot(store) == before_business


@pytest.mark.parametrize("package", ["anshun_monthly", "ruyuan_yuebao", "longchuan_yuebao"])
def test_request_package_controls_feature_snapshot(isolated, monkeypatch, package):
    store, refs, queued = isolated
    monkeypatch.setenv("REPORT_PACKAGE", "anshun_monthly")
    monkeypatch.setattr(main, "UPLOADS", store.uploads_for("anshun_monthly"))
    if package == "longchuan_yuebao":
        with package_context(package):
            template = store.get_artifact(refs["ruyuan_yuebao"])
            store.put_task(TaskState(id="longchuan-template", kind="template", package=package, phase="template_confirmed"))
            refs[package] = store.put_artifact("longchuan-template", "template_version", template)
        folder = store.uploads_for(package)
        folder.mkdir(parents=True)
        (folder / "fixture.xlsx").write_bytes(b"stub")
    with package_context("anshun_monthly"), TestClient(main.app) as client:
        response = client.post("/api/report-tasks", json={"package": package, "file_ids": ["fixture"], "template_ref": refs[package]})
    assert response.status_code == 200, response.text
    state = store.get_task(response.json()["id"])
    expected = package == "anshun_monthly"
    assert state.metadata["template_rules"]["features"]["locality"] is expected
    with package_context(package):
        features = workflow.effective_features(store, state)
        assert features["locality"] is expected
        assert ("resolve_locality" in workflow._processing_policy(features).allow) is expected
        assert ("resolve_locality" in workflow._disabled_steps(features)) is not expected


@pytest.mark.parametrize("package", PACKAGES)
@pytest.mark.parametrize("case", ["valid", "missing", "invalid", "cross"])
def test_internal_planner_goals_or_explicit_failure(isolated, monkeypatch, package, case):
    frozen_at = "2026-11-18T04:00:00+00:00"
    monkeypatch.setattr("core.timing.stamp", lambda: frozen_at)
    store, refs, _ = isolated
    other = next(p for p in PACKAGES if p != package)
    ref = {"valid": refs[package], "missing": None, "invalid": "missing-template", "cross": refs[other]}[case]
    calls = []
    async def planner(role, payload, *args, **kwargs):
        assert role == "data_processor"
        calls.append(payload)
        return SimpleNamespace(action="finish_processing")
    monkeypatch.setattr(workflow, "invoke_agent", planner)
    with package_context(package):
        state = TaskState(id="report", kind="report", package=package, phase="queued", template_ref=ref, metadata={"mode": "dynamic"})
        store.put_task(state)
        seed = store.put_artifact(state.id, "seed", {"records": []})
        state.result_refs = {k: seed for k in workflow._needed_refs(workflow.effective_features(store, state))}
        store.put_task(state, state.revision)
        before = counts(store)
        before_business = business_snapshot(store)
        asyncio.run(workflow._process_records(workflow.Dependencies(store, planner), state.id))
        latest = store.get_task(state.id)
    accepted = case == "valid" or (case == "missing" and package == "anshun_monthly")
    if accepted:
        assert len(calls) == 1
        ids = [f["id"] for f in calls[0]["slot_goals"]]
        assert ids == [package + "_ONLY"] if case == "valid" else len(ids) == 99
        assert calls[0]["input"]["sheet_index"] == (3 if package == "anshun_monthly" else 1)
        assert latest.fallback is None and latest.phase == "processing"
    else:
        assert calls == [] and latest.phase == "failed"
        expected_code = "confirmed_two_report_template_required" if case == "missing" else "template_artifact_missing"
        assert latest.metadata["planning_error"] == expected_code
        after_business = business_snapshot(store)
        assert after_business["artifacts"] == before_business["artifacts"]
        assert after_business["files"] == before_business["files"]
        assert after_business["auxiliary"] == before_business["auxiliary"]
        assert latest.revision == before_business["tasks"][state.id]["revision"] + 1
        assert latest.planning_calls == 0
        expected_state = before_business["tasks"][state.id].copy()
        expected_state.update(phase="failed", revision=latest.revision)
        expected_state["metadata"] = {**expected_state["metadata"], "planning_error": latest.metadata["planning_error"]}
        expected_timing = copy.deepcopy(expected_state["metadata"]["timing"])
        expected_timing["segments"][-1]["ended_at"] = frozen_at
        expected_timing["segments"].append({"phase": "failed", "started_at": frozen_at})
        expected_state["metadata"]["timing"] = expected_timing
        assert after_business["tasks"] == {**before_business["tasks"], state.id: expected_state}
        assert after_business["events"][state.id][:-1] == before_business["events"][state.id]
        assert after_business["events"][state.id][-1]["type"] == "planning_error"
    assert latest.fact_ref is None and latest.draft_ref is None
    assert latest.result_refs == state.result_refs and counts(store) == before


def test_empty_legacy_package_uses_configured_context():
    with package_context("ruyuan_yuebao"):
        assert workflow._sheet_index(SimpleNamespace(package="", metadata={})) == 1


def test_structured_planner_needs_no_slot_layout(isolated, monkeypatch):
    from core import paths
    store, refs, _ = isolated
    def no_layout(*args, **kwargs):
        raise RuntimeError("template_dir_missing:fixture")
    monkeypatch.setattr(paths, "template_dir", no_layout)
    calls = []
    async def planner(role, payload, *args, **kwargs):
        calls.append(payload)
        return SimpleNamespace(action="finish_processing")
    monkeypatch.setattr(workflow, "invoke_agent", planner)
    with package_context("ruyuan_yuebao"):
        state = TaskState(id="report", kind="report", package="ruyuan_yuebao", phase="queued", template_ref=refs["ruyuan_yuebao"], metadata={"mode": "dynamic"})
        store.put_task(state)
        seed = store.put_artifact(state.id, "seed", {"records": []})
        state.result_refs = {k: seed for k in workflow._needed_refs(workflow.effective_features(store, state))}
        store.put_task(state, state.revision)
        asyncio.run(workflow._process_records(workflow.Dependencies(store, planner), state.id))
    assert len(calls) == 1 and calls[0]["template_id"] == "ruyuan_yuebao_TEMPLATE"


def test_failed_reference_stops_the_entire_report_graph(isolated, monkeypatch):
    store, _, _ = isolated
    def forbidden(*args, **kwargs):
        raise AssertionError("failed binding must not enter analysis/review")
    monkeypatch.setattr(workflow, "_analyse_report_events", forbidden)
    monkeypatch.setattr(workflow, "_await_data_review", forbidden)
    with package_context("anshun_monthly"):
        state = TaskState(id="bad-graph", kind="report", package="anshun_monthly", phase="queued", template_ref="missing", metadata={"mode": "dynamic"})
        store.put_task(state)
        seed = store.put_artifact(state.id, "seed", {"records": []})
        state.result_refs = {k: seed for k in workflow._needed_refs(workflow.effective_features(store, state))}
        store.put_task(state, state.revision)
        before_business = business_snapshot(store)
        asyncio.run(workflow.run_report_graph(workflow.Dependencies(store), state.id))
    latest = store.get_task(state.id)
    after_business = business_snapshot(store)
    assert after_business["files"] == before_business["files"]
    assert after_business["artifacts"] == before_business["artifacts"]
    assert after_business["auxiliary"] == before_business["auxiliary"]
    assert latest.phase == "failed" and latest.planning_calls == 0
    assert latest.fact_ref is None and latest.draft_ref is None


def test_slot_planner_reports_a_genuinely_missing_layout(isolated, monkeypatch):
    from core import paths
    from app.report_planning import planning_template
    store, _, _ = isolated
    def no_layout(*args, **kwargs):
        raise RuntimeError("template_dir_missing:fixture")
    monkeypatch.setattr(paths, "template_dir", no_layout)
    state = TaskState(id="slot", kind="report", package="anshun_monthly", phase="queued", template_ref="anshun-monthly-colored")
    with pytest.raises(RuntimeError, match="template_dir_missing:fixture"):
        planning_template(store, state, state.package)


def test_task_package_precedence_and_unconfigured_failure(monkeypatch):
    import contextvars
    from core.task_package import resolve_task_package
    from core.packages import context
    state = SimpleNamespace(id="legacy", package="  ")
    store = SimpleNamespace(package_of=lambda tid: "ruyuan_yuebao", package="anshun_monthly")
    with package_context("longchuan_yuebao"):
        assert resolve_task_package("anshun_monthly", state=state, store=store) == "anshun_monthly"
        assert resolve_task_package(state=SimpleNamespace(package="ruyuan_yuebao"), store=store) == "ruyuan_yuebao"
        assert resolve_task_package(state=state, store=store) == "ruyuan_yuebao"
        assert resolve_task_package(state=state) == "longchuan_yuebao"
    monkeypatch.setattr(context, "_ref", contextvars.ContextVar("unconfigured", default=None))
    monkeypatch.delenv("REPORT_PACKAGE", raising=False)
    with pytest.raises(context.PackageNotSpecified):
        resolve_task_package(state=state)


def test_request_parameters_artifact_stays_in_task_package(isolated, monkeypatch):
    store, refs, _ = isolated
    package = "ruyuan_yuebao"
    monkeypatch.setattr(main, "UPLOADS", store.uploads_for("anshun_monthly"))
    with package_context("anshun_monthly"), TestClient(main.app) as client:
        response = client.post("/api/report-tasks", json={"package": package, "file_ids": ["fixture"], "template_ref": refs[package], "issue_number": 3})
    assert response.status_code == 200, response.text
    state = store.get_task(response.json()["id"])
    ref = state.metadata["report_parameters_ref"]
    assert store.store_for(package).get_artifact(ref)["parameters"] == {"issue_number": 3}
    with pytest.raises(KeyError):
        store.store_for("anshun_monthly").get_artifact(ref)


@pytest.mark.parametrize("package", PACKAGES)
@pytest.mark.parametrize("case", ["valid", "missing", "cross", "mismatch"])
def test_approval_validates_local_template_before_export(isolated, tmp_path, monkeypatch, case, package):
    store, refs, _ = isolated
    other = next(value for value in PACKAGES if value != package)
    import hashlib
    import zipfile
    layout = tmp_path / "approval-layout.docx"
    with zipfile.ZipFile(layout, "w") as archive:
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>snapshot</w:t></w:r></w:p></w:body></w:document>')
    template = store.store_for(package).get_artifact(refs[package])
    template["layout_source"] = str(layout)
    template["source_reports"][0]["sha256"] = hashlib.sha256(layout.read_bytes()).hexdigest()
    local_ref = store.store_for(package).put_artifact("template-" + package, "template_version", template)
    task_ref = {"valid": local_ref, "missing": "missing", "cross": refs[other], "mismatch": local_ref}[case]
    draft_template = "other" if case == "mismatch" else task_ref
    with package_context(package):
        state = TaskState(id="approve", kind="report", package=package, phase="awaiting_final_review", template_ref=task_ref)
        store.put_task(state)
        state.fact_ref = store.put_artifact(state.id, "facts", {"metrics": {}})
        draft = {"id": "d", "template_ref": task_ref, "structured_template_ref": draft_template, "fact_ref": state.fact_ref, "content_hash": "hash", "sections": [],
                 "slot_values": {package + "_ONLY": {"value": "fixed snapshot", "source_refs": [state.fact_ref]}}, "chart_refs": {}}
        state.draft_ref = store.put_artifact(state.id, "draft_version", draft)
        store.put_task(state, state.revision)
    exports = []
    monkeypatch.setattr(main, "validate_draft", lambda *args: [])
    monkeypatch.setattr(main, "export_docx", lambda *args, **kwargs: exports.append((args, kwargs)))
    before = counts(store)
    before_business = business_snapshot(store)
    with TestClient(main.app) as client:
        response = client.post("/api/tasks/approve/approve", json={"draft_hash": "hash"})
    assert response.status_code == 409, response.text
    if case == "valid":
        assert response.json()["detail"] == "writing_review_required" and len(exports) == 1
        args, kwargs = exports[0]
        assert args[0]["content_hash"] == "hash" and args[1] == {"metrics": {}}
        assert args[2] is None and args[3] == "final" and args[4] == []
        assert kwargs["local_store"] is store
        assert kwargs["features"]["locality"] is (package == "anshun_monthly")
    else:
        assert response.json()["detail"].startswith("report_incomplete:") and exports == []
    assert counts(store) == before and store.get_task(state.id).phase == "awaiting_final_review"
    assert business_snapshot(store) == before_business


def test_confirmed_template_without_display_id_uses_immutable_reference(isolated):
    from app.report_planning import planning_template
    store, refs, _ = isolated
    package = "ruyuan_yuebao"
    local = store.store_for(package)
    template = local.get_artifact(refs[package])
    template.pop("id")
    ref = local.put_artifact("template-" + package, "template_version", template)
    state = TaskState(id="legacy-structured", kind="report", package=package, phase="queued", template_ref=ref)
    assert planning_template(store, state, package)["template_id"] == ref


def test_empty_legacy_package_selects_only_configured_builtin():
    from app.template_engine import is_slot_template
    with package_context("anshun_monthly"):
        assert is_slot_template("anshun-monthly-colored", "") is True
    with package_context("ruyuan_yuebao"):
        assert is_slot_template("anshun-monthly-colored", "") is False


@pytest.mark.parametrize("package", PACKAGES)
def test_body_header_package_mismatch_has_no_task_or_artifact_side_effect(isolated, package):
    store, refs, queued = isolated
    other = next(p for p in PACKAGES if p != package)
    before = counts(store)
    before_business = business_snapshot(store)
    with TestClient(main.app) as client:
        response = client.post("/api/report-tasks", headers={"X-Report-Package": other}, json={"package": package, "file_ids": ["fixture"], "template_ref": refs[package]})
    assert response.status_code == 400 and response.json()["detail"] == "package_mismatch"
    assert counts(store) == before and queued == []
    assert business_snapshot(store) == before_business


@pytest.mark.parametrize("store_package", PACKAGES)
@pytest.mark.parametrize("request_package", PACKAGES)
@pytest.mark.parametrize("kind", ["structured", "builtin", "legacy_default"])
def test_single_store_ownership_precedes_all_template_successes(isolated, tmp_path, store_package, request_package, kind):
    from app.storage import Store
    from app.template_engine import report_template
    store, refs, _ = isolated
    local = Store(tmp_path / "single", package=store_package)
    template = store.store_for(store_package).get_artifact(refs[store_package])
    structured_ref = local.put_artifact("template", "confirmed", template)
    ref = structured_ref if kind == "structured" else "anshun-monthly-colored" if kind == "builtin" else None
    before = business_snapshot(local)
    if store_package != request_package:
        with pytest.raises(ValueError, match="^template_package_mismatch$"):
            report_template(local, ref, request_package, allow_legacy_builtin=kind == "legacy_default")
    elif kind == "structured":
        selected, definition = report_template(local, ref, request_package)
        assert selected == ref and definition["fields"][0]["id"] == store_package + "_ONLY"
    elif request_package == "anshun_monthly":
        assert report_template(local, ref, request_package, allow_legacy_builtin=kind == "legacy_default") == ("anshun-monthly-colored", None)
    else:
        expected_code = "template_artifact_missing" if kind == "builtin" else "confirmed_two_report_template_required"
        with pytest.raises(ValueError, match="^" + expected_code + "$"):
            report_template(local, ref, request_package, allow_legacy_builtin=kind == "legacy_default")
    assert business_snapshot(local) == before


@pytest.mark.parametrize("package", PACKAGES)
@pytest.mark.parametrize("kind", ["generic_legacy", "slot_without_marker", "structured_without_marker"])
def test_approval_rejects_wrong_single_store_even_without_structured_marker(isolated, tmp_path, package, kind):
    from app.api_views.approval import approval_gate
    from app.storage import Store
    source, refs, _ = isolated
    other = next(value for value in PACKAGES if value != package)
    local = Store(tmp_path / "wrong-owner", package=other)
    if kind == "generic_legacy":
        ref = "opaque-old-generic-reference"
    elif kind == "slot_without_marker":
        ref = "anshun-monthly-colored"
    else:
        ref = local.put_artifact("template", "template", source.store_for(other).get_artifact(refs[other]))
    fact = local.put_artifact("legacy", "facts", {"metrics": {}})
    draft = {"id": "d", "template_ref": ref, "fact_ref": fact, "content_hash": "hash", "sections": [], "slot_values": {}}
    draft_ref = local.put_artifact("legacy", "draft", draft)
    state = TaskState(id="legacy", kind="report", package=package, phase="awaiting_final_review", template_ref=ref, fact_ref=fact, draft_ref=draft_ref)
    local.put_task(state)
    calls = []
    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("ownership rejection must precede validation/export")
    before = business_snapshot(local)
    error, result = approval_gate(local, state, SimpleNamespace(draft_hash="hash"), validate_draft=forbidden, export_docx=forbidden)
    assert error == (409, "report_incomplete:template_package_mismatch") and result is None
    assert calls == [] and business_snapshot(local) == before


@pytest.mark.parametrize("package", PACKAGES)
def test_owned_generic_legacy_reference_keeps_existing_review_gate(isolated, tmp_path, package):
    from app.api_views.approval import approval_gate
    from app.storage import Store
    local = Store(tmp_path / "generic-legacy", package=package)
    fact = local.put_artifact("legacy", "facts", {"metrics": {}})
    draft = {"id": "d", "template_ref": "opaque-old-generic-reference", "fact_ref": fact, "content_hash": "hash", "sections": [], "slot_values": {}}
    draft_ref = local.put_artifact("legacy", "draft", draft)
    state = TaskState(id="legacy", kind="report", package=package, phase="awaiting_final_review", template_ref=draft["template_ref"], fact_ref=fact, draft_ref=draft_ref)
    local.put_task(state)
    validations, exports = [], []
    def validate(*args):
        validations.append(args)
        return []
    before = business_snapshot(local)
    error, result = approval_gate(local, state, SimpleNamespace(draft_hash="hash"), validate_draft=validate, export_docx=lambda *a, **kw: exports.append((a, kw)))
    assert error == (409, "writing_review_required") and result is None
    assert len(validations) == 1 and exports == [] and business_snapshot(local) == before


@pytest.mark.parametrize("package", PACKAGES)
@pytest.mark.parametrize("damage", ["invalid_json", "missing_field_owner"])
def test_malformed_planner_template_fails_without_body_or_artifact_writes(isolated, package, damage):
    store, refs, _ = isolated
    local = store.store_for(package)
    template = local.get_artifact(refs[package])
    if damage == "missing_field_owner":
        template["fields"][0].pop("owner")
    ref = local.put_artifact("template-" + package, "malformed-planner-template", template)
    if damage == "invalid_json":
        (local.files / (ref + ".json")).write_text("{not-valid-json", encoding="utf-8")
    state = TaskState(id="malformed", kind="report", package=package, phase="queued", template_ref=ref, metadata={"mode": "dynamic"})
    store.put_task(state)
    before = business_snapshot(store)
    with package_context(package):
        asyncio.run(workflow._process_records(workflow.Dependencies(store), state.id))
    latest = store.get_task(state.id)
    after = business_snapshot(store)
    assert latest.phase == "failed" and latest.planning_calls == latest.tool_calls == 0
    assert latest.fact_ref is None and latest.draft_ref is None and latest.result_refs == {}
    assert latest.metadata["planning_error"]
    assert latest.revision == before["tasks"][state.id]["revision"] + 1
    assert after["files"] == before["files"] and after["artifacts"] == before["artifacts"]
    assert after["auxiliary"] == before["auxiliary"]
    assert after["events"][state.id][:-1] == before["events"][state.id]
    assert after["events"][state.id][-1]["type"] == "planning_error"


def test_owned_slot_without_structured_marker_keeps_existing_review_gate(isolated, tmp_path):
    from app.api_views.approval import approval_gate
    from app.slot_writer import writer_slot_ids
    from app.storage import Store
    package = "anshun_monthly"  # only this package currently declares a slot builtin
    local = Store(tmp_path / "owned-slot", package=package)
    fact = local.put_artifact("slot", "facts", {"metrics": {}})
    with package_context(package):
        values = {field_id: {"value": "fixed snapshot", "source_refs": [fact]} for field_id in writer_slot_ids()}
    assert values
    draft = {"id": "d", "template_ref": "anshun-monthly-colored", "fact_ref": fact, "content_hash": "hash", "sections": [], "slot_values": values}
    draft_ref = local.put_artifact("slot", "draft", draft)
    state = TaskState(id="slot", kind="report", package=package, phase="awaiting_final_review", template_ref=draft["template_ref"], fact_ref=fact, draft_ref=draft_ref)
    local.put_task(state)
    validations, exports = [], []
    def validate(*args):
        validations.append(args)
        return []
    before = business_snapshot(local)
    with package_context(package):
        error, result = approval_gate(local, state, SimpleNamespace(draft_hash="hash"), validate_draft=validate, export_docx=lambda *a, **kw: exports.append((a, kw)))
    assert error == (409, "writing_review_required") and result is None
    assert len(validations) == 1 and exports == [] and business_snapshot(local) == before
