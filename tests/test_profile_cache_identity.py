"""The public mutation contract must survive registry cache invalidation."""
import pytest
import core.agent as agent
from app.agent import REPORT_PROMPT_PROFILES
from core.packages import registry
from core.packages.context import package_context

@pytest.mark.parametrize("mutate_before", [True, False])
def test_public_profile_mutation_survives_invalidation(monkeypatch, mutate_before):
    with package_context("anshun_monthly"):
        if mutate_before:
            monkeypatch.setitem(REPORT_PROMPT_PROFILES, "cache_probe", {"writer.general": "offline fixture"})
        registry.invalidate()
        if not mutate_before:
            monkeypatch.setitem(REPORT_PROMPT_PROFILES, "cache_probe", {"writer.general": "offline fixture"})
        assert agent._resolved().report_profiles is REPORT_PROMPT_PROFILES
        assert agent.get_prompt("writer.general", "cache_probe") == "offline fixture"


def test_profile_mutation_does_not_leak_to_another_package(monkeypatch):
    with package_context("anshun_monthly"):
        monkeypatch.setitem(REPORT_PROMPT_PROFILES, "cache_probe", {"writer.general": "offline fixture"})
        registry.invalidate()
    with package_context("ruyuan_yuebao"):
        with pytest.raises(ValueError, match="unknown_writer_prompt_profile"):
            agent.get_prompt("writer.general", "cache_probe")


def test_config_refresh_updates_public_view_in_place_without_changing_source(tmp_path):
    source = {"default": {}}
    view = registry._profile_view(tmp_path, source)
    view["runtime"] = {"writer.general": "injected"}
    assert registry._profile_view(tmp_path, source) is view
    assert "runtime" in view and "runtime" not in source
    refreshed = registry._profile_view(tmp_path, {"new_default": {}})
    assert refreshed is view and view == {"new_default": {}}
