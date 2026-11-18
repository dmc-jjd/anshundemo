"""Saved completion metadata and approval must share the template contract."""
import pytest
from jsonschema import ValidationError

from app.structured_writer import preview_status, save_draft
from core.structured_template import validate_values
from test_frozen_writer import fixture


@pytest.mark.parametrize('required,filled,chart_count,missing,pending', [
    (['w1'], ['w1'], 5, [], 0),
    (['w1'], [], 5, ['w1'], 0),
    ([], [], 5, [], 0),
    (['w1'], ['w1'], 4, [], 1),
    (None, ['w1'], 5, ['b17_warning_count', 'w2', 'b5_issue_no'], 0),
])
def test_saved_completion_matches_preview(tmp_path, required, filled, chart_count, missing, pending):
    store, template = fixture(tmp_path)
    if required is None:
        template['output_schema'].pop('required', None)
    else:
        template['output_schema']['required'] = required
    values = {key: {'value': '人工确认', 'source_refs': ['human_edit']} for key in filled}
    charts = {str(i): 'chart-ref' for i in range(chart_count)}
    issues = [{'field_id': 'w2', 'error': 'writer_unfilled'}]
    state = save_draft(store, store.get_task('r'), template, values, {'human_edit'}, charts, issues)
    expected = dict(missing_fields=missing, pending_charts=pending, preview_only=bool(missing or pending))
    assert preview_status(template, values, charts) == expected
    assert {key: state.metadata[key] for key in expected} == expected
    assert store.get_task('r').metadata == state.metadata
    # Optional unfilled diagnostics remain available even when they do not block approval.
    assert state.metadata['writer_issues'] == issues
    if required is not None:
        if missing:
            with pytest.raises(ValidationError, match='required property'):
                validate_values(template, values, {'human_edit'}, require_complete=True)
        else:
            validate_values(template, values, {'human_edit'}, require_complete=True)


def test_approval_rejects_required_field_even_with_stale_ready_metadata(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.api_views.approval import approval_gate
    import app.template_engine as engine
    store, template = fixture(tmp_path)
    template['output_schema']['required'] = ['w1']
    state = save_draft(store, store.get_task('r'), template, {}, set(), {}, [])
    state.phase = 'awaiting_final_review'
    state.metadata['preview_only'] = False
    monkeypatch.setattr(engine, 'report_template', lambda *args: (state.template_ref, template))
    monkeypatch.setattr(engine, 'report_store_for_package', lambda *args: store)
    error, _ = approval_gate(store, state, SimpleNamespace(draft_hash='unused'),
                             validate_draft=lambda *args: pytest.fail('validation before completion gate'),
                             export_docx=lambda *args, **kw: pytest.fail('export before completion gate'))
    assert error == (409, 'missing_current_chart')
    # Supplying all chart slots exposes the missing required field gate.
    draft = store.get_artifact(state.draft_ref)
    draft['chart_refs'] = {str(i): 'chart-ref' for i in range(5)}
    state.draft_ref = store.put_artifact('r', 'structured_draft', draft)
    error, _ = approval_gate(store, state, SimpleNamespace(draft_hash='unused'),
                             validate_draft=lambda *args: pytest.fail('validation before completion gate'),
                             export_docx=lambda *args, **kw: pytest.fail('export before completion gate'))
    assert error == (409, 'preview_cannot_be_approved')

