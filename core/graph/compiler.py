"""把 `core.ports.GraphSpec`（只读声明）编译成可执行图。

两段式（`docs/team/任务分解-S6.md` §4.1）：
`GraphSpec` 只声明能静态知道的（节点、静态边、入口）；**运行期条件边**由 `edges` 注册表传入——
条件分支的出口是 `format_route` 这类函数在运行期算出来的，塞进声明就是把运行期逻辑伪装成数据。
因此 `core/ports.py` 零改动（S1 冻结契约）。

本模块不 import `app/`：基座与客户包互不依赖。图引擎类型不外泄（`compile()` 返回 `Any`），
图的 state 形状也由调用方给（`state_schema`）——core 不认识任何具体 state 的键。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from langgraph.graph import START, StateGraph

from core.ports import GraphSpec

#: 条件边的终止落点。`GraphSpec.next` 只认节点 id（`validate()` 会把别的当悬空边），
#: 所以"出口即结束"只能出现在 `edges` 注册表里。取值等于 langgraph 的 END 哨兵。
END_TARGET = "__end__"

#: 一条条件边：(路由函数, {出口名: 目标节点 id 或 END_TARGET})
ConditionalEdge = tuple[Callable[[Any], str], Mapping[str, str]]


def _route(
    origin: str,
    router: Callable[[Any], str],
    outcomes: Mapping[str, str],
    state: Any,
) -> str:
    """跑一次路由函数；出口必须已声明，否则抛错（不许"多一个出口就忽略"）。"""
    outcome = router(state)
    if outcome not in outcomes:
        raise ValueError(f"graph_unknown_outcome:{origin}:{outcome}")
    return outcomes[outcome]


def _router_for(
    origin: str,
    router: Callable[[Any], str],
    outcomes: Mapping[str, str],
) -> Callable[[Any], str]:
    def route(state: Any) -> str:
        return _route(origin, router, outcomes, state)

    return route


@dataclass(frozen=True, slots=True)
class CompiledGraph:
    """编译结果：声明原样保留（可静态比对），`.compile()` 才产出可执行图。"""

    spec: GraphSpec
    actions: Mapping[str, Callable[..., Any]]
    edges: Mapping[str, ConditionalEdge]
    #: 图状态 schema（TypedDict 之类），由调用方给——core 不认识客户包的 state 形状
    state_schema: type
    #: 节点包装器（现状是 `_graph_node` 那种加事件、转 phase 的闭包），签名 `(节点 id, 动作) -> 动作`
    node_wrapper: Callable[[str, Callable[..., Any]], Callable[..., Any]] | None = None

    def resolve(self, origin: str, state: Any) -> str:
        """只算一条条件边的落点，不建图（出口未声明即抛错）。"""
        router, outcomes = self.edges[origin]
        return _route(origin, router, outcomes, state)

    def compile(self) -> Any:
        """按声明逐条搭图并编译。不做自动排序之类聪明事。"""
        graph = StateGraph(self.state_schema)
        for node in self.spec.nodes:
            action = self.actions[node.id]
            if self.node_wrapper is not None:
                action = self.node_wrapper(node.id, action)
            graph.add_node(node.id, action)
            for target in node.next:
                graph.add_edge(node.id, target)
        graph.add_edge(START, self.spec.entry)
        for origin, (router, outcomes) in self.edges.items():
            graph.add_conditional_edges(origin, _router_for(origin, router, outcomes), dict(outcomes))
        return graph.compile()


def compile_graph(
    spec: GraphSpec,
    *,
    actions: Mapping[str, Callable[..., Any]],
    edges: Mapping[str, ConditionalEdge],
    state_schema: type,
    node_wrapper: Callable[[str, Callable[..., Any]], Callable[..., Any]] | None = None,
) -> CompiledGraph:
    """校验声明后返回 `CompiledGraph`。悬空边/缺动作/未声明出口一律抛错，不静默容忍。

    `state_schema` 必须显式传入（TypedDict 之类）：**没有默认值**——实测 `dict` 会让每个节点
    的整体返回值替换 state，第二个节点就取不到前一节点没返回的键（如图的 `task_id`）。
    """
    problems = spec.validate()
    if problems:
        raise ValueError("graph_spec_invalid:" + ",".join(problems))
    for node in spec.nodes:
        if node.id not in actions:
            raise ValueError(f"graph_action_missing:{node.id}")
    known = {node.id for node in spec.nodes}
    for origin, (_, outcomes) in edges.items():
        if origin not in known:
            raise ValueError(f"graph_edge_origin_unknown:{origin}")
        for outcome, target in outcomes.items():
            if target not in known and target != END_TARGET:
                raise ValueError(f"graph_edge_target_unknown:{origin}.{outcome}->{target}")
    return CompiledGraph(
        spec=spec,
        actions=actions,
        edges=edges,
        state_schema=state_schema,
        node_wrapper=node_wrapper,
    )
