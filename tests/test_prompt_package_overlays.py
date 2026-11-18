# -*- coding: utf-8 -*-
"""Anshun prompt overlays stay verbatim; base no longer forces TOP10 or 研判分析."""
from pathlib import Path

from core.agent import get_prompt, provenance
from core.prompts import registry as prompt_registry


REPO = Path(__file__).resolve().parents[1]
KEYS = (
    "template_analyst.template",
    "writer.analysis",
    "writer.outlook",
    "writer.general",
    "writer.revise",
    "event_judge.top10",
)


def test_anshun_overlays_are_package_and_match_copied_files():
    sources = provenance("anshun_monthly")
    for key in KEYS:
        assert sources[key] == "package", key
        filename = key + ".md"
        expected = (REPO / "packages" / "anshun_monthly" / "prompts" / "agent" / filename).read_bytes()
        # registry load discipline: text plus a single trailing LF is stripped
        body = expected.decode("utf-8")
        body = body[:-1] if body.endswith("\n") else body
        assert get_prompt(key, package="anshun_monthly") == body
        # Hard Anshun constraints remain in the overlay, not dropped.
        if key == "writer.analysis":
            assert "300—500字" in body
        if key == "template_analyst.template":
            assert "（一）研判分析" in body
            assert "TOP10 可绑定" in body


def test_base_template_analyst_no_longer_forces_anshun_structure():
    text = get_prompt("template_analyst.template", package="longchuan_yuebao")
    assert provenance("longchuan_yuebao")["template_analyst.template"] == "base"
    assert "必须整段设为一个 kind=analysis" not in text
    assert "梗概15—35字" not in text
    assert "强制增加榜单字段" in text or "不要强制增加榜单字段" in text
    assert "写300—500字完整一段" not in get_prompt("writer.analysis", package="longchuan_yuebao")
