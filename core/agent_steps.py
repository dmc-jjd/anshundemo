"""声明式角色调度：角色 → 流程步骤的基座映射，以及按声明裁剪图。

客户包只声明「谁参与」（`manifest.yaml` 的 `agents:`），基座决定「哪一步跑」。
反向映射留在基座的理由：节点 id 属于图结构，图结构属于基座。让客户包写
`('writing', 'final_format_review')` 等于把图抄进每个客户包，换个包就漂移。

语义（与 `core.ports.Manifest.agents` 配套）：
    未声明 / 空     → 全部角色参与（向后兼容，老包行为不变）
    声明非空        → 只有列出的角色参与；它驱动的节点若无人驱动则整段裁掉，
                      前驱按 `BYPASS` 改接到后继；`validate_input` 是图入口，永不裁。
    未登记角色      → `manifest_unknown_agent:<id>`（`core/manifest.py` 启动期即校验）

为什么历史调研单列 `INLINE_STEPS`：它不是图节点，是 `write_draft` 内部的一步；
按「角色 → 节点」硬塞会让它假装成一个可裁的图节点。
"""

from __future__ import annotations

from typing import AbstractSet, Iterable, Mapping

from core.ports import GraphNode, GraphSpec

#: 角色 → 它驱动的流程步骤（图, 节点）。基座知识，客户包不写。
ROLE_STEPS: dict[str, tuple[tuple[str, str], ...]] = {
    'template_analyst': (('template', 'local_compare_and_analysis'),),
    'data_processor': (('report', 'data_processing'),),
    'event_judge': (('report', 'event_analysis'),),
    'event_classifier': (('report', 'event_analysis'),),
    'event_summarizer': (('report', 'event_analysis'),),
    'writer': (('writing', 'write_draft'),),
    'format_reviewer': (('writing', 'format_review'), ('writing', 'final_format_review')),
    'content_reviewer': (('writing', 'content_review'),),
}

#: 内联步骤（不是图节点）：角色 → 步骤名。识别靠显式声明，不靠字段名猜测。
INLINE_STEPS: dict[str, str] = {'historical_researcher': 'historical_research'}

#: 内联步骤属于哪张图——只用于把「本次启用了谁」写进任务事件。
INLINE_STEP_GRAPH: dict[str, str] = {'historical_researcher': 'writing'}

#: 受声明调度的全部角色（声明缺省时 = 这就是「全部」）。
#: 序与 A 包 `manifest.yaml` 的声明序一致；只列会驱动流程步骤的角色
#: （`writer_data_planner` / `hotspot_collector` 不驱动本节所列步骤，不受裁剪影响）。
ALL_AGENTS: tuple[str, ...] = (
    'template_analyst',
    'data_processor',
    'event_judge',
    'event_classifier',
    'event_summarizer',
    'writer',
    'historical_researcher',
    'format_reviewer',
    'content_reviewer',
)

#: 节点被裁掉时，入边改接哪里（基座拓扑知识）。值为 None = 该链在图上结束。
#: 只登记「可能被裁」的节点；`validate_input` 与各 `await_*` 闸门不在映射里，故永不裁。
BYPASS: dict[tuple[str, str], str | None] = {
    ('report', 'data_processing'): 'await_data_review',
    ('report', 'event_analysis'): 'await_data_review',
    ('template', 'local_compare_and_analysis'): None,
    ('writing', 'format_review'): 'content_review',
    ('writing', 'content_review'): 'await_final_review',
    ('writing', 'final_format_review'): 'await_final_review',
}

_ROLES_BY_STEP: dict[tuple[str, str], list[str]] = {}
for _role in ALL_AGENTS:
    for _step in ROLE_STEPS.get(_role, ()):
        _ROLES_BY_STEP.setdefault(_step, []).append(_role)
_STEP_ROLES: dict[tuple[str, str], tuple[str, ...]] = {
    step: tuple(roles) for step, roles in _ROLES_BY_STEP.items()
}


# --------------------------------------------------------------------------- #
# 声明解释
# --------------------------------------------------------------------------- #


