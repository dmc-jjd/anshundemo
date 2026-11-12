"""能力开关必须真的能开关（修「假开关」的判据）。

背景：verifier 实测发现 `manifest.features.locality/dedup` 只被解析、零消费者，
客户改 yaml 不会产生任何效果——等于谎称可关。这组测试就是那条修复的硬证据：
关掉某项能力后，对应工具必须真的从白名单里消失（模型调用会被 tool_not_allowed 拒掉）。
"""

from __future__ import annotations

from app.config import PACKAGE_DIR
from core.manifest import load_manifest
from core.tools import registry


def _features(**overrides):
    """构造 features 声明；每项默认 enabled=True，可按测试覆盖。"""
    base = {
        "locality": {"enabled": True},
        "dedup": {"enabled": True},
        "event_classification": {"enabled": True},
    }
    base.update(overrides)
    return base


def test_dedup_switch_off_removes_its_tools():
    """关掉去重 → group_events 与两级候选全部退出白名单。"""
    required = ["records", "events"]

    on = registry.resolve_tools(required, _features())
    off = registry.resolve_tools(required, _features(dedup={"enabled": False}))

    assert "group_events" in on, "前提：开着时去重工具在白名单"
    assert "group_events" not in off, "关掉后必须真的消失，否则就是假开关"
    assert "propose_vector_event_neighbors" not in off
    assert "propose_keyword_event_candidates" not in off
    # 不在该能力组里的工具不受影响
    assert "import_records" in off


def test_locality_switch_off_removes_only_locality_tool():
    required = ["records", "locality", "metrics"]

    on = registry.resolve_tools(required, _features())
    off = registry.resolve_tools(required, _features(locality={"enabled": False}))

    assert "resolve_locality" in on
    assert "resolve_locality" not in off
    assert {"import_records", "calculate_metrics"} <= off, "其它能力的工具不该被牵连"


def test_event_classification_switch_off_removes_classifiers():
    required = ["records", "events"]

    off = registry.resolve_tools(required, _features(event_classification={"enabled": False}))

    assert "classify_records" not in off
    assert "cluster_event_themes" not in off
    assert "discover_topics" not in off
    # 去重仍开着
    assert "group_events" in off


def test_undeclared_feature_does_not_intervene():
    """未声明某项能力 = 不干预（向后兼容）：老 manifest 不写 features 也要照常工作。"""
    required = ["records", "events", "locality"]

    without_features = registry.resolve_tools(required)
    with_empty = registry.resolve_tools(required, {})
    declared_on = registry.resolve_tools(required, _features())

    assert without_features == with_empty == declared_on


def test_default_package_switches_are_all_on_and_lossless():
    """A 包三项能力全开，剪枝结果必须与 tools.allow 完全一致（不多不少）。"""
    manifest = load_manifest(PACKAGE_DIR)

    resolved = registry.resolve_tools(manifest.required_capabilities, manifest.features)

    assert resolved == set(manifest.policy.allow)
    for feature in ("locality", "dedup", "event_classification"):
        assert manifest.features[feature]["enabled"] is True


def test_feature_tools_registry_covers_every_switchable_group():
    """FEATURE_TOOLS 的键必须与客户包 features 声明的键对得上。

    漏一个键 → 那个开关又是假的（改了没人读）。这条守的是"新增能力别忘了登记"。
    """
    manifest = load_manifest(PACKAGE_DIR)

    declared = set(manifest.features)
    registered = set(registry.FEATURE_TOOLS)

    assert declared <= registered, f"这些能力声明了却没有对应工具组: {sorted(declared - registered)}"


def test_dedup_threshold_has_single_source_of_truth():
    """dedup 阈值只允许在 template.json 里出现一次。"""
    manifest = load_manifest(PACKAGE_DIR)

    assert "similarity" not in manifest.features["dedup"], (
        "manifest 不该再写阈值：唯一真相是 template.json 的 data_contract.dedup"
    )

    from core.tools import vocabulary
    assert vocabulary.dedup_threshold() == 0.65
    assert vocabulary.dedup_candidate_floor() == 0.6
