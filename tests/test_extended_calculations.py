"""Reusable calculations for unbound fields; no real data or model calls."""
from types import SimpleNamespace
import copy

import pytest
from pydantic import ValidationError

from core.frozen_report import Calculation, FrozenReport, MissingReportInput


def report():
    r = object.__new__(FrozenReport)
    r.fact_ref = 'fact-test'
    r.state = SimpleNamespace(metadata={'report_parameters': {'publication_date': '2026-11-18'},
                                       'report_parameters_ref': 'params-test'})
    r.records = [
        {'id': '1', 'title': '政务会议', 'source': '央媒', 'source_id': 'a', 'author': '甲',
         'media_level': '全国', 'media_attribute': '政务', 'published': '2026-10-02', 'sentiment': '正面'},
        {'id': '2', 'title': '政务会议', 'source': '省媒', 'source_id': 'b', 'author': '乙',
         'media_level': '省级', 'media_attribute': '官媒', 'published': '2026-10-02', 'sentiment': '正面'},
        {'id': '3', 'title': '政务会议', 'source': '省媒', 'source_id': 'b', 'author': '乙',
         'media_level': '省级', 'media_attribute': '官媒', 'published': '2026-10-03', 'sentiment': '中性'},
        {'id': '4', 'title': '另一政务标题', 'source': '市媒', 'source_id': '', 'author': '丙',
         'media_level': '市级', 'media_attribute': '政务', 'published': '2026-10-03', 'sentiment': '负面'},
        {'id': '5', 'title': '其他标题', 'source': '市媒', 'source_id': '', 'author': '丁',
         'media_level': '市级', 'media_attribute': '官媒', 'published': '2026-10-03', 'sentiment': '负面'},
        {'id': '6', 'title': '普通发言', 'source': '个人', 'source_id': 'c', 'author': '戊',
         'media_level': '其他', 'media_attribute': '个人', 'published': '2026-10-04', 'sentiment': '负面'},
    ]
    r.metrics = {'record_count': 6, 'daily_count': {'2026-10-02': 2, '2026-10-03': 3, '2026-10-04': 1},
                 'peak_day': '2026-10-03'}
    r.facts = {'report_month': '2026-10'}
    r.refs = {}
    return r


def test_peak_count_and_source_statistics_use_actual_scope():
    r = report()
    assert r.calculate({'metric': 'peak_count'})['value'] == '3'
    assert r.calculate({'metric': 'peak_count', 'sentiment': '正面'})['value'] == '2'
    assert r.calculate({'metric': 'source_statistics', 'limit': 2})['value'] == '市媒（2条），省媒（2条）'
    assert r.calculate({'metric': 'source_statistics', 'sentiment': '正面'})['value'] == '央媒（1条），省媒（1条）'
    r.records = []
    r.metrics = {'record_count': 0, 'daily_count': {}}
    assert r.calculate({'metric': 'peak_count'})['value'] == '0'
    assert r.calculate({'metric': 'source_statistics'})['value'] == '无记录'


def test_media_counts_use_filter_and_author_identity_fallback():
    r = report()
    spec = {'filters': {'media_level': ['全国', '省级', '市级']}}
    assert r.calculate({'metric': 'filtered_record_count', **spec})['value'] == '5'
    assert r.calculate({'metric': 'distinct_source_count', **spec})['value'] == '4'
    assert r.calculate({'metric': 'distinct_source_count', 'filters': {'media_level': ['省级']}})['value'] == '1'
    assert r.calculate({'metric': 'filtered_record_count', 'filters': {'media_level': ['不存在']}})['value'] == '0'
    assert r.calculate({'metric': 'filtered_record_count', 'filters': {'media_level': ['市级']}, 'sentiment': '负面'})['value'] == '2'
    # No mutation of frozen records or history.
    assert len(r.records) == 6
    r.records = [{'id': 'bad', 'title': '记录'}]
    with pytest.raises(MissingReportInput, match='media_level'):
        r.calculate({'metric': 'filtered_record_count', **spec})
    with pytest.raises(MissingReportInput, match='身份'):
        r.calculate({'metric': 'distinct_source_count'})


def test_selected_material_count_and_title_are_from_one_selection():
    r = report()
    result = r.calculate({'metric': 'selected_material_count', 'filters': {'media_attribute': ['政务']}})
    assert result['value'] == '3'  # Includes reposts with the identical title outside government accounts.
    assert result['selection']['title'] == '政务会议'
    assert result['selection']['record_refs'] == ['1', '2', '3']
    assert result['source_refs'] == ['fact-test']
    r.records.append({**r.records[1], 'id': '7', 'title': ' 政务会议 '})
    assert r.calculate({'metric': 'selected_material_count', 'filters': {'media_attribute': ['政务']}})['value'] == '4'
    r.records = [{**r.records[0], 'media_attribute': '个人'}]
    with pytest.raises(MissingReportInput, match='选题'):
        r.calculate({'metric': 'selected_material_count', 'filters': {'media_attribute': ['政务']}})


