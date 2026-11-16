"""`GET /api/workflow-graphs` 的实现：**按客户包**展示图结构。

为什么不在 `app/main.py` 里写：`tests/test_s6_api_parity.py` 钉住 main.py ≤620 行
（M3 起点 620 行，零余量），所以路由还是那条路由，逻辑搬到这里。

为什么需要显式包（M3 缺口 8）：图结构里的节点集合受「该包的 manifest 能力剪枝 +
features 开关」影响（`prune_spec` / `_enabled_agents`），不传包就只能看默认包的图。
`package=''` = 部署默认包；显式包名走 `resolve_package()` 校验（坏包 404/422，不回落）。
"""
from __future__ import annotations


def workflow_graphs_view(deps, package: str = ''):
    """`{report: {nodes,edges,mermaid}, writing: {...}}`，在目标包的上下文里构建。"""
    from core.packages.context import package_context

    from ..packages_api import resolve_package
    from ..workflow import build_report_graph, build_writing_graph

    target = resolve_package(package)
    result = {}
    with package_context(target):
        for name, compiled in (('report', build_report_graph(deps)),
                               ('writing', build_writing_graph(deps))):
            graph = compiled.get_graph()
            result[name] = {
                'nodes': list(graph.nodes),
                'edges': [{'source': edge.source, 'target': edge.target,
                           'conditional': edge.conditional} for edge in graph.edges],
                'mermaid': graph.draw_mermaid(),
            }
    return result
