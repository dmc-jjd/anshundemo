import asyncio,copy,io,json
from datetime import datetime
import pytest
from fastapi.testclient import TestClient
from test_frozen_writer import fixture
from app.chart_spec import DEFAULTS,styles_for,with_styles,definitions
from app.writer_tools import chart_payload
from app.frozen_report import FrozenReport
from app.structured_writer import save_draft,StructuredAnswers
from app.tool_executor import RunContext
from app.usage import task_usage,configuration,save_configuration,band,normalized

def test_pies_vertical_bars_and_style_change_preserves_counts(tmp_path):
    store,template=fixture(tmp_path);report=FrozenReport(store,'r')
    assert [c['style'] for c in definitions(template)]==['pie','line','pie','bar','barh']
    pie=chart_payload(report,'sentiment');bar=chart_payload(report,'theme');horizontal=chart_payload(report,'theme','barh')
    assert pie['style']=='pie' and pie['x_axis'] is None
    assert bar['x_axis']=='类别' and bar['y_axis']=='数量'
    assert horizontal['x_axis']=='数量' and horizontal['y_axis']=='类别'
    assert bar['counts']==horizontal['counts'] and bar['fact_ref']==horizontal['fact_ref']
    assert chart_payload(report,'platform')['style']=='pie'
    with pytest.raises(ValueError):styles_for(template,{'daily':'pie'})
    with pytest.raises(ValueError):styles_for(template,{'made_up':'pie'})
    changed=with_styles(with_styles(template,{'theme':'barh'}),{'platform':'bar'})
    assert styles_for(changed)['theme']=='barh' and styles_for(changed)['platform']=='bar'
    assert not template.get('charts')

def seed_draft(store,template):
    state=store.get_task('r');state.phase='awaiting_final_review';store.put_task(state,state.revision)
    values={f['id']:{'value':'人工文字','source_refs':['human_edit']} for f in template['fields']}
    return save_draft(store,state,template,values,{'human_edit',state.fact_ref},{},[])

def test_report_chart_api_is_local_and_template_styles_are_versioned(tmp_path,monkeypatch):
    import app.main as main
    from app.schemas import TaskState
    store,template=fixture(tmp_path);state=seed_draft(store,template);fact_before=store.get_artifact(state.fact_ref)
    draft=store.get_artifact(state.draft_ref);monkeypatch.setattr(main,'store',store)
    with TestClient(main.app) as client:
        bad=client.post('/api/tasks/r/chart-settings',json={'expected_hash':draft['content_hash'],'styles':{'daily':'pie'}})
        assert bad.status_code==409
        response=client.post('/api/tasks/r/chart-settings',json={'expected_hash':draft['content_hash'],'styles':{'sentiment':'bar','theme':'barh'}})
        assert response.status_code==200,response.text
        new=store.get_artifact(store.get_task('r').draft_ref)
        assert new['slot_values']==draft['slot_values'] and new['fact_ref']==draft['fact_ref']
        assert store.get_artifact(new['chart_refs']['sentiment'])['style']=='bar'
        assert store.get_artifact(new['chart_refs']['theme'])['style']=='barh'
        assert store.get_artifact(state.fact_ref)==fact_before
        assert client.post('/api/tasks/r/chart-settings',json={'expected_hash':draft['content_hash'],'styles':{}}).status_code==409
        assert not any(e['type']=='model_call' for e in store.events('r'))
        parent=store.get_task('r').template_ref
        store.put_task(TaskState(id='tpl',kind='template',phase='template_confirmed',metadata={'confirmed_template_ref':parent}))
        t=store.get_task('tpl')
        changed=client.post('/api/templates/tpl/chart-version',json={'expected_revision':t.revision,'styles':{'theme':'pie'}})
        assert changed.status_code==200
        child=store.get_artifact(changed.json()['template_ref'])
        assert child['parent_ref']==parent and styles_for(child)['theme']=='pie'
        assert store.get_artifact(parent)==template
        assert store.get_task('r').template_ref==parent

def test_each_http_tool_round_billed_once_including_bad_json(tmp_path,monkeypatch):
    # WP-S8-L2：实现在 core/model_client.py，patch 必须打在被读的模块上；
    # 打 app.model_client（壳）只改壳的副本，core 侧仍读自己的 MODEL_*（静默失效）。
    import core.model_client as m
    from app.writer_tools import native_tools
    store,_=fixture(tmp_path);requests=[]
    config=configuration(store);config['mode']='off_peak';save_configuration(store,config)
    class Reply:
        def __init__(self,obj):self.obj=obj
        def __enter__(self):return io.StringIO(json.dumps(self.obj))
        def __exit__(self,*args):pass
    def request(req,timeout):
        requests.append(json.loads(req.data));first=len(requests)==1
        message={'role':'assistant','tool_calls':[{'id':'c1','function':{'name':'frozen_statistics','arguments':'{"metric":"count"}'}}]} if first else {'role':'assistant','content':'{"values":{}}'}
        return Reply({'model':'deepseek-flash','choices':[{'message':message}], 'usage':{'prompt_tokens':100 if first else 150,'completion_tokens':10 if first else 5,'prompt_cache_hit_tokens':50 if first else 100,'completion_tokens_details':{'reasoning_tokens':4 if first else 0}}})
    monkeypatch.setattr(m,'MODEL_URL','https://api.deepseek.com');monkeypatch.setattr(m,'MODEL_NAME','deepseek-flash');monkeypatch.setattr(m,'MODEL_KEY','secret')
    monkeypatch.setattr(m.urllib.request,'urlopen',request)
    # Metering imports the configured provider separately from the request client.
    # WP-S8-L1：实现在 core/usage.py，patch 必须打在被读的模块上；打 app.usage 只改壳的副本（静默失效）。
    import core.usage as u
    monkeypatch.setattr(u,'MODEL_URL','https://api.deepseek.com');monkeypatch.setattr(u,'MODEL_NAME','deepseek-flash')
    async def tool(name,args):return {'value':'4'}
    asyncio.run(m.invoke_agent('writer',{},StructuredAnswers,RunContext(store,'r'),tools=native_tools(),tool_executor=tool))
    value=task_usage(store,'r')
    assert value['requests']==2 and value['total_tokens']==265 and value['input_tokens']==250
    assert value['reasoning_tokens']==4 and value['cache_hit_tokens']==150
    assert value['estimated_cost_min']==pytest.approx(.000163)
    assert value['unpriced_requests']==0
    def invalid(req,timeout):return Reply({'model':'deepseek-flash','choices':[{'message':{'content':'invalid JSON'}}],'usage':{'prompt_tokens':3,'completion_tokens':2}})
    monkeypatch.setattr(m.urllib.request,'urlopen',invalid)
    with pytest.raises(ValueError):asyncio.run(m.invoke_agent('writer',{},StructuredAnswers,RunContext(store,'r')))
    value=task_usage(store,'r');assert value['requests']==3 and value['total_tokens']==270

