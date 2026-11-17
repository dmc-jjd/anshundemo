# -*- coding: utf-8 -*-
"""Package-configurable second-section policy; default Anshun behavior stays intact."""
from pathlib import Path

import pytest
import yaml

from app.section_two import role, forecast_window, validate_history, source_excerpts, HistoryTopic, HistoryCitation, HistoricalResearch
from core import section_policy
from test_frozen_writer import fixture
from app.frozen_report import FrozenReport


def test_default_roles_match_legacy_heuristics():
    assert role({"id": "monthly_recommendations", "kind": "paragraph"}) == "outlook"
    assert role({"id": "numbered_items_1", "kind": "paragraph_list", "display_name": "编号条目列表（第1组）"}) == "outlook"
    assert role({"id": "b40_analysis_paragraph", "kind": "analysis", "display_name": "研判"}) == "analysis"
    assert role({"id": "x", "kind": "analysis", "display_name": "综合研判分析"}) == "analysis"
    assert role({"id": "b46_risk_tip_1", "kind": "analysis", "display_name": "第1条风险提示"}) is None
    assert role({"id": "b32_overall_suggestion", "kind": "analysis", "display_name": "综合工作建议"}) is None


def test_field_roles_override_paragraph_list_and_assign_outlook():
    policy = {
        "field_roles": {
            "numbered_items_1": "general",
            "b46_risk_tip_1": "outlook",
        }
    }
    assert role({"id": "numbered_items_1", "kind": "paragraph_list"}, policy=policy) is None
    assert role({"id": "b46_risk_tip_1", "kind": "analysis", "display_name": "第1条风险提示"}, policy=policy) == "outlook"
    # Unmentioned fields keep the built-in default.
    assert role({"id": "monthly_recommendations", "kind": "paragraph_list"}, policy=policy) == "outlook"


def test_invalid_field_role_is_rejected():
    with pytest.raises(ValueError, match="field_roles"):
        role({"id": "x", "kind": "analysis"}, policy={"field_roles": {"x": "outlooks"}})


def test_forecast_window_default_region_unchanged(tmp_path):
    store, _ = fixture(tmp_path)
    window = forecast_window(FrozenReport(store, "r"))
    assert window["region"] == "安顺市"
    assert window["periods"] == ["2026-11", "2026-12"]


def test_forecast_window_uses_configured_region(tmp_path, monkeypatch):
    store, _ = fixture(tmp_path)
    monkeypatch.setattr(section_policy, "load", lambda package=None: {"locality_evidence": {"region": "示例县"}})
    window = forecast_window(FrozenReport(store, "r"))
    assert window["region"] == "示例县"


def test_validate_history_vocabulary_names_do_not_require_default_place(tmp_path, monkeypatch):
    store, _ = fixture(tmp_path)
    vocab = {"示例县": ["示例县", "示例"]}
    monkeypatch.setattr("core.tools.vocabulary.localities", lambda package=None: vocab)
    policy = {"locality_evidence": {"from_vocabulary": True, "region": "示例县"}}
    window = forecast_window(FrozenReport(store, "r"))
    quote = "示例县2025年11月道路交通问题多发，相关部门提示做好前置风险防范。"
    ref = store.put_artifact("r", "historical_page", {
        "url": "https://www.example.gov.cn/road",
        "title": "道路",
        "published_at": "2025-11-15T08:00:00+00:00",
        "content": quote,
    })
    topic = HistoryTopic(
        category="冬季道路交通",
        rationale="本地区往年同期有官方高发提示，与下两个月的季节和社会活动变化相关。",
        evidence=[HistoryCitation(page_ref=ref, period="2025-11", quote=quote, location_quote="示例县", basis="official_frequency")],
    )
    # Need 4 qualifying topics; reuse the same local quote pattern.
    topics = []
    categories = ("冬季道路交通", "居民用火用电", "年末劳动报酬", "冬季人员聚集")
    for category in categories:
        q = f"示例县2025年11月{category}问题多发，相关部门提示做好前置风险防范。"
        page = store.put_artifact("r", "historical_page", {
            "url": "https://www.example.gov.cn/" + category,
            "title": category,
            "published_at": "2025-11-15T08:00:00+00:00",
            "content": q,
        })
        topics.append(HistoryTopic(
            category=category,
            rationale="本地区往年同期有官方高发提示，与下两个月的季节和社会活动变化相关。",
            evidence=[HistoryCitation(page_ref=page, period="2025-11", quote=q, location_quote="示例县", basis="official_frequency")],
        ))
    good, errors = validate_history(HistoricalResearch(topics=topics), store, "r", window, policy=policy)
    assert len(good) == 4 and not errors

    # A page that only mentions the default place name must not pass this package policy.
    foreign = topics[0].model_copy(deep=True)
    foreign.evidence[0].quote = "安顺市2025年11月冬季道路交通问题多发，相关部门提示做好前置风险防范。"
    foreign.evidence[0].location_quote = "安顺市"
    page = store.get_artifact(foreign.evidence[0].page_ref)
    page["content"] = foreign.evidence[0].quote
    store._artifacts = getattr(store, "_artifacts", {})  # may not exist
    # overwrite artifact content through the store API if possible
    try:
        store.put_artifact
    except Exception:
        pass
    # Safer: put a new page
    new_quote = "安顺市2025年11月冬季道路交通问题多发，相关部门提示做好前置风险防范。"
    new_ref = store.put_artifact("r", "historical_page", {
        "url": "https://www.example.gov.cn/foreign",
        "title": "x",
        "published_at": "2025-11-15T08:00:00+00:00",
        "content": new_quote,
    })
    bad = HistoricalResearch(topics=[HistoryTopic(
        category="冬季道路交通",
        rationale="本地区往年同期有官方高发提示，与下两个月的季节和社会活动变化相关。",
        evidence=[HistoryCitation(page_ref=new_ref, period="2025-11", quote=new_quote, location_quote="安顺市", basis="official_frequency")],
    )])
    good, errors = validate_history(bad, store, "r", window, policy=policy)
    assert good == []
    assert any("不是示例县本地证据" in error for error in errors)


