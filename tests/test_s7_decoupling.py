"""WP-S7-B：`core → app` 反向依赖 15 → 0 的六条判据（一组一条）。

每组只钉一件事：
    B1 类型上移   `core.tools.contracts` 是 SourceRef/ToolSpec/ToolResult 的家，`app.schemas` 只是 re-export；
                  字段集合逐字钉死（防搬家时丢字段，`G-SPECS` 指纹靠字段序）。
    B2 模块搬迁   `app.ooxml` / `app.template_compare` 是薄壳，异常类与函数身份不变。
    B3 数据根注入 `core.paths.data_root()` = `app.config.DATA`，且 `core/paths.py` 源码不出现宿主包名。
    B4 工具注入   21 项全来自「组合根传入的表 + extra_modules」；空表退出注入即什么都不产出。
    B5 工厂注入   未注册工厂 → 固定 RuntimeError；注册后同一调用不再抛它（只断言不是它）。
    B1–B5 总     `core/**` 的 ast 里 `app` 命中 0（复用 gate_core_iso 的扫描函数，不另写一把尺子）。
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import gate_core_iso  # noqa: E402

import app.config  # noqa: E402
import app.schemas  # noqa: E402
import app.tool  # noqa: E402
import core.charts.renderers.matplotlib as matplotlib_renderer  # noqa: E402
import core.paths  # noqa: E402
import core.tools.contracts as contracts  # noqa: E402
from core.tools import registry  # noqa: E402
from app import historical_web, writer_tools  # noqa: E402


def test_core_imports_no_app() -> None:
    assert gate_core_iso.dep_sites(REPO / "core") == []


def test_schemas_reexport_same_objects() -> None:
    assert app.schemas.SourceRef is contracts.SourceRef
    assert app.schemas.ToolSpec is contracts.ToolSpec
    assert app.schemas.ToolResult is contracts.ToolResult
    assert set(contracts.ToolResult.model_fields) == {
        'status', 'data_ref', 'source_refs', 'method', 'warnings', 'unresolved',
        'tool_version', 'elapsed_ms', 'error_code'}
    assert set(contracts.ToolSpec.model_fields) == {
        'name', 'description', 'version', 'required_capabilities',
        'produced_capabilities', 'mutates_facts', 'arguments_schema'}
    assert set(contracts.SourceRef.model_fields) == {'file_id', 'file_hash', 'location', 'record_ids'}


def test_ooxml_and_compare_reexport_identity() -> None:
    import app.ooxml as shell_ooxml
    import app.template_compare as shell_compare
    import core.tools.ooxml as core_ooxml
    import core.tools.template_compare as core_compare

    assert shell_ooxml.UnreadableDocument is core_ooxml.UnreadableDocument
    for module, names in ((shell_ooxml, ('read_docx', 'read_xlsx')),
                          (shell_compare, ('parse_report_document', 'compare_reports'))):
        for name in names:
            assert getattr(module, name) is getattr(core_ooxml if module is shell_ooxml else core_compare, name)
            assert getattr(module, name).__module__.startswith('core.tools.')
    assert shell_compare.NUMBER_RE.pattern == core_compare.NUMBER_RE.pattern


def test_data_root_is_injected() -> None:
    assert core.paths.data_root() == app.config.DATA
    source = (REPO / "core" / "paths.py").read_text(encoding="utf-8")
    assert "app" not in source
    tree = ast.parse(source)
    imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {a.name for node in ast.walk(tree) if isinstance(node, ast.Import) for a in node.names}
    assert not [m for m in imported if m == "app" or m.startswith("app.")]


def test_tool_specs_expand_via_injection() -> None:
    assert len(app.tool.get_tool_specs()) == 21
    params = inspect.signature(registry.get_tool_specs).parameters
    assert params['extra_modules'].kind is inspect.Parameter.KEYWORD_ONLY
    assert params['extra_modules'].default == ()

    # 空表 = 组合根什么都没给：core 不产出任何 spec（证明 21 项不是硬编码在 core 里）。
    # 规格 §3 此处写「16」，那要求 core 自己持有一张 16 项基座表（新的公开名 + 与组合根两份事实），
    # 与 B4「由 app/tool.py 传入」冲突，故按注入语义断言 0，并额外证明「只给两个模块 → 恰好 5 项」。
    assert registry.get_tool_specs({}, set(), {}, {}, extra_modules=()) == []
    injected = registry.get_tool_specs({}, set(), {}, {}, extra_modules=(writer_tools, historical_web))
    assert [spec.name for spec in injected] == [
        'frozen_statistics', 'query_frozen_materials', 'plot_frozen_chart',
        'search_historical_web', 'fetch_historical_page']


def test_report_factory_is_injected(monkeypatch) -> None:
    monkeypatch.setattr(matplotlib_renderer, '_report_factory', None)
    with pytest.raises(RuntimeError, match='report_factory_not_configured'):
        matplotlib_renderer.plot_frozen_chart({'chart_type': 'sentiment'}, None)

    monkeypatch.setattr(matplotlib_renderer, '_report_factory', lambda store, task_id: object())
    with pytest.raises(Exception) as caught:
        matplotlib_renderer.plot_frozen_chart({'chart_type': 'sentiment'}, None)
    assert 'report_factory_not_configured' not in str(caught.value)
