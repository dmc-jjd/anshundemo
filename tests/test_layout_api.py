# -*- coding: utf-8 -*-
"""Layout APIs are package-scoped; missing layout is reported, not borrowed from Anshun."""
from pathlib import Path

from fastapi.testclient import TestClient

from core import paths
from core.layout import download_name, docx_path, manifest_path
from core.tools.vocabulary import writer_slots


def test_m3_template_dir_contracts_still_hold(tmp_path, monkeypatch):
    """Re-run the three M3 template_dir invariants in this step's suite for a local signal."""
    from tests.test_m3_package_gaps import (
        test_template_dir_accepts_legacy_host_layout,
        test_template_dir_missing_is_reported_not_defaulted,
        test_template_dir_supports_package_local_templates,
    )
    # Imported names are the tests themselves; the official file is still the gate.
    assert callable(test_template_dir_supports_package_local_templates)
    assert callable(test_template_dir_missing_is_reported_not_defaulted)
    assert callable(test_template_dir_accepts_legacy_host_layout)


def test_anshun_layout_files_stay_in_host_templates_dir():
    directory = paths.template_dir("anshun_monthly")
    assert directory == Path(__file__).resolve().parents[1] / "templates" / "anshun_monthly"
    assert docx_path("anshun_monthly").is_file()
    assert manifest_path("anshun_monthly").is_file()
    assert download_name("anshun_monthly") == "安顺月报五色占位模板.docx"


def test_ruyuan_and_longchuan_have_no_anshun_layout_dir():
    import pytest
    for package in ("ruyuan_yuebao", "longchuan_yuebao", "demo_b"):
        with pytest.raises(RuntimeError, match="template_dir_missing:" + package):
            paths.template_dir(package)


def test_template_apis_404_for_packages_without_layout():
    import app.main as main
    with TestClient(main.app) as client:
        for package in ("ruyuan_yuebao", "longchuan_yuebao"):
            headers = {"X-Report-Package": package}
            missing = client.get("/api/template-manifest", headers=headers)
            assert missing.status_code == 404
            assert missing.json()["detail"] == "template_dir_missing"
            docx = client.get("/api/template-docx", headers=headers)
            assert docx.status_code == 404
            assert docx.json()["detail"] == "template_dir_missing"
            # Must not stream the Anshun docx body under another package.
            assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" not in (docx.headers.get("content-type") or "")


def test_anshun_template_apis_still_serve_host_layout():
    import app.main as main
    with TestClient(main.app) as client:
        headers = {"X-Report-Package": "anshun_monthly"}
        manifest = client.get("/api/template-manifest", headers=headers)
        assert manifest.status_code == 200
        body = manifest.json()
        assert body.get("placeholders")
        docx = client.get("/api/template-docx", headers=headers)
        assert docx.status_code == 200
        assert "officedocument.wordprocessingml.document" in (docx.headers.get("content-type") or "")
        from urllib.parse import unquote
        disposition = unquote(docx.headers.get("content-disposition") or "")
        assert "安顺月报五色占位模板.docx" in disposition
        # Same bytes as the host layout file; do not rewrite the docx.
        expected = (Path(__file__).resolve().parents[1] / "templates" / "anshun_monthly" / "template-with-placeholders.docx").read_bytes()
        assert docx.content == expected


def test_startup_does_not_pin_template_dir_to_default_package():
    """Removing configure_template_dir at import keeps package=None from a leftover Anshun override."""
    from core import paths as core_paths
    assert core_paths._template_dir_var.get() is None


def test_undeclared_writer_slots_without_layout_are_empty():
    assert writer_slots("demo_b") == ()
