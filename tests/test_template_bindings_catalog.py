"""Confirmation toolbox includes catalog metrics and package field bindings."""
from core.frozen_report import Calculation
from core.state import DataBinding, TemplateField
from app.template_review import available_bindings, binding_allowed, make_input


def test_available_bindings_include_legacy_catalog_and_package():
    bindings = available_bindings()
    legacy = {'tool': 'calculate_metrics', 'path': ['record_count']}
    assert legacy in bindings
    assert {'tool': 'top10_events', 'path': []} in bindings
    metrics = {item['metric'] for item in bindings if item.get('metric') and not item.get('field_id')}
    for name in ('platform_count', 'platform_source_detail', 'period_start', 'period_end', 'record_table', 'peak_date'):
        assert name in metrics

    package = available_bindings('ruyuan_yuebao')
    by_field = {item['field_id']: item for item in package if item.get('field_id')}
    assert by_field['b1_video']['metric'] == 'platform_count'
    assert by_field['b1_video']['platforms'] == ['视频']
    assert by_field['b9_period_start']['metric'] == 'period_start'
    assert by_field['b30_positive_events_table']['metric'] == 'record_table'


def test_binding_allowed_accepts_catalog_and_rejects_unknown_tool():
    packet = {'available_bindings': available_bindings('ruyuan_yuebao')}
    assert binding_allowed({'tool': 'calculate_metrics', 'path': ['record_count']}, packet)
    assert binding_allowed({'metric': 'platform_count', 'platforms': ['视频']}, packet)
    assert binding_allowed({'metric': 'period_start', 'include_year': True, 'include_day_suffix': True}, packet)
    assert binding_allowed({'metric': 'record_table', 'sentiment': '正面', 'limit': 6}, packet)
    assert not binding_allowed({'tool': 'calculate_metrics', 'path': ['invented']}, packet)
    assert not binding_allowed({'metric': 'not_a_real_metric'}, packet)
    assert not binding_allowed({'metric': 'platform_count'}, packet)  # missing platforms


def test_template_field_accepts_metric_binding():
    field = {
        'id': 'b1_video', 'display_name': '视频言论条数', 'owner': 'data', 'kind': 'number',
        'source_type': 'statistics', 'semantic': '视频渠道条数', 'rule': '按视频平台计数',
        'format': '整数', 'missing_policy': 'block', 'reason': '统计槽',
        'binding': {'metric': 'platform_count', 'platforms': ['视频']},
        'sources': [{'report_id': 'r1', 'block': 1, 'text': '视频言论xx条'}],
    }
    parsed = TemplateField.model_validate(field)
    assert parsed.binding.metric == 'platform_count'
    assert Calculation.model_validate(parsed.binding.model_dump())
    legacy = TemplateField.model_validate({**field, 'binding': {'tool': 'calculate_metrics', 'path': ['record_count']}})
    assert isinstance(legacy.binding, DataBinding)


def test_make_input_surfaces_package_bindings():
    documents = [
        {'id': 'r1', 'path': 'a.docx', 'sha256': 'a', 'blocks': [{'index': 1, 'kind': 'paragraph', 'text': '甲'}]},
        {'id': 'r2', 'path': 'b.docx', 'sha256': 'b', 'blocks': [{'index': 1, 'kind': 'paragraph', 'text': '乙'}]},
    ]
    comparison = {'documents': documents, 'method': 'x', 'alignments': []}
    local = {'blocks': [], 'fields': []}
    packet = make_input(documents, comparison, local, package='ruyuan_yuebao')
    assert any(item.get('metric') == 'platform_count' for item in packet['available_bindings'])
    assert any(item.get('field_id') == 'b1_web' for item in packet['available_bindings'])
