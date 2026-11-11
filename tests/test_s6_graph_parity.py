"""WP-S6-C：`app/workflow.py` 改读 `GraphSpec` 后的拓扑与契约钉。

判据来源：`docs/team/任务分解-S6.md` §0.3（三张图现状节点/边）与 §3 WP-S6-C。
图的**行为**（节点落地序 / 调用序 / 轮次）由 G-GRAPH 门禁负责；这里钉"搭法换了、结构没变"。

**唯一与改前字面拓扑不同的元数据**：三条终审落地边（`await_data_review` / `await_final_review` /
`local_compare_and_analysis` → `__end__`）由静态边变成"单出口条件边"——`core.graph.compiler`
没有静态 END 通道（`GraphSpec.next` 只认节点 id，`__end__` 会被判 `dangling_edge`），
出口即结束只能走 `edges` 注册表。目标节点与运行期行为完全不变（G-GRAPH 13 行逐字不变为证）。
"""

from __future__ import annotations

import asyncio

import app.workflow as workflow
from app.workflow import (
    Dependencies,
    GraphState,
    _report_spec,
    _template_spec,
    _writing_spec,
    build_report_graph,
    build_template_graph,
    build_writing_graph,
    run_writing_graph,
)


def _stub_deps():
    """建图期不执行任何节点：store 只需是个对象。"""
    return Dependencies(object())


def _edges(graph):
    """`(源, 目标, 是否条件边, 条件出口名)` 四元组集合（`get_graph()` 的实际元数据）。"""
    return {(edge.source, edge.target, edge.conditional, edge.data) for edge in graph.get_graph().edges}


REPORT_EDGES = {
    ("__start__", "validate_input", False, None),
    ("validate_input", "data_processing", True, "process"),
    ("validate_input", "__end__", True, "stop"),
    ("data_processing", "event_analysis", True, "analyse"),
    ("data_processing", "await_data_review", True, "finish"),
    ("event_analysis", "await_data_review", True, "finish"),
    ("event_analysis", "__end__", True, "stop"),
    # 终审落地：单出口条件边（见模块 docstring，core 无静态 END 通道）
    ("await_data_review", "__end__", True, "end"),
}

WRITING_EDGES = {
    ("__start__", "validate_input", False, None),
    ("validate_input", "write_draft", False, None),
    ("write_draft", "local_validation", False, None),
    ("local_validation", "style_detection", False, None),
    ("style_detection", "format_review", False, None),
    ("content_local_validation", "content_style_detection", False, None),
    ("content_style_detection", "content_review", False, None),
    ("final_format_review", "await_final_review", False, None),
    ("await_final_review", "__end__", True, "end"),
    ("format_review", "content_review", True, "content"),
    ("format_review", "revise_draft", True, "revise"),
    ("format_review", "await_final_review", True, "finish"),
    ("content_review", "revise_draft", True, "revise"),
    ("content_review", "final_format_review", True, "final_format"),
    ("content_review", "await_final_review", True, "finish"),
    ("revise_draft", "local_validation", True, "format_revalidate"),
    ("revise_draft", "content_local_validation", True, "content_revalidate"),
    ("revise_draft", "revise_draft", True, "retry"),
    ("revise_draft", "content_review", True, "content"),
    ("revise_draft", "final_format_review", True, "final_format"),
    ("revise_draft", "await_final_review", True, "finish"),
}

TEMPLATE_EDGES = {
    ("__start__", "validate_input", False, None),
    ("validate_input", "local_compare_and_analysis", False, None),
    ("local_compare_and_analysis", "__end__", True, "end"),
}


def test_report_graph_topology_unchanged():
    graph = build_report_graph(_stub_deps())
    assert set(graph.get_graph().nodes) == {
        "__start__", "validate_input", "data_processing", "event_analysis", "await_data_review", "__end__"}
    assert _edges(graph) == REPORT_EDGES


