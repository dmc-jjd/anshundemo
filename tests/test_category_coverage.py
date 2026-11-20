import pytest
from app.writing_pipeline.category_coverage import context_for,validate_coverage

def test_nonzero_categories_are_complete_ordered_and_include_matching_materials():
    from types import SimpleNamespace
    report=SimpleNamespace(categories_for=lambda scope,count_unit='events':{'教育管理':3,'社会治安':1,'其他':0},
        records_for=lambda scope:[{'id':'a','title':'学校事件','sentiment':'负面'},{'id':'b','title':'失窃事件','sentiment':'负面'}],
        categories={'a':'教育管理','b':'社会治安'},record_mode=False)
    context=context_for(report,{'category_coverage_scope':'negative_warning_events'})
    assert [r['category'] for r in context['rows']]==['教育管理','社会治安']
    assert [r['count'] for r in context['rows']]==[3,1]
    assert context['rows'][0]['materials'][0]['ref']=='a'
    validate_coverage(['教育管理3条，占比75%，例如学校事件','社会治安1条，占比25%，例如失窃事件'],context)
    with pytest.raises(ValueError):validate_coverage(['教育管理3条'],context)
    with pytest.raises(ValueError):validate_coverage(['教育管理3条','教育管理1条'],context)

def test_actual_writer_request_carries_dynamic_schema_and_category_evidence(tmp_path,monkeypatch):
    import asyncio
    from test_frozen_writer import fixture
    from app.structured_template import _schema
    from app.structured_writer import write_structured_preview
    from app.workflow import Dependencies
    store,template=fixture(tmp_path)
    field=next(f for f in template['fields'] if f['id']=='w1')
    field.update(kind='paragraph_list',category_coverage_scope='negative_warning_events',count_unit='records',value_schema={'type':'array','items':{'type':'string'},'minItems':0})
    template['output_schema']=_schema(template['fields']);template['writer_schema']=_schema(template['fields'],True)
    state=store.get_task('r');state.template_ref=store.put_artifact('r','template',template);store.put_task(state,state.revision)
    monkeypatch.setattr('app.chart_spec.definitions',lambda template:[])
    calls=[]
    async def writer(catalog,payload,schema,ctx,**kwargs):
        if 'w1' in payload['remaining_fields']:
            coverage=payload['category_coverage']['w1'];calls.append(coverage)
            assert coverage['count_unit']=='records' and coverage['total']==2
            assert payload['report_context']['category_counts']=={'市场监管':2}
            assert payload['report_context']['scope']=='negative_warning_events'
            assert payload['evidence'][-1]['data']==payload['report_context']
            assert [row['category'] for row in coverage['rows']]==['市场监管']
            assert payload['output_values_schema']['properties']['w1']['properties']['value']['minItems']==1
            assert {item['ref'] for row in coverage['rows'] for item in row['materials']}=={'r0','r1'}
            return {'values':{'w1':{'value':['市场监管1条，占比100%，例如事件0。'],'source_refs':[state.fact_ref]}}}
        return {'values':{key:{'value':'合成正文','source_refs':[state.fact_ref]} for key in payload['remaining_fields']}}
    monkeypatch.setattr('app.structured_writer.invoke_numbered_writer',writer)
    result=asyncio.run(write_structured_preview(Dependencies(store),'r',agents={'writer'}))
    assert calls
    assert store.get_artifact(result.draft_ref)['slot_values']['w1']['value'][0].startswith('市场监管')