def test_parameterized_table_is_typed_and_uses_current_date():
    r = report()
    rows = [['发：各单位'], ['编印 {publication_date}印发']]
    original = copy.deepcopy(rows)
    result = r.calculate({'metric': 'parameterized_table', 'rows': rows, 'date_format': 'chinese'})
    assert result['value'] == [['发：各单位'], ['编印 2026年11月18日印发']]
    assert rows == original
    assert result['source_refs'] == ['params-test']
    r.state.metadata['report_parameters']['publication_date'] = '2026-12-01'
    assert r.calculate({'metric': 'parameterized_table', 'rows': rows})['value'][1][0] == '编印 2026-12-01印发'
    r.state.metadata['report_parameters'].pop('publication_date')
    with pytest.raises(MissingReportInput, match='publication_date'):
        r.calculate({'metric': 'parameterized_table', 'rows': rows})


@pytest.mark.parametrize('spec', [
    {'metric': 'filtered_record_count', 'filters': {'unknown_column': ['x']}},
    {'metric': 'filtered_record_count', 'filters': {'media_level': []}},
    {'metric': 'parameterized_table', 'rows': []},
    {'metric': 'parameterized_table', 'rows': [['{not_a_parameter}']]},
    {'metric': 'parameterized_table', 'rows': [['{publication_date.__class__}']]},
])
def test_invalid_specs_fail_before_calculation(spec):
    with pytest.raises(ValidationError):
        Calculation.model_validate(spec)


def test_confirm_toolbox_accepts_extended_specs_and_keeps_parameters():
    from app.template_review import available_bindings, binding_allowed
    from core.state import TemplateField
    spec = {'metric': 'filtered_record_count', 'filters': {'media_level': ['全国']}}
    assert binding_allowed(spec)
    assert {'peak_count', 'source_statistics', 'filtered_record_count', 'distinct_source_count',
            'selected_material_count', 'parameterized_table'} <= {b.get('metric') for b in available_bindings('longchuan_yuebao')}
    f = TemplateField.model_validate({'id': 'test_count', 'display_name': '数量', 'owner': 'data',
        'kind': 'number', 'source_type': 'statistics', 'semantic': '统计数量', 'rule': '统计筛选记录',
        'format': '整数', 'missing_policy': 'block', 'reason': '动态数量', 'binding': spec,
        'sources': [{'report_id': 'r1', 'block': 1, 'text': '12'}]})
    assert f.model_dump()['binding']['filters'] == spec['filters']


def test_all_twelve_package_bindings_execute_without_a_planner():
    from core.field_calculations import load
    from app.structured_writer import data_values
    from app.structured_template import _schema
    bindings = load('longchuan_yuebao')
    assert len(bindings) == 12
    fields = [{'id': key, 'owner': 'data', 'binding': None, 'value_schema':
               {'type': 'array', 'items': {'type': 'array', 'items': {'type': 'string'}}}
               if key == 'b48_table_rows' else {'type': 'string', 'minLength': 1}}
              for key in bindings]
    template = {'fields': fields, 'output_schema': _schema(fields)}
    values, issues = data_values(template, report(), {}, package='longchuan_yuebao')
    assert issues == []
    assert len(values) == 12
    assert values['b21_top_gov_count']['value'] == '3'
    assert values['b22_media_articles']['value'] == '5'
    assert values['b22_media_outlets']['value'] == '4'
    assert len(values['b48_table_rows']['value']) == 2  # Confirmed header is already the first of three rows.
    assert '2026年11月18日' in values['b48_table_rows']['value'][-1][0]


def test_selection_context_rejects_unrelated_writer_title():
    from app.writing_pipeline.calculation_context import build_contexts, validate_selection
    from core.field_calculations import load
    bindings = load('longchuan_yuebao')
    fields = {key: {'id': key, 'owner': 'data', 'binding': None} for key in bindings}
    fields.update({key: {'id': key, 'owner': 'writer'} for key in ('b21_top_gov_title', 'b21_gov_titles')})
    values = {'b21_top_gov_count': {'value': '3', 'source_refs': ['fact-test']}}
    contexts = build_contexts(fields, report(), values, {}, 'longchuan_yuebao')
    assert contexts[0]['selection']['title'] == '政务会议'
    validate_selection('b21_top_gov_title', {'value': '政务会议'}, contexts)
    validate_selection('b21_gov_titles', {'value': '《政务会议》《另一政务标题》'}, contexts)
    with pytest.raises(ValueError, match='选题'):
        validate_selection('b21_top_gov_title', {'value': '无关标题'}, contexts)
    with pytest.raises(ValueError, match='选题'):
        validate_selection('b21_gov_titles', {'value': '《另一政务标题》'}, contexts)