def enabled_agents(manifest) -> frozenset[str]:
    """声明为空 = 全部角色；否则就是声明集合。"""
    declared = tuple(getattr(manifest, 'agents', ()) or ())
    return frozenset(declared) if declared else frozenset(ALL_AGENTS)


def resolve_enabled_agents() -> frozenset[str]:
    """按宿主配置的客户包（`core.paths.package_dir()`）解析本次启用的角色。"""
    from core import paths
    from core.manifest import load_manifest

    return enabled_agents(load_manifest(paths.package_dir()))


def validate_declared_agents(declared: Iterable[str], known_roles: Iterable[str]) -> None:
    """声明里出现 `roles.yaml` 没有的角色 → 启动即失败，不静默忽略。"""
    known = set(known_roles)
    for agent in declared:
        if agent not in known:
            raise ValueError(f'manifest_unknown_agent:{agent}')


def graph_agents(graph_id: str, agents: AbstractSet[str]) -> tuple[str, ...]:
    """某张图实际参与者（含内联角色），按 `ALL_AGENTS` 序——审计用。"""
    enabled = set(agents)
    return tuple(
        role for role in ALL_AGENTS
        if role in enabled
        and (any(graph == graph_id for graph, _ in ROLE_STEPS.get(role, ()))
             or INLINE_STEP_GRAPH.get(role) == graph_id)
    )


# --------------------------------------------------------------------------- #
# 图裁剪
# --------------------------------------------------------------------------- #


def _replacement(graph_id: str, target: str, removed: frozenset[str]) -> str | None:
    """沿裁剪链找第一个保留节点；None 表示这条链在图上结束。"""
    origin = target
    seen: set[str] = set()
    while target in removed:
        if target in seen:
            raise ValueError(f'agent_step_cycle:{graph_id}:{origin}')
        seen.add(target)
        if (graph_id, target) not in BYPASS:
            # 新增「角色 → 步骤」却忘了登记后继：宁可建图失败，也不静默把图截断。
            raise ValueError(f'agent_step_bypass_missing:{graph_id}:{target}')
        target = BYPASS[(graph_id, target)]  # type: ignore[assignment]
        if target is None:
            return None
    return target


def _end_router(state):
    return 'end'


def prune_spec(
    spec: GraphSpec,
    edges: Mapping[str, tuple],
    graph_id: str,
    agents: AbstractSet[str],
):
    """按角色声明裁图：无人驱动的节点整段移除，前驱改接到首个保留后继。

    返回值与入参同形 `(GraphSpec, edges 注册表)`。**零裁剪时原样返回**——
    A 包全声明走的正是这条路径，图对象逐字段不变（G-GRAPH 指纹不变的前提）。
    """
    enabled = set(agents)
    removed = frozenset(
        node.id for node in spec.nodes
        if _STEP_ROLES.get((graph_id, node.id))
        and not (set(_STEP_ROLES[(graph_id, node.id)]) & enabled)
    )
    if not removed:
        return spec, edges

    from core.graph.compiler import END_TARGET

    nodes: list[GraphNode] = []
    end_only: set[str] = set()
    for node in spec.nodes:
        if node.id in removed:
            continue
        targets = tuple(_replacement(graph_id, target, removed) for target in node.next)
        live = tuple(target for target in targets if target is not None)
        if live and len(live) != len(targets):
            raise ValueError(f'agent_step_end_ambiguous:{graph_id}:{node.id}')
        if targets and not live:
            end_only.add(node.id)
        nodes.append(GraphNode(node.id, node.kind, node.ref, live))

    pruned: dict[str, tuple] = {}
    for origin, (router, outcomes) in edges.items():
        if origin in removed:
            continue
        pruned[origin] = (router, {
            outcome: (target if target == END_TARGET
                      else (_replacement(graph_id, target, removed) or END_TARGET))
            for outcome, target in outcomes.items()
        })
    for node in nodes:
        if node.id not in end_only:
            continue
        if node.id in pruned:
            raise ValueError(f'agent_step_end_ambiguous:{graph_id}:{node.id}')
        pruned[node.id] = (_end_router, {'end': END_TARGET})

    return GraphSpec(id=spec.id, nodes=tuple(nodes), entry=spec.entry), pruned
