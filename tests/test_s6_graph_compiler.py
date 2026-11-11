"""WP-S6-B：`core/graph` 的图编译器与审校循环模式。

全是纯函数/数据结构断言，**不跑图**——唯一例外是"未声明出口"那条：它必须证明守卫真的挂在
langgraph 的路径上，而不只是一个没人调用的旁路函数。

判据来源：`docs/team/任务分解-S6.md` §3 WP-S6-B、§0.3（writing 图 21 条边的现状）、§4.1（两段式）。
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
from typing import TypedDict

import pytest

from core.graph import compiler, review_loop
from core.ports import GraphNode, GraphSpec, ReviewerSpec

REPO = pathlib.Path(__file__).resolve().parents[1]


class _State(TypedDict, total=False):
    task_id: str


def _spec(*nodes: GraphNode, entry: str) -> GraphSpec:
    return GraphSpec(id="probe", nodes=tuple(nodes), entry=entry)


# --- 编译器：走 GraphSpec.validate() 的三条 ---------------------------------


def test_compiler_rejects_dangling_edge():
    spec = _spec(GraphNode("a", "agent", next=("ghost",)), entry="a")
    with pytest.raises(ValueError, match=r"graph_spec_invalid:.*dangling_edge:a->ghost"):
        compiler.compile_graph(spec, actions={"a": lambda state: None}, edges={}, state_schema=_State)


def test_compiler_rejects_duplicate_node():
    spec = _spec(GraphNode("a", "agent"), GraphNode("a", "tool"), entry="a")
    with pytest.raises(ValueError, match=r"graph_spec_invalid:.*duplicate_node_id"):
        compiler.compile_graph(spec, actions={"a": lambda state: None}, edges={}, state_schema=_State)


def test_compiler_rejects_missing_entry():
    spec = _spec(GraphNode("a", "agent"), entry="")
    with pytest.raises(ValueError, match=r"graph_spec_invalid:.*entry_missing"):
        compiler.compile_graph(spec, actions={"a": lambda state: None}, edges={}, state_schema=_State)


# --- 编译器：条件边的出口集合必须与声明完全一致 ------------------------------


def test_compiler_rejects_unknown_outcome():
    spec = _spec(GraphNode("a", "gate"), GraphNode("b", "tool"), entry="a")
    compiled = compiler.compile_graph(
        spec,
        actions={"a": lambda state: None, "b": lambda state: None},
        edges={"a": (lambda state: "third", {"first": "b", "second": "b"})},
        state_schema=_State,
    )
    with pytest.raises(ValueError, match="graph_unknown_outcome:a:third"):
        compiled.resolve("a", {})
    # 守卫必须挂在真实的图路径上：否则 compile() 会把未声明出口静默丢掉
    with pytest.raises(ValueError, match="graph_unknown_outcome:a:third"):
        compiled.compile().invoke({})


# --- 审校循环：能逐条还原现状 writing 图的 21 条边 ---------------------------

REVIEWERS = (
    ReviewerSpec(kind="format", role_id="format_reviewer"),
    ReviewerSpec(kind="content", role_id="content_reviewer"),
)

LOOP_ACTIONS = {
    "review:format_reviewer": "format_review",
    "review:content_reviewer": "content_review",
    "revalidate:format_reviewer": "local_validation",
    "revalidate:content_reviewer": "content_local_validation",
    "revision": "revise_draft",
    "final_review": "final_format_review",
    "await_final": "await_final_review",
}

#: 循环模式产出的 12 条条件边：出口名必须与 `format_route`/`review_route`/`after_revision` 逐字一致
EXPECTED_OUTCOMES = {
    ("format_review", "revise"): "revise_draft",
    ("format_review", "content"): "content_review",
    ("format_review", "finish"): "await_final_review",
    ("content_review", "revise"): "revise_draft",
    ("content_review", "final_format"): "final_format_review",
    ("content_review", "finish"): "await_final_review",
    ("revise_draft", "format_revalidate"): "local_validation",
    ("revise_draft", "content_revalidate"): "content_local_validation",
    ("revise_draft", "content"): "content_review",
    ("revise_draft", "final_format"): "final_format_review",
    ("revise_draft", "retry"): "revise_draft",
    ("revise_draft", "finish"): "await_final_review",
}

#: 模式之外由调用方声明的 8 条静态边（循环前流水线 + 两条校验链内部 + 终审落地）
CALLER_EDGES = (
    ("__start__", "validate_input"),
    ("validate_input", "write_draft"),
    ("write_draft", "local_validation"),
    ("local_validation", "style_detection"),
    ("style_detection", "format_review"),
    ("content_local_validation", "content_style_detection"),
    ("content_style_detection", "content_review"),
    ("await_final_review", "__end__"),
)

#: 现状 `build_writing_graph`（app/workflow.py:60-114）的 21 条边，逐条字面写死
WRITING_EDGES = frozenset(CALLER_EDGES) | frozenset(
    {
        ("format_review", "content_review"),
        ("format_review", "revise_draft"),
        ("format_review", "await_final_review"),
        ("content_review", "revise_draft"),
        ("content_review", "final_format_review"),
        ("content_review", "await_final_review"),
        ("revise_draft", "local_validation"),
        ("revise_draft", "content_local_validation"),
        ("revise_draft", "revise_draft"),
        ("revise_draft", "content_review"),
        ("revise_draft", "final_format_review"),
        ("revise_draft", "await_final_review"),
        ("final_format_review", "await_final_review"),
    }
)


def test_review_loop_reproduces_writing_edge_set():
    plan = review_loop.build_review_loop(reviewers=REVIEWERS, actions=LOOP_ACTIONS)

    assert plan.nodes == (
        "format_review",
        "content_review",
        "local_validation",
        "content_local_validation",
        "revise_draft",
        "final_format_review",
        "await_final_review",
    )
    outcomes = {
        (origin, outcome): target
        for origin, branches in plan.conditional_edges
        for outcome, target in branches
    }
    assert outcomes == EXPECTED_OUTCOMES

    plan_edges = set(plan.static_edges) | {
        (origin, target) for (origin, _), target in outcomes.items()
    }
    assert len(WRITING_EDGES) == 21
    assert plan_edges | set(CALLER_EDGES) == set(WRITING_EDGES)


# --- 审校循环：预算默认 5（钉住 ReviewerSpec.max_rounds=2 的坑） -------------


def test_review_loop_budget_default_is_five():
    plan = review_loop.build_review_loop(reviewers=REVIEWERS, actions=LOOP_ACTIONS)
    assert isinstance(plan.budgets, review_loop.ReviewBudgets)
    assert plan.budgets.max_rounds == 5
    # 未被消费的声明值：默认 2，不许拿它当默认预算
    assert REVIEWERS[0].max_rounds == 2


# --- 审校循环：plan 必须是纯数据（全不可变） ---------------------------------


def test_review_loop_plan_is_pure_data():
    plan = review_loop.build_review_loop(reviewers=REVIEWERS, actions=LOOP_ACTIONS)

    def assert_immutable(value):
        assert isinstance(value, (tuple, str)), type(value)
        if isinstance(value, tuple):
            for item in value:
                assert_immutable(item)

    assert_immutable(plan.nodes)
    assert_immutable(plan.static_edges)
    assert_immutable(plan.conditional_edges)
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.nodes = ()  # frozen dataclass


# --- 基座边界 ---------------------------------------------------------------


def test_core_graph_has_no_app_import():
    for path in sorted((REPO / "core" / "graph").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                assert not (module == "app" or module.startswith("app.")), (
                    f"{path.name} 导入了 {module}：core 不许反向依赖 app"
                )


def test_compile_does_not_mutate_spec():
    spec = _spec(GraphNode("a", "gate", next=("b",)), GraphNode("b", "tool"), entry="a")
    before = (spec, spec.nodes, spec.entry)
    compiled = compiler.compile_graph(
        spec,
        actions={"a": lambda state: None, "b": lambda state: None},
        edges={},
        state_schema=_State,
    )
    assert (compiled.spec, compiled.spec.nodes, compiled.spec.entry) == before
    assert compiled.spec is spec
    # state 形状由调用方给：core 不认识客户包的键（`dict` 会整体替换 state，不能当默认）
    assert compiled.state_schema is _State