def test_writer_uses_bound_selection_and_never_plans_legacy_tool_fields(tmp_path, monkeypatch):
    import asyncio
    from app.structured_writer import write_structured_preview
    from app.structured_template import _schema
    from app.workflow import Dependencies
    from test_frozen_writer import fixture
    from core.packages import context
    import app.structured_writer as writer

    store, template = fixture(tmp_path)
    r = report()
    store.package = 'longchuan_yuebao'
    template = {**template, 'blocks': [{'index': 0, 'kind': 'paragraph', 'parts': [
        {'field': 'b21_top_gov_title'}, {'text': '传播'}, {'field': 'b21_top_gov_count'},
        {'field': 'b21_gov_titles'}, {'field': 'raw_warning'}]}]}
    template['fields'] = [{'id': key, 'owner': owner, 'kind': 'text', 'semantic': key,
                           'display_name': key, 'value_schema': {'type': 'string', 'minLength': 1},
                           'sources': [{'text': '历史'}], 'binding': binding}
                          for key, owner, binding in [
                              ('b21_top_gov_title', 'writer', None), ('b21_gov_titles', 'writer', None),
                              ('b21_top_gov_count', 'data', None),
                              ('raw_warning', 'data', {'tool': 'calculate_metrics', 'path': ['warning_raw_count']})]]
    template['output_schema'] = _schema(template['fields'])
    template['writer_schema'] = _schema(template['fields'], True)
    state = store.get_task('r')
    state.package = 'longchuan_yuebao'
    state.template_ref = store.put_artifact('r', 'template', template)
    refs = dict(state.result_refs)
    refs.pop('confirmed_event_groups', None)
    refs.pop('confirmed_theme_groups', None)
    refs['import_records'] = store.put_artifact('r', 'records', {'records': r.records})
    metrics = {**r.metrics, 'warning_raw_count': 2}
    state.fact_ref = store.put_artifact('r', 'facts', {'metrics': metrics, 'result_refs': refs,
                                                   'report_month': '2026-10', 'top10': []})
    store.put_task(state, state.revision)
    # Test only the material-writing path; the separate chart regression covers real plotting.
    monkeypatch.setattr('core.charts.spec.chart_slot_drawings', lambda root: [])
    seen = []
    async def invoke(catalog, payload, schema, ctx, **kwargs):
        seen.append(payload)
        assert payload['calculation_selections'][0]['selection']['title'] == '政务会议'
        if len(seen) == 1:
            return {'values': {'b21_top_gov_title': {'value': '无关标题', 'source_refs': [state.fact_ref]}}}
        return {'values': {key: {'value': '政务会议' if key == 'b21_top_gov_title' else '《政务会议》《另一政务标题》',
                                 'source_refs': [state.fact_ref]} for key in payload['remaining_fields']}}
    planner_calls = []
    async def no_planner(*args, **kwargs):
        planner_calls.append(args)
        raise AssertionError('Bound fields must not invoke a data planner')
    monkeypatch.setattr(writer, 'invoke_numbered_writer', invoke)
    monkeypatch.setattr(writer, 'invoke_agent', no_planner)
    with context.package_context('longchuan_yuebao'):
        result = asyncio.run(write_structured_preview(Dependencies(store), 'r', agents={'writer'}))
    draft = store.get_artifact(result.draft_ref)
    assert len(seen) == 2
    assert planner_calls == []
    assert draft['slot_values']['b21_top_gov_title']['value'] == '政务会议'
    assert draft['slot_values']['b21_top_gov_count']['value'] == '3'
    assert draft['slot_values']['raw_warning']['value'] == '2'
    assert not result.metadata['missing_fields']
    from app.writing_review import edit_structured
    from app.structured_writer import data_values
    calls = []
    def tracked_data_values(*args, **kwargs):
        calls.append(kwargs.get('package'))
        return data_values(*args, **kwargs)
    monkeypatch.setattr('app.writing_review.data_values', tracked_data_values)
    edit_structured(store, 'r', {}, draft['content_hash'], parameters={'publication_date': '2026-12-01'})
    assert calls == ['longchuan_yuebao']
    revised = store.get_artifact(store.get_task('r').draft_ref)
    with pytest.raises(ValueError, match='选题'):
        edit_structured(store, 'r', {'b21_top_gov_title': '无关标题'}, revised['content_hash'])