def test_legacy_exchange_does_not_double_count_final_model_call(tmp_path):
    store,_=fixture(tmp_path)
    for i in range(2):
        ref=store.put_artifact('r','exchange',{'response':{'model':'deepseek-flash','usage':{'prompt_tokens':100,'completion_tokens':10,'prompt_cache_hit_tokens':20}}})
        store.append_event('r',{'type':'model_exchange','role':'writer','ref':ref,'turn':i+1})
    store.append_event('r',{'type':'model_call','role':'writer','status':'ok','usage':{'prompt_tokens':100,'completion_tokens':10}})
    store.append_event('r',{'type':'model_call','role':'writer','status':'synthetic_test'})
    value=task_usage(store,'r');assert value['requests']==2 and value['total_tokens']==220
    store.append_event('r',{'type':'model_call','role':'event_judge','status':'ok','usage':{'prompt_tokens':50,'completion_tokens':8}})
    value=task_usage(store,'r');assert value['requests']==3 and value['unpriced_requests']==1

def test_tariffs_unknown_usage_and_price_validation(tmp_path):
    store,_=fixture(tmp_path)
    assert band('2026-11-08T03:00:00+00:00','auto')==['off_peak']
    assert band('2026-11-09T02:00:00+00:00','auto')==['off_peak','peak']
    assert normalized(None) is None
    assert normalized({'prompt_tokens':10,'completion_tokens':3})['cache_split_known'] is False
    config=configuration(store);config['models']['deepseek-flash']['off_peak']['input']=-1
    with pytest.raises(ValueError):save_configuration(store,config)
    assert configuration(store)['models']['deepseek-flash']['off_peak']['input']==1

def test_reference_comparison_must_match_frozen_version_and_source_hash(tmp_path):
    import hashlib
    from app.reference_comparison import view
    store,_=fixture(tmp_path);state=store.get_task('r');source=tmp_path/'reference.xlsx';source.write_bytes(b'unchanged source')
    root=store.root/'reference-comparison';root.mkdir()
    summary={'task_id':'r','fact_ref':state.fact_ref,'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'reference_rows':817}
    (root/'summary.json').write_text(json.dumps(summary),encoding='utf-8')
    assert view(store,'r')['reference_rows']==817
    source.write_bytes(b'changed source')
    with pytest.raises(ValueError,match='reference_source_changed'):view(store,'r')

def test_word_image_geometry_uses_new_png_aspect_ratio(tmp_path):
    import hashlib,zipfile
    from lxml import etree as ET
    from app.structured_template import render_structured_docx
    store,template=fixture(tmp_path);path=__import__('pathlib').Path(template['layout_source'])
    with zipfile.ZipFile(path) as z:entries={n:z.read(n) for n in z.namelist()}
    entries['word/document.xml']=entries['word/document.xml'].replace(b'<w:drawing>',b'<w:drawing><a:xfrm><a:ext cx="1600000" cy="1600000"/></a:xfrm>')
    with zipfile.ZipFile(path,'w') as z:
        for name,content in entries.items():z.writestr(name,content)
    template['source_reports'][0]['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    report=FrozenReport(store,'r');charts={kind:chart_payload(report,kind) for kind in DEFAULTS}
    values={f['id']:{'value':'已填写','source_refs':[report.fact_ref]} for f in template['fields']}
    result=render_structured_docx(template,values,{report.fact_ref},require_complete=True,charts=charts)
    with zipfile.ZipFile(io.BytesIO(result)) as z:
        root=ET.fromstring(z.read('word/document.xml'))
    assert all(x.get('cy')=='768000' for x in root.xpath('//*[local-name()="ext"]'))

@pytest.mark.skipif(__import__('sys').platform!='win32',reason='Windows GDI rasterizes the actual historical EMF images')
def test_actual_historical_emf_is_previewable_as_png():
    from pathlib import Path
    import hashlib
    from app.chart_spec import source_image
    from PIL import Image
    path=Path(__file__).resolve().parents[1]/'2026年6月安顺市网络舆情分析报告.docx'
    if not path.exists():pytest.skip('Historical reference not available in this checkout')
    template={'source_reports':[{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}]}
    data,mime=source_image(template,'sentiment')
    assert mime=='image/png' and data.startswith(b'\x89PNG')
    with Image.open(io.BytesIO(data)) as image:assert image.width>0 and image.height>0
