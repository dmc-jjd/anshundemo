"""S10-G：`agents:` 声明式调度（客户包声明参与角色，基座决定跑哪些步骤）。

判据分三层，互不替代：
    * 声明解释：空 = 全部；非空 = 声明集；未登记角色 = 启动即失败 `manifest_unknown_agent:<id>`。
    * 图裁剪：按声明裁节点、前驱改接后继，`validate_input` 永不裁。
    * 内联步骤：历史调研同时要求「声明了 historical_researcher」且「模板有 outlook 字段」。

V1（A 包行为零变化）由 G-GRAPH / G-GOLDEN 门禁承担，本文件只钉声明解释与裁剪形状。
临时客户包一律复制 A 包到 `.conda/`（逐文件 `read_bytes`/`write_bytes`——`write_text`
在 Windows 上会写出 CRLF，提示词会被污染）。
"""

from __future__ import annotations

import asyncio
import pathlib
import shutil
import sys
import tempfile

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'tests'))

from app.config import PACKAGE_DIR  # noqa: E402
from app.workflow import (  # noqa: E402
    Dependencies,
    _report_spec,
    _template_spec,
    _writing_spec,
    build_report_graph,
    build_template_graph,
    build_writing_graph,
    run_writing_graph,
)
from core.agent_steps import (  # noqa: E402
    ALL_AGENTS,
    INLINE_STEPS,
    ROLE_STEPS,
    enabled_agents,
    graph_agents,
    resolve_enabled_agents,
)
from core.manifest import load_manifest  # noqa: E402
from core.ports import Manifest  # noqa: E402

SOURCE_PACKAGE = REPO / 'packages' / 'anshun_monthly'
SCRATCH = REPO / '.conda'
EVENT_ROLES = ('event_judge', 'event_classifier', 'event_summarizer')


# --------------------------------------------------------------------------- #
# 临时客户包（复制 A 包，改 manifest）
# --------------------------------------------------------------------------- #


@pytest.fixture()
def scratch():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = pathlib.Path(tempfile.mkdtemp(prefix='agent-dispatch-', dir=str(SCRATCH)))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def copy_package(dst: pathlib.Path) -> pathlib.Path:
    """逐文件 `read_bytes`/`write_bytes` 复制 A 包（禁 `write_text`：CRLF 会污染提示词）。"""
    for source in SOURCE_PACKAGE.rglob('*'):
        if not source.is_file():
            continue
        target = dst / source.relative_to(SOURCE_PACKAGE)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    return dst


def temp_package(scratch: pathlib.Path, agents, name: str = 'pkg') -> pathlib.Path:
    """复制 A 包后重写 manifest 的 `agents:`；`agents=None` = 删掉该段（测向后兼容）。"""
    package = copy_package(scratch / name)
    manifest = package / 'manifest.yaml'
    data = yaml.safe_load(manifest.read_bytes())
    if agents is None:
        data.pop('agents', None)
    else:
        data['agents'] = list(agents)
    manifest.write_bytes(yaml.safe_dump(data, allow_unicode=True, sort_keys=False).encode('utf-8'))
    return package


def package_agents(scratch: pathlib.Path, agents, name: str = 'pkg') -> frozenset[str]:
    return enabled_agents(load_manifest(temp_package(scratch, agents, name)))


def edge_set(graph):
    return {(edge.source, edge.target, edge.conditional, edge.data) for edge in graph.get_graph().edges}


# --------------------------------------------------------------------------- #
# V3：声明解释与启动校验
# --------------------------------------------------------------------------- #


def test_a_package_declares_every_role_and_graph_specs_unchanged():
    manifest = load_manifest(PACKAGE_DIR)
    assert manifest.agents == ALL_AGENTS
    assert enabled_agents(manifest) == frozenset(ALL_AGENTS)
    assert resolve_enabled_agents() == frozenset(ALL_AGENTS)
    assert len(_report_spec().nodes) == 4
    assert len(_writing_spec(review_only=False).nodes) == 11
    assert len(_template_spec().nodes) == 2


def test_undeclared_agents_means_all_roles(scratch):
    plain = Manifest.from_mapping({'package': 'probe', 'report_type': 'probe', 'version': '1',
                                   'template': 'template.json', 'prompts': 'prompts/'})
    assert plain.agents == ()
    assert enabled_agents(plain) == frozenset(ALL_AGENTS)

    # 同一个 A 包，只把 agents: 段删掉 —— 仍然全部启用（老包不炸）
    package = temp_package(scratch, None)
    assert load_manifest(package).agents == ()
    assert enabled_agents(load_manifest(package)) == frozenset(ALL_AGENTS)


