# -*- coding: utf-8 -*-
"""Fallback plan and new-task event_scope come from the package, not a hardcoded Anshun list."""
from pathlib import Path

from app.fallback_policy import build_fallback_plan, event_scope_metadata, VERSION
from app.schemas import TaskState

ANSHUN_STEPS = [
    "import_records",
    "calculate_metrics",
    "filter_positive_scope",
    "filter_neutral_scope",
    "filter_records",
    "filter_warning_scope",
    "filter_union_scope",
    "resolve_locality",
    "group_events",
    "classify_records",
    "cluster_event_themes",
    "discover_topics",
    "select_materials",
]
ANSHUN_GOALS = {
    "import_records": [],
    "calculate_metrics": ["B17_sentiment_peak", "B26_platform"],
    "filter_positive_scope": ["positive_record_scope"],
    "filter_neutral_scope": ["neutral_record_scope"],
    "filter_records": ["negative_record_scope"],
    "filter_warning_scope": ["warning_record_scope"],
    "filter_union_scope": ["B30_categories_districts_top10"],
    "resolve_locality": ["B30_districts"],
    "group_events": ["B30_event_groups"],
    "classify_records": [],
    "cluster_event_themes": ["B30_categories"],
    "discover_topics": [],
    "select_materials": ["B30_top10_candidates"],
}
CLOSED_BY_FEATURE = {
    "locality": {"resolve_locality"},
    "classification": {"classify_records", "cluster_event_themes", "discover_topics"},
    "top10": {"select_materials"},
}


def _state(package, refs=None):
    return TaskState(id="t", package=package, kind="report", phase="processing", result_refs=refs or {}, metadata={})


def test_anshun_fallback_keeps_legacy_version_steps_and_goals():
    plan = build_fallback_plan(_state("anshun_monthly"), "model_not_configured")
    assert plan["version"] == "anshun-colored-fallback-v1"
    assert plan["steps"] == ANSHUN_STEPS
    assert plan["goal_by_step"] == ANSHUN_GOALS
    assert plan["status"] == "active"


def test_ruyuan_fallback_omits_closed_locality_and_has_no_anshun_slots():
    plan = build_fallback_plan(_state("ruyuan_yuebao"), "model_not_configured")
    assert "resolve_locality" not in plan["steps"]
    assert "classify_records" in plan["steps"]
    assert "select_materials" in plan["steps"]
    assert "import_records" in plan["steps"]
    joined = " ".join(name for names in plan["goal_by_step"].values() for name in names)
    assert "B17_" not in joined and "B26_" not in joined and "B30_" not in joined
    assert plan["version"] == VERSION


def test_longchuan_fallback_omits_closed_locality_classification_and_top10():
    plan = build_fallback_plan(_state("longchuan_yuebao"), "model_not_configured")
    assert "resolve_locality" not in plan["steps"]
    assert "classify_records" not in plan["steps"]
    assert "cluster_event_themes" not in plan["steps"]
    assert "discover_topics" not in plan["steps"]
    assert "select_materials" not in plan["steps"]
    assert "import_records" in plan["steps"]
    assert "group_events" in plan["steps"]
    joined = " ".join(name for names in plan["goal_by_step"].values() for name in names)
    assert "B30_" not in joined


def test_demo_b_fallback_does_not_borrow_anshun_slot_names():
    plan = build_fallback_plan(_state("demo_b"), "model_not_configured")
    assert plan["steps"]
    joined = " ".join(name for names in plan["goal_by_step"].values() for name in names)
    assert "B17_" not in joined and "B30_" not in joined
    assert plan["goal_by_step"]["filter_union_scope"] == ["negative_or_warning_record_scope"]


def test_event_scope_metadata_is_package_declared():
    anshun = event_scope_metadata("anshun_monthly")
    assert anshun["event_scope"] == "negative_or_warning"
    assert anshun["event_scope_confirmed"] is True
    assert anshun["event_scope_applies_to"] == "first_section_four_categories_districts_top10"
    assert anshun["event_scope_authority"] == "user_confirmed_2026_11_06"
    ruyuan = event_scope_metadata("ruyuan_yuebao")
    assert "event_scope_applies_to" not in ruyuan
    assert "event_scope_authority" not in ruyuan
    longchuan = event_scope_metadata("longchuan_yuebao")
    assert "first_section_four_categories_districts_top10" not in longchuan.values()


def test_base_no_longer_hardcodes_anshun_event_scope_or_fallback_id():
    root = Path(__file__).resolve().parents[1]
    main = (root / "app" / "main.py").read_text(encoding="utf-8")
    policy = (root / "app" / "fallback_policy.py").read_text(encoding="utf-8")
    assert "first_section_four_categories_districts_top10" not in main
    assert "user_confirmed_2026_11_06" not in main
    assert "anshun-colored-fallback-v1" not in policy
    assert "B30_categories_districts_top10" not in policy