def test_writing_graph_topology_unchanged():
    graph = build_writing_graph(_stub_deps(), review_only=False)
    assert set(graph.get_graph().nodes) == {
        "__start__", "validate_input", "write_draft", "local_validation", "style_detection", "format_review",
        "content_review", "revise_draft", "content_local_validation", "content_style_detection",
        "final_format_review", "await_final_review", "__end__"}
    assert len(WRITING_EDGES) == 21
    assert _edges(graph) == WRITING_EDGES
    # revise_draft 的 6 个出口：after_revision 的返回串逐字对应
    assert {outcome for source, _, _, outcome in WRITING_EDGES if source == "revise_draft"} == {
        "format_revalidate", "content_revalidate", "retry", "content", "final_format", "finish"}


def test_template_graph_topology_unchanged():
    graph = build_template_graph(_stub_deps())
    assert set(graph.get_graph().nodes) == {
        "__start__", "validate_input", "local_compare_and_analysis", "__end__"}
    assert _edges(graph) == TEMPLATE_EDGES


def test_review_only_entry_branch_unchanged():
    for review_only, target in ((True, "local_validation"), (False, "write_draft")):
        graph = build_writing_graph(_stub_deps(), review_only=review_only)
        assert {edge.target for edge in graph.get_graph().edges if edge.source == "validate_input"} == {target}


def test_graph_node_event_contract_unchanged(tmp_path):
    from test_writing_graph import clean_review, seeded

    store, _template, _state = seeded(tmp_path)

    async def adapter(role, payload):
        return clean_review(payload)

    asyncio.run(run_writing_graph(Dependencies(store, adapter), "r", review_only=True))
    events = [event for event in store.events("r") if event["type"] == "graph_node"]
    assert {event["graph"] for event in events} == {"writing"}

    def node_fields(event):
        # Store.events() 追加 seq/at 记账字段；`_graph_node` 自己写的只有下面这些
        return frozenset(event) - {"seq", "at"}

    assert {node_fields(event) for event in events if event["status"] == "started"} == {
        frozenset({"type", "graph", "node", "status"})}
    assert {node_fields(event) for event in events if event["status"] == "finished"} == {
        frozenset({"type", "graph", "node", "status", "phase"})}
    assert not [event for event in events if event["status"] == "error"]


def test_graph_spec_validates():
    assert _report_spec().validate() == []
    assert _writing_spec(review_only=True).validate() == []
    assert _writing_spec(review_only=False).validate() == []
    assert _template_spec().validate() == []


def test_graph_spec_is_derived_from_one_source():
    specs = (_report_spec(), _writing_spec(review_only=False), _template_spec())
    assert [spec.id for spec in specs] == ["report", "writing", "template"]
    node_sets = {frozenset(node.id for node in spec.nodes) for spec in specs}
    assert len(node_sets) == 3  # 三张图不许抄成一张


def test_state_schema_is_graph_state():
    # 硬约束：传 dict 会让每个节点的返回值整体替换 state，第二个节点就取不到 task_id
    assert build_report_graph(_stub_deps()).builder.state_schema is GraphState
    assert build_writing_graph(_stub_deps()).builder.state_schema is GraphState
    assert build_template_graph(_stub_deps()).builder.state_schema is GraphState


PUBLIC_NAMES = (
    "GraphState", "Dependencies",
    "build_report_graph", "build_writing_graph", "build_template_graph",
    "run_writing_graph", "run_report_graph", "run_template_graph",
    "run_report", "run_template", "make_preview_with_charts",
    "freeze_facts", "make_draft", "make_preview",
    "_graph_node", "_item", "_args_for", "_process_records",
    "_analyse_report_events", "_await_data_review", "_write_draft",
)


def test_public_names_unchanged():
    assert [name for name in PUBLIC_NAMES if not hasattr(workflow, name)] == []
    assert workflow.GraphState is GraphState
