"""WP-S2-F：`app/tool.py` 收成纯薄壳——组合根 + 两个转发函数（`render_chart` 已迁 `core/charts/renderers/pillow.py`）。"""

from __future__ import annotations

import ast
import pathlib

import app.tool as tool

SHELL_NAMES = [
    'import_records', 'filter_records', 'resolve_locality', 'group_events',
    'propose_keyword_event_candidates', 'propose_vector_event_neighbors', 'calculate_metrics',
    'classify_records', 'cluster_event_themes', 'discover_topics', 'select_materials', 'read_evidence',
    'render_chart', 'build_table', 'parse_report_document_tool', 'compare_report_structures',
    'CLUSTER_TERMS', 'HANDLERS', 'READ_ONLY', 'ARGUMENTS', 'DESCRIPTIONS',
    'get_tool_specs', 'get_tool_handler',
]


def test_shell_exposes_every_public_name_and_the_full_registry():
    """薄壳完整性：A 的 `__all__` 一个不少，且取 specs 时表被就地扩到 21 个。"""
    assert [name for name in SHELL_NAMES if not hasattr(tool, name)] == []
    assert len(tool.get_tool_specs()) == 21
    assert len(tool.HANDLERS) == 21


def test_registry_logic_lives_outside_the_shell():
    """实现已外迁：顶层只允许组合根两个转发函数这两个 def。"""
    tree = ast.parse(pathlib.Path(tool.__file__).read_text(encoding='utf-8'))
    assert {node.name for node in tree.body if isinstance(node, ast.FunctionDef)} == {
        'get_tool_specs', 'get_tool_handler'}
