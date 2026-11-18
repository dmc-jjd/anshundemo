# -*- coding: utf-8 -*-
"""Built-in slot templates are package-declared; other packages must not see the Anshun baseline."""
from pathlib import Path

from app.api_views.template_library import list_templates
from app.template_engine import builtin_templates, is_slot_template, template_engine, SLOT_TEMPLATE, STRUCTURED_TEMPLATE


def test_anshun_builtin_slot_template_is_package_declared():
    items = builtin_templates("anshun_monthly")
    assert items and items[0]["id"]
    assert items[0]["name"] == "安顺月报 · 五色逐项占位模板"
    assert items[0]["status"] == "candidate_requires_review"
    assert items[0]["usable_for_final"] is False
    assert "engine" not in items[0]
    slot_id = items[0]["id"]
    assert is_slot_template(slot_id, "anshun_monthly")
    assert template_engine(slot_id, "anshun_monthly") == SLOT_TEMPLATE


def test_ruyuan_and_longchuan_libraries_omit_anshun_slot_template():
    anshun_id = builtin_templates("anshun_monthly")[0]["id"]
    for package in ("ruyuan_yuebao", "longchuan_yuebao", "demo_b"):
        assert all(item["id"] != anshun_id for item in builtin_templates(package))
        assert all(item["id"] != anshun_id for item in list_templates(_EmptyStore(), package=package))


class _EmptyStore:
    def list_tasks(self):
        return []


def test_structured_refs_are_not_slot_engine():
    assert is_slot_template("template_version-5bd58d920e99b82e8884", "ruyuan_yuebao") is False
    assert template_engine("template_version-5bd58d920e99b82e8884") == STRUCTURED_TEMPLATE


def test_business_code_has_no_colored_template_id_literal():
    root = Path(__file__).resolve().parents[1]
    hits = []
    for folder in ("app", "core"):
        for path in (root / folder).rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".py", ".js", ".html", ".yaml", ".yml", ".json"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "anshun-monthly-colored" in text:
                hits.append(str(path.relative_to(root)))
    assert hits == []
