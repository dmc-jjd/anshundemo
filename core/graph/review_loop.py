"""审校循环的通用拓扑模式：只产出节点与边（数据），不建图、不含任何判定逻辑。

通用的是**形状**（§4.2）：
    N 个审校角色 → 可退修则回到本阶段校验链 → 不可退修/取消则转终审 → 末位审校只审不退修
不通用的是**判定**：`format_route`/`review_route`/`after_revision`/`repairable` 读的都是 `app/` 的
数据结构，一个字符都不搬进 core。本模块只声明"哪个出口落到哪个节点"，出口由调用方的路由函数在
运行期产出——所以入口是"语义槽位 → 节点 id"，而不是某张具体图的节点名。

出口名由 `ReviewerSpec.kind` 派生（不是硬编码某张图）：
    非末位审校过审 → 下一阶段的 kind（如 'content'）
    末位审校过审   → 'final_<首阶段 kind>'（只审不退修，交回首阶段角色的终审节点）
    退修成功       → '<kind>_revalidate'；退修失败重试 → 'retry'；取消/收尾 → 'finish'
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from core.ports import ReviewerSpec


@dataclass(frozen=True, slots=True)
class ReviewBudgets:
    """审校预算。

    现状真实预算是 **5 处字面 5**；`ReviewerSpec.max_rounds`（默认 2）全仓零消费，
    **不许拿它当默认**——接线即改行为（`test_writing_graph.py:66/169` 依赖 5 轮）。
    """

    max_rounds: int = 5


@dataclass(frozen=True, slots=True)
class ReviewLoopPlan:
    """纯数据：审校循环占用的节点与边（全部不可变）。"""

    nodes: tuple[str, ...]
    static_edges: tuple[tuple[str, str], ...]
    #: (起点, ((出口名, 目标节点), ...))——出口名由路由函数在运行期产出，这里声明它可能落到哪
    conditional_edges: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    budgets: ReviewBudgets


def build_review_loop(
    *,
    reviewers: tuple[ReviewerSpec, ...],
    actions: Mapping[str, str],
    budgets: ReviewBudgets = ReviewBudgets(),
) -> ReviewLoopPlan:
    """按审校角色序列展开循环拓扑。

    `actions` 的语义槽位：`review:<role_id>` / `revalidate:<role_id>`（该角色的校验链头节点）/
    `revision` / `final_review` / `await_final`。
    """
    if not reviewers:
        raise ValueError("review_loop_reviewers_empty")

    def node(slot: str) -> str:
        try:
            return actions[slot]
        except KeyError:
            raise ValueError(f"review_loop_action_missing:{slot}") from None

    revision = node("revision")
    final_review = node("final_review")
    await_final = node("await_final")
    reviews = [node(f"review:{reviewer.role_id}") for reviewer in reviewers]
    chains = [node(f"revalidate:{reviewer.role_id}") for reviewer in reviewers]

    kinds = [reviewer.kind for reviewer in reviewers]
    last = len(reviewers) - 1
    final_outcome = f"final_{kinds[0]}"

    conditional: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    for index, kind in enumerate(kinds):
        pass_outcome = final_outcome if index == last else kinds[index + 1]
        pass_target = final_review if index == last else reviews[index + 1]
        conditional.append(
            (
                reviews[index],
                (
                    ("revise", revision),
                    (pass_outcome, pass_target),
                    ("finish", await_final),
                ),
            )
        )

    revision_outcomes: list[tuple[str, str]] = [
        (f"{kind}_revalidate", head) for kind, head in zip(kinds, chains)
    ]
    revision_outcomes += [
        (kinds[index + 1], reviews[index + 1]) for index in range(last)
    ]
    revision_outcomes += [
        (final_outcome, final_review),
        ("retry", revision),
        ("finish", await_final),
    ]
    conditional.append((revision, tuple(revision_outcomes)))

    return ReviewLoopPlan(
        nodes=tuple(reviews) + tuple(chains) + (revision, final_review, await_final),
        static_edges=((final_review, await_final),),
        conditional_edges=tuple(conditional),
        budgets=budgets,
    )
