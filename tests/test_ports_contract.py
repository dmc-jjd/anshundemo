"""S1 契约冻结的契约测试。

只测 `core/ports.py` 的判定逻辑，不测任何业务实现。
这些断言一旦定下，W2 拆出的工作包必须满足它们。
"""

from __future__ import annotations

import pytest

from core.ports import (
    REJECT_PHASE_NOT_ALLOWED,
    REJECT_TOOL_NOT_ALLOWED,
    GraphNode,
    GraphSpec,
    Manifest,
    ToolPolicy,
    ToolResult,
    ToolSpec,
    load_forbidden_terms,
    scan_forbidden_terms,
)


# --- ToolPolicy：白名单与阶段 ------------------------------------------------


def test_policy_allows_tool_in_global_allow_list():
    policy = ToolPolicy(allow=frozenset({"import_records"}))
    assert policy.permits("import_records", "processing") is None


def test_policy_rejects_tool_missing_from_every_list():
    policy = ToolPolicy(allow=frozenset({"import_records"}))
    assert policy.permits("render_chart", "processing") == REJECT_TOOL_NOT_ALLOWED


def test_policy_allows_phase_specific_tool_only_in_that_phase():
    policy = ToolPolicy(
        allow=frozenset({"import_records"}),
        phases={"writing": frozenset({"plot_frozen_chart"})},
    )
    assert policy.permits("plot_frozen_chart", "writing") is None
    # 同一条工具，换了阶段就应被拒
    assert policy.permits("plot_frozen_chart", "processing") == REJECT_PHASE_NOT_ALLOWED


def test_policy_budget_falls_back_to_default():
    policy = ToolPolicy(budgets={"default": 40, "writing": 80})
    assert policy.budget("writing") == 80
    assert policy.budget("unknown_phase") == 40


# --- Manifest：缺字段即启动失败 ----------------------------------------------


def test_manifest_requires_core_keys():
    with pytest.raises(ValueError) as exc:
        Manifest.from_mapping({"package": "p"})
    assert "manifest_missing_keys" in str(exc.value)


def test_manifest_parses_tools_and_packs():
    manifest = Manifest.from_mapping(
        {
            "package": "demo",
            "report_type": "月报",
            "version": "1.0.0",
            "template": "template.json",
            "prompts": "prompts/",
            "tools": {
                "allow": ["import_records"],
                "phases": {"writing": ["plot_frozen_chart"]},
                "budgets": {"default": 40, "writing": 80},
            },
            "charts": {"pack": "chart-core", "use": ["sentiment"]},
            "skills": {"pack": "skill-core", "use": ["source-binding"]},
        }
    )
    assert manifest.package == "demo"
    assert manifest.policy.permits("import_records", "processing") is None
    assert manifest.policy.budget("writing") == 80
    assert manifest.chart_use == ("sentiment",)
    assert manifest.skill_use == ("source-binding",)


# --- GraphSpec：图规格自检 ---------------------------------------------------


def _graph(**kwargs) -> GraphSpec:
    default_nodes = (
        GraphNode(id="start", kind="agent", ref="writer", next=("done",)),
        GraphNode(id="done", kind="gate"),
    )
    return GraphSpec(
        id="g",
        nodes=kwargs.get("nodes", default_nodes),
        entry=kwargs.get("entry", "start"),
    )


def test_graph_valid_spec_has_no_problems():
    assert _graph().validate() == []


def test_graph_rejects_dangling_edge():
    nodes = (GraphNode(id="start", kind="agent", next=("ghost",)),)
    problems = _graph(nodes=nodes, entry="start").validate()
    assert any(p.startswith("dangling_edge") for p in problems)


def test_graph_rejects_duplicate_node_id():
    nodes = (
        GraphNode(id="a", kind="agent", next=("a",)),
        GraphNode(id="a", kind="gate"),
    )
    problems = _graph(nodes=nodes, entry="a").validate()
    assert "duplicate_node_id" in problems


def test_graph_requires_entry():
    nodes = (GraphNode(id="a", kind="gate"),)
    assert "entry_missing" in _graph(nodes=nodes, entry="").validate()


# --- 解耦门禁 -----------------------------------------------------------------


def test_scan_flags_client_words_in_core_text():
    problems = scan_forbidden_terms([("core/x.py", "if name == '安顺': pass")], ["安顺"])
    assert problems == ["core/x.py:安顺"]


def test_scan_is_clean_for_client_neutral_text():
    assert scan_forbidden_terms([("core/y.py", "def classify(records): pass")], ["安顺"]) == []


def test_forbidden_terms_live_outside_core_and_cover_acceptance_list():
    """禁词表必须定义在 core 之外，否则门禁扫 core 时会命中定义本身（自指）。

    S2-A 实测过这个缺陷：core/ports.py 内置字面量表 → 永远 5 条命中。
    """
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    terms = load_forbidden_terms(repo / "scripts" / "forbidden_terms.json")

    for term in ("安顺", "西秀", "舆情调性", "b40_analysis_paragraph", "CLUSTER_TERMS"):
        assert term in terms

    # 关键：定义门禁的那个文件自身不能被扫描命中
    ports_src = (repo / "core" / "ports.py").read_text(encoding="utf-8")
    assert scan_forbidden_terms([("core/ports.py", ports_src)], terms) == []


# --- 数据契约结构兼容性 -------------------------------------------------------


def test_tool_spec_and_result_are_structurally_compatible_with_app_schemas():
    spec = ToolSpec(name="import_records", description="d", arguments_schema={"type": "object"})
    assert spec.version == "1" and spec.mutates_facts is True

    result = ToolResult(status="needs_review")
    assert result.data_ref is None and result.elapsed_ms == 0