def test_declared_role_must_exist_in_roles_yaml(scratch):
    package = temp_package(scratch, [*ALL_AGENTS, 'ghost_agent'])
    with pytest.raises(ValueError) as error:
        load_manifest(package)
    assert str(error.value) == 'manifest_unknown_agent:ghost_agent'


def test_declaration_can_narrow_to_a_subset_without_touching_roles_yaml(scratch):
    declared = ('writer', 'template_analyst')
    assert package_agents(scratch, declared) == frozenset(declared)


def test_rule_tables_cover_every_declared_role():
    # 每个可调度角色都必须有落点，否则「声明了但不生效」会静默无感。
    for role in ALL_AGENTS:
        assert ROLE_STEPS.get(role) or role in INLINE_STEPS, role
    assert set(INLINE_STEPS) == {'historical_researcher'}
    assert graph_agents('writing', frozenset(ALL_AGENTS)) == (
        'writer', 'historical_researcher', 'format_reviewer', 'content_reviewer')
    assert graph_agents('report', frozenset(ALL_AGENTS)) == (
        'data_processor', 'event_judge', 'event_classifier', 'event_summarizer')


# --------------------------------------------------------------------------- #
# V2-1：删事件研判三角 -> 报告图 4 变 3，data_processing 直指 await_data_review
# --------------------------------------------------------------------------- #


def test_report_graph_drops_event_analysis_when_no_event_role(scratch):
    agents = package_agents(scratch, [role for role in ALL_AGENTS if role not in EVENT_ROLES])
    graph = build_report_graph(Dependencies(object()), agents=agents)
    assert set(graph.get_graph().nodes) == {
        '__start__', 'validate_input', 'data_processing', 'await_data_review', '__end__'}
    # 两个出口（analyse / finish）都落到 await_data_review；langgraph 会把这个同目标
    # 折叠成一条可视化边（出口名仍各自保留在 path_map 里），所以断言目标集合。
    assert {edge.target for edge in graph.get_graph().edges
            if edge.source == 'data_processing'} == {'await_data_review'}
    assert not [edge for edge in graph.get_graph().edges
                if 'event_analysis' in (edge.source, edge.target)]


def test_prune_rewires_static_and_conditional_edges():
    from core.agent_steps import prune_spec
    from core.ports import GraphNode, GraphSpec

    spec = GraphSpec('writing', (
        GraphNode('validate_input', 'gate', next=('style_detection',)),
        GraphNode('style_detection', 'tool', next=('format_review',)),
        GraphNode('format_review', 'agent'),
        GraphNode('content_review', 'agent', next=('await_final_review',)),
        GraphNode('final_format_review', 'agent', next=('await_final_review',)),
        GraphNode('await_final_review', 'gate')), entry='validate_input')
    edges = {
        'format_review': (lambda state: 'content', {'content': 'content_review'}),
        'content_review': (lambda state: 'final_format',
                           {'final_format': 'final_format_review', 'finish': 'await_final_review'}),
        'final_format_review': (lambda state: 'end', {'end': None}),
    }
    pruned, pruned_edges = prune_spec(spec, edges, 'writing',
                                      frozenset({'writer', 'content_reviewer'}))
    assert [node.id for node in pruned.nodes] == [
        'validate_input', 'style_detection', 'content_review', 'await_final_review']
    assert pruned.node('style_detection').next == ('content_review',)
    assert 'format_review' not in pruned_edges and 'final_format_review' not in pruned_edges
    assert pruned_edges['content_review'][1] == {
        'final_format': 'await_final_review', 'finish': 'await_final_review'}


def test_report_graph_still_drops_data_processing_when_role_absent(scratch):
    agents = frozenset({'writer'})
    graph = build_report_graph(Dependencies(object()), agents=agents)
    assert set(graph.get_graph().nodes) == {
        '__start__', 'validate_input', 'await_data_review', '__end__'}
    assert ('validate_input', 'await_data_review', True, 'process') in edge_set(graph)


# --------------------------------------------------------------------------- #
# V2-3：删 format_reviewer -> 写作图少两个节点（format_review / final_format_review）
# --------------------------------------------------------------------------- #


