"""WP-S3-C：Pillow 渲染器外迁到 `core/charts/renderers/pillow.py`——外壳零行为，注册项仍指向同一 handler。"""

from __future__ import annotations

import pytest

import app.tool as tool
from app.schemas import TaskState
from app.storage import Store
from app.tool_executor import RunContext


def fixture_ctx(tmp_path):
    store = Store(tmp_path)
    store.put_task(TaskState(id='t1', kind='report', phase='processing'))
    ref = store.put_artifact('t1', 'metrics', {
        'sentiment': {'负面': 1}, 'daily_count': {'2026-10-01': 1}, 'platform': {'网站': 1}})
    return RunContext(store, 't1'), ref


def test_pillow_renderer_lives_outside_the_shell():
    """实现已外迁，且 `app.tool` 的注册项仍指向同一个 handler（调用方零改动）。"""
    assert tool.render_chart.__module__ == 'core.charts.renderers.pillow'
    assert tool.HANDLERS['render_chart'] is tool.render_chart


def test_unknown_chart_type_message_is_unchanged(tmp_path):
    ctx, ref = fixture_ctx(tmp_path)
    with pytest.raises(ValueError) as exc:
        tool.render_chart({'chart_type': 'nope', 'metrics_ref': ref}, ctx)
    assert str(exc.value) == 'unknown_chart_type'


def test_candidate_charts_early_return_when_their_input_is_missing(tmp_path):
    """theme/locality 缺候选引用时仍是早退的 `needs_review`，不抛错、不画图。"""
    ctx, ref = fixture_ctx(tmp_path)
    for chart_type in ('theme', 'locality'):
        result = tool.render_chart({'chart_type': chart_type, 'metrics_ref': ref}, ctx)
        assert result.status == 'needs_review'
        assert result.unresolved[0]['kind'] == 'chart_input'
