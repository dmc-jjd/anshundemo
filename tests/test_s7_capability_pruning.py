"""方案 B：能力剪枝 —— 「去重/分类/研判不必每份报告都跑」的机械判据。

为什么需要这组测试：
    P7 的教训是「流程不要写死在代码里」。落地方式是客户包在 manifest 声明
    `capabilities.require`，基座按 `products → requirements` 反推可达工具集，
    再作为 `ToolPolicy.allow` 生效——白名单本身就是门禁，没选中的工具模型调不动。

    没有这组测试，剪枝表 `CAPABILITY_TOOLS` 会随工具增删悄悄失配：
    漏一个工具不会立刻报错，只会在某天某个客户包上变成「工具调不动」的谜题。
"""

from __future__ import annotations

from app.config import PACKAGE_DIR
from core.manifest import load_manifest
from core.tools import registry


def test_capability_tools_cover_default_allow():
    """硬约束：CAPABILITY_TOOLS 的并集必须涵盖 A 包的 allow 全集。

    否则「A 包声明全部产物」就等于「A 包被静默剪掉工具」——剪枝必须先在默认包上无损。
    """
    manifest = load_manifest(PACKAGE_DIR)
    allow = set(manifest.policy.allow)

    union: set[str] = set()
    for tools in registry.CAPABILITY_TOOLS.values():
        union.update(tools)

    assert allow <= union, f"剪枝表缺这些工具: {sorted(allow - union)}"


def test_default_package_pruning_is_lossless():
    """声明全部产物后，resolve_tools 结果必须与 allow 完全相同（不多不少）。"""
    manifest = load_manifest(PACKAGE_DIR)
    allowed = set(manifest.policy.allow)
    resolved = registry.resolve_tools(manifest.required_capabilities)

    assert resolved == allowed, (
        f"丢失={sorted(allowed - resolved)} 新增={sorted(resolved - allowed)}"
    )


def test_pruning_excludes_dedup_and_classify_without_events_capability():
    """不声明 events → 去重(group_events)与分类(classify_records)都不在白名单。

    这正是「不是每份报告都要去重/分类」的机械表达：删一个 require 项即可。
    """
    resolved = registry.resolve_tools(["records", "metrics"])

    assert "group_events" not in resolved
    assert "classify_records" not in resolved
    assert "propose_vector_event_neighbors" not in resolved
    assert {"import_records", "filter_records", "calculate_metrics"} <= resolved


def test_pruning_adds_events_tools_only_when_declared():
    without = registry.resolve_tools(["records"])
    with_events = registry.resolve_tools(["records", "events"])

    assert "group_events" not in without
    assert "group_events" in with_events
    assert with_events > without


def test_requirements_are_pulled_in_transitively():
    """`propose_vector_event_neighbors` 需要 keyword 候选：声明它就要顺带带上生产者。"""
    resolved = registry.resolve_tools(["records"])
    # records 本身不含向量近邻，缺失时不该凭空出现
    assert "propose_vector_event_neighbors" not in resolved

    # 一旦声明 events，向量近邻与它的上游关键词候选都要在
    with_events = registry.resolve_tools(["events"])
    assert "propose_vector_event_neighbors" in with_events
    assert "propose_keyword_event_candidates" in with_events
    assert "import_records" in with_events  # normalized_records 的生产者


def test_empty_requirement_yields_empty_set_not_everything():
    """require 为空语义是「不剪枝」（由调用方判断），resolve_tools 自身返回空集而非全集。"""
    assert registry.resolve_tools([]) == frozenset()