def test_writing_graph_drops_both_format_review_nodes(scratch):
    agents = package_agents(scratch, [role for role in ALL_AGENTS if role != 'format_reviewer'])
    graph = build_writing_graph(Dependencies(object()), agents=agents)
    nodes = set(graph.get_graph().nodes)
    assert len(nodes) == 11  # 13（A 包 11 节点 + __start__/__end__）- 2
    assert 'format_review' not in nodes and 'final_format_review' not in nodes
    edges = edge_set(graph)
    assert ('style_detection', 'content_review', False, None) in edges
    assert ('content_review', 'await_final_review', True, 'final_format') in edges
    assert not [edge for edge in graph.get_graph().edges
                if 'format_review' in (edge.source, edge.target)
                or 'final_format_review' in (edge.source, edge.target)]


# --------------------------------------------------------------------------- #
# V2-4：只留 writer -> 图仍能编译、能跑（零模型调用）
# --------------------------------------------------------------------------- #


def test_writer_only_graph_compiles_and_runs(tmp_path):
    from test_writing_graph import seeded

    store, _template, _state = seeded(tmp_path)

    async def forbidden(*args, **kwargs):
        raise AssertionError('只留 writer 时写作图不得调用任何审核模型')

    graph = build_writing_graph(Dependencies(store, forbidden), review_only=True, agents=frozenset({'writer'}))
    assert set(graph.get_graph().nodes) == {
        '__start__', 'validate_input', 'write_draft', 'local_validation', 'style_detection',
        'revise_draft', 'content_local_validation', 'content_style_detection',
        'await_final_review', '__end__'}
    state = asyncio.run(run_writing_graph(Dependencies(store, forbidden), 'r',
                                          review_only=True, agents=frozenset({'writer'})))
    assert state.phase == 'awaiting_final_review'


def test_template_graph_without_template_analyst_ends_after_validate(scratch):
    agents = package_agents(scratch, [role for role in ALL_AGENTS if role != 'template_analyst'])
    graph = build_template_graph(Dependencies(object()), agents=agents)
    assert set(graph.get_graph().nodes) == {'__start__', 'validate_input', '__end__'}
    assert ('validate_input', '__end__', True, 'end') in edge_set(graph)


# --------------------------------------------------------------------------- #
# V2-2：历史调研由声明决定（不再靠 outlook 字段名猜）
# --------------------------------------------------------------------------- #


def _history_counter(monkeypatch):
    import app.historical_research as research

    prepared = research.prepare_history
    calls = []

    async def counting(*args, **kwargs):
        calls.append(1)
        return await prepared(*args, **kwargs)

    monkeypatch.setattr(research, 'prepare_history', counting)
    return calls


def test_historical_research_runs_once_when_declared(tmp_path, monkeypatch):
    import app.structured_writer as writer
    from test_section_two import outlook_writer_fixture, seasonal_outlook_item

    store, _topics = outlook_writer_fixture(tmp_path, monkeypatch)
    calls = _history_counter(monkeypatch)  # 包在 fixture 的桩外面

    async def model(role, payload):
        return {'outlook_items': [seasonal_outlook_item(topic)
                                  for topic in payload['historical_research']['topics']]}

    assert 'historical_researcher' in resolve_enabled_agents()
    asyncio.run(writer.write_structured_preview(Dependencies(store, model), 'r'))
    assert len(calls) == 1


def test_historical_research_never_runs_when_not_declared(tmp_path, monkeypatch, scratch):
    import app.structured_writer as writer
    from test_section_two import outlook_writer_fixture

    store, _topics = outlook_writer_fixture(tmp_path, monkeypatch)
    calls = _history_counter(monkeypatch)
    package = temp_package(scratch, [role for role in ALL_AGENTS if role != 'historical_researcher'])
    declared = enabled_agents(load_manifest(package))
    assert 'historical_researcher' not in declared
    # 生产路径：写手按客户包声明解析角色，而不是由调用方传参。
    monkeypatch.setattr(writer, 'resolve_enabled_agents', lambda: declared)

    async def forbidden(*args, **kwargs):
        raise AssertionError('未声明 historical_researcher 时不得调用任何写作模型')

    state = asyncio.run(writer.write_structured_preview(Dependencies(store, forbidden), 'r'))
    assert calls == []
    assert 'monthly_recommendations' in state.metadata['missing_fields']
    assert any(issue.get('error') == 'historical_evidence_insufficient'
               for issue in state.metadata['writer_issues'])