def test_vocabulary_mode_does_not_inherit_default_official_host(tmp_path, monkeypatch):
    store, _ = fixture(tmp_path)
    monkeypatch.setattr("core.tools.vocabulary.localities", lambda package=None: {"示例县": ["示例县"]})
    policy = {"locality_evidence": {"from_vocabulary": True, "region": "示例县"}}
    window = forecast_window(FrozenReport(store, "r"))
    quote = "该地区2025年11月道路交通问题多发，相关部门提示做好前置风险防范。"
    ref = store.put_artifact("r", "historical_page", {
        "url": "https://www.anshun.gov.cn/road",
        "title": "道路",
        "published_at": "2025-11-15T08:00:00+00:00",
        "content": quote + "安顺市附带出现",
    })
    topic = HistoryTopic(
        category="冬季道路交通",
        rationale="本地区往年同期有官方高发提示，与下两个月的季节和社会活动变化相关。",
        evidence=[HistoryCitation(page_ref=ref, period="2025-11", quote=quote, location_quote="安顺市", basis="official_frequency")],
    )
    good, errors = validate_history(HistoricalResearch(topics=[topic]), store, "r", window, policy=policy)
    assert good == []
    assert any("不是示例县本地证据" in error or "须明确涉及示例县" in error for error in errors)


def test_source_excerpts_include_package_place_names(monkeypatch):
    monkeypatch.setattr("core.tools.vocabulary.localities", lambda package=None: {"示例县": ["示例县"]})
    policy = {"locality_evidence": {"from_vocabulary": True}}
    rows = source_excerpts("前缀示例县出现在资料里，后接说明文字。" * 1, policy=policy)
    assert any("示例县" in row for row in rows)


def test_default_source_excerpts_still_match_legacy_names():
    rows = source_excerpts("前缀安顺出现在资料里，后接说明文字。")
    assert any("安顺" in row for row in rows)


def test_ruyuan_package_config_if_present():
    root = Path(__file__).resolve().parents[1]
    pkg = root / "packages" / "ruyuan_yuebao"
    if not (pkg / "template.json").is_file():
        pytest.skip("ruyuan_yuebao package is not in this checkout")
    import json
    template = json.loads((pkg / "template.json").read_text(encoding="utf-8"))
    cfg = template["section_two"]
    assert cfg["field_roles"]["numbered_items_1"] == "general"
    assert cfg["field_roles"]["b46_risk_tip_1"] == "outlook"
    assert cfg["outlook_fields"] == ["b46_risk_tip_1", "b47_risk_tip_2", "b48_risk_tip_3", "b49_risk_tip_4"]
    assert cfg["locality_evidence"]["from_vocabulary"] is True
    assert "乳源" in cfg["locality_evidence"]["region"] or "示例" in cfg["locality_evidence"]["region"]
    manifest = yaml.safe_load((pkg / "manifest.yaml").read_text(encoding="utf-8-sig"))
    assert manifest["features"]["locality"]["enabled"] is False
    assert role({"id": "numbered_items_1", "kind": "paragraph_list"}, policy=cfg) is None
    assert role({"id": "b46_risk_tip_1", "kind": "analysis", "display_name": "第1条风险提示"}, policy=cfg) == "outlook"
    names = section_policy.flatten_localities(template["vocabulary"]["localities"])
    assert "乳源" in names and "乳源瑶族自治县" in names
