import asyncio,base64,hashlib,io,json,zipfile
from pathlib import Path
import pytest
from app.storage import Store
from app.schemas import TaskState,ToolCall
from app.frozen_report import FrozenReport,query_materials,MissingReportInput
from app.writer_tools import chart_payload,CHARTS
from app.structured_writer import write_structured_preview
from app.structured_template import _schema,render_structured_docx
from app.workflow import Dependencies
from app.writing_review import edit_structured

def fixture(tmp_path):
    s=Store(tmp_path/'store');tid='r'
    rows=[{'id':f'r{i}','title':f'事件{i}','summary':f'原文梗概{i}','source':'省报','media_level':'省级','published':'2026-10-02','sentiment':'负面' if i<3 else '正面','warning':'是' if i in (0,1) else '否','platform':'网站'} for i in range(4)]
    metrics={'record_count':4,'sentiment':{'负面':3,'正面':1},'daily_count':{'2026-10-02':4},'platform':{'网站':4},'peak_day':'2026-10-02'}
    refs={'import_records':s.put_artifact(tid,'records',{'records':rows}),
          'calculate_metrics':s.put_artifact(tid,'metrics',metrics),
          'confirmed_event_groups':s.put_artifact(tid,'groups',{'groups':[{'id':'g1','representative_id':'r0','member_ids':['r0','r1']},{'id':'g2','representative_id':'r2','member_ids':['r2']}]}),
          'confirmed_theme_groups':s.put_artifact(tid,'themes',{'groups':[{'candidate_theme':'市场监管','member_ids':['r0','r1']},{'candidate_theme':'交通管理','member_ids':['r2']}]}),
          'resolve_locality':s.put_artifact(tid,'geo',{'items':[{'record_id':'r0','candidates':['西秀区']},{'record_id':'r1','candidates':['平坝区']} ]})}
    fact=s.put_artifact(tid,'facts',{'metrics':metrics,'result_refs':refs,'report_month':'2026-10','top10':[],'decisions':[{'large_private_review':'do not transmit'}]})
    # Real OOXML fixture with five image geometries and independently editable blocks.
    path=tmp_path/'layout.docx'
    w='http://schemas.openxmlformats.org/wordprocessingml/2006/main';a='http://schemas.openxmlformats.org/drawingml/2006/main';r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    paras=''.join('<w:p><w:r><w:t>历史</w:t></w:r></w:p>' for _ in range(4))
    draws=''.join('<w:p><w:r><w:drawing><a:blip r:embed="old"/></w:drawing></w:r></w:p>' for _ in CHARTS)
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('word/document.xml',f'<w:document xmlns:w="{w}" xmlns:a="{a}" xmlns:r="{r}"><w:body>{paras}{draws}</w:body></w:document>')
        z.writestr('word/_rels/document.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
    fields=[{'id':key,'owner':owner,'kind':'text','display_name':key,'semantic':key,'sources':[{'text':'历史'}],'value_schema':{'type':'string','minLength':1}} for key,owner in [('b17_warning_count','data'),('w1','writer'),('w2','writer'),('b5_issue_no','data')]]
    t={'status':'confirmed_by_human','layout_source':str(path),'source_reports':[{'sha256':hashlib.sha256(path.read_bytes()).hexdigest()},{'sha256':'other'}], 'comparison_ref':'comparison','fields':fields,
       'blocks':[{'index':i,'kind':'paragraph','parts':[{'field':f['id']}]} for i,f in enumerate(fields)],'output_schema':_schema(fields),'writer_schema':_schema(fields,True)}
    ref=s.put_artifact(tid,'template',t)
    s.put_task(TaskState(id=tid,kind='report',phase='facts_frozen',fact_ref=fact,template_ref=ref,result_refs=refs,tool_calls=40,metadata={'template_rules':{'first_warning_scope':'negative_or_warning'}}))
    return s,t

def test_frozen_calculations_denominators_and_no_silent_parameters(tmp_path):
    s,t=fixture(tmp_path);r=FrozenReport(s,'r')
    assert r.calculate({'metric':'count','scope':'confirmed_events'})['value']=='2'
    assert r.calculate({'metric':'count','scope':'negative_warning_events'})['value']=='1'
    assert r.calculate({'metric':'warning_percentage','scope':'confirmed_events'})['value']=='50.00%'
    assert r.calculate({'metric':'sentiment_percentage','sentiment':'负面'})['value']=='75.00%'
    assert sum(r.categories_for().values())==sum(r.counties_for().values())==2
    assert r.counties_for()=={'属地不明':1,'跨区涉及':1}
    with pytest.raises(MissingReportInput):r.calculate({'metric':'publish_day'})
    assert 'decisions' not in r.summary()
    q=query_materials(r,{'focus':'negative_events','limit':1})
    assert q['items'][0]['summary'] and q['next_offset']==1

def test_matplotlib_five_figures_and_docx_relationships(tmp_path):
    s,t=fixture(tmp_path);r=FrozenReport(s,'r');charts={name:chart_payload(r,name) for name in CHARTS}
    assert all(base64.b64decode(c['png_base64']).startswith(b'\x89PNG') for c in charts.values())
    values={f['id']:{'value':'已填','source_refs':[r.fact_ref]} for f in t['fields']}
    with pytest.raises(ValueError,match='missing_current_chart'):render_structured_docx(t,values,{r.fact_ref},require_complete=True)
    content=render_structured_docx(t,values,{r.fact_ref},require_complete=True,charts=charts)
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        assert len([name for name in z.namelist() if 'frozen_chart_' in name])==5
        assert b'{{' not in z.read('word/document.xml')
        assert z.read('word/_rels/document.xml.rels').count(b'rIdFrozenChart')==5

def test_writer_tool_access_retry_continues_then_human_is_final(tmp_path):
    s,t=fixture(tmp_path);calls=[]
    async def model(role,payload):
        calls.append(payload)
        assert len(json.dumps(payload,ensure_ascii=False))<30000
        assert 'large_private_review' not in json.dumps(payload)
        if 'reference_requests' in payload:return {'selections':[]}
        key=payload['remaining_fields'][0]
        if key=='w1':return {'values':{'w1':{'value':'bad','source_refs':['fake']}}}
        if not payload.get('tool_results'):return {'tool_calls':[{'function':{'name':'query_frozen_materials','arguments':{'focus':'negative_events','limit':1}}}]}
        ref=payload['tool_results'][-1]['result']['items'][0]['ref']
        return {'values':{'w2':{'value':'有来源的写作','source_refs':[ref]}}}
    state=asyncio.run(write_structured_preview(Dependencies(s,model),'r'));draft=s.get_artifact(state.draft_ref)
    assert set(state.metadata['missing_fields'])=={'w1','b5_issue_no'}
    assert draft['slot_values']['b17_warning_count']['value']=='2'
    assert len(draft['chart_refs'])==5 and not state.metadata['pending_charts']
    assert sum(p.get('remaining_fields')==['w1'] for p in calls)==1
    assert sum('reference_requests' in p for p in calls)==2
    state.phase='awaiting_final_review';s.put_task(state,state.revision)
    count=len(calls)
    result=edit_structured(s,'r',{'w1':'人工确认的文字'},draft['content_hash'],{'issue_number':10,'publication_date':'2026-11-08'})
    assert not result['missing'] and len(calls)==count
    with pytest.raises(ValueError,match='stale_draft_hash'):edit_structured(s,'r',{'w1':'旧版本'},draft['content_hash'])
    state=asyncio.run(write_structured_preview(Dependencies(s,model),'r'))
    assert len(calls)==count and s.get_artifact(state.draft_ref)['slot_values']['w1']['source_refs']==['human_edit']
    assert s.get_task('r').fact_ref==draft['fact_ref']

def test_native_http_tools_roundtrip_and_audit(tmp_path,monkeypatch):
    # WP-S8-L2：实现在 core/model_client.py，patch 必须打在被读的模块上（打壳=改副本，静默失效）。
    import core.model_client as m
    from app.tool_executor import RunContext
    from app.structured_writer import StructuredAnswers
    s,t=fixture(tmp_path);requests=[]
    class Response:
        def __init__(self,obj):self.obj=obj
        def __enter__(self):return io.StringIO(json.dumps(self.obj))
        def __exit__(self,*args):pass
    def urlopen(req,timeout):
        data=json.loads(req.data);requests.append(data)
        message={'role':'assistant','tool_calls':[{'id':'call1','type':'function','function':{'name':'frozen_statistics','arguments':'{"metric":"count"}'}}]} if len(requests)==1 else {'role':'assistant','content':'{"values":{}}'}
        return Response({'choices':[{'message':message,'finish_reason':'stop'}]})
    monkeypatch.setattr(m,'MODEL_URL','https://example.invalid');monkeypatch.setattr(m,'MODEL_KEY','test-secret');monkeypatch.setattr(m,'MODEL_NAME','test')
    monkeypatch.setattr(m.urllib.request,'urlopen',urlopen)
    from app.writer_tools import native_tools
    async def executor(name,args):return {'value':'4','source_refs':['fact']}
    asyncio.run(m.invoke_agent('writer',{},StructuredAnswers,RunContext(s,'r'),tools=native_tools(),tool_executor=executor))
    assert requests[1]['messages'][-1]['role']=='tool'
    assert requests[0]['thinking']=={'type':'enabled'}
    logs=[e for e in s.events('r') if e['type']=='model_exchange']
    assert len(logs)==2 and 'test-secret' not in json.dumps(s.get_artifact(logs[0]['ref']))

def test_api_parameters_manual_fallback_and_final_chart_gate(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main
    s,t=fixture(tmp_path);calls=[]
    async def writer(role,payload):
        calls.append(role)
        ref=payload['evidence'][0]['ref']
        return {'values':{key:{'value':'测试文字','source_refs':[ref]} for key in payload['remaining_fields']}}
    state=asyncio.run(write_structured_preview(Dependencies(s,writer),'r'))
    state.phase='awaiting_final_review';s.put_task(state,state.revision)
    monkeypatch.setattr(main,'store',s);monkeypatch.setattr(main,'deps',Dependencies(s,writer))
    count=len(calls)
    with TestClient(main.app) as client:
        view=client.get('/api/tasks/r/draft-view').json();draft_hash=view['draft']['content_hash']
        assert view['missing']==['b5_issue_no'] and not view['can_approve']
        assert client.get('/api/tasks/r/charts/theme').content.startswith(b'\x89PNG')
        assert client.post('/api/tasks/r/slot-values',json={'values':{'b17_warning_count':'99'},'expected_hash':draft_hash}).status_code==409
        assert client.post('/api/tasks/r/report-parameters',json={'expected_hash':draft_hash,'publication_date':'not-a-date'}).status_code==409
        saved=client.post('/api/tasks/r/report-parameters',json={'expected_hash':draft_hash,'issue_number':10,'publication_date':'2026-11-08'})
        assert saved.status_code==200 and saved.json()['missing']==[]
        assert len(calls)==count
        assert client.post('/api/tasks/r/slot-values',json={'values':{'w1':'旧版本'},'expected_hash':draft_hash}).status_code==409
        view=client.get('/api/tasks/r/draft-view').json()
        assert not view['can_approve'] and not view['review_ready']  # Complete fields still require the two real reviews.
        assert client.post('/api/tasks/r/slot-values',json={'values':{'w1':'人工最终修正'},'expected_hash':view['draft']['content_hash']}).status_code==200
        assert len(calls)==count
        # Metadata alone must never bypass missing figure validation.
        state=s.get_task('r');draft=s.get_artifact(state.draft_ref);draft['chart_refs']={}
        state.draft_ref=s.put_artifact('r','broken_draft',draft);s.put_task(state,state.revision)
        denied=client.post('/api/tasks/r/approve',json={'draft_hash':draft['content_hash']})
        assert denied.status_code==409 and 'missing_current_chart' in denied.text


def test_catalog_covers_period_platform_and_record_table(tmp_path):
    s,t=fixture(tmp_path);r=FrozenReport(s,'r')
    assert r.calculate({'metric':'peak_date'})['value']=='10月2'
    assert r.calculate({'metric':'peak_date','include_day_suffix':True})['value']=='10月2日'
    assert r.calculate({'metric':'peak_date','include_year':True,'include_day_suffix':True})['value']=='2026年10月2日'
    assert r.calculate({'metric':'period_start','include_year':True,'include_day_suffix':True})['value']=='2026年10月2日'
    assert r.calculate({'metric':'period_end','include_year':True,'include_day_suffix':True})['value']=='2026年10月2日'
    assert r.calculate({'metric':'platform_count','platforms':['网站']})['value']=='4'
    assert r.calculate({'metric':'platform_count','platforms':['视频']})['value']=='0'
    assert r.calculate({'metric':'platform_count','platforms':['网站'],'sentiment':'正面'})['value']=='1'
    assert r.calculate({'metric':'platform_count','exclude_platforms':['网站']})['value']=='0'
    assert r.calculate({'metric':'platform_names','sentiment':'负面'})['value']=='网站'
    assert r.calculate({'metric':'platform_source_detail'})['value']=='网站主要来源于省报'
    table=r.calculate({'metric':'record_table','sentiment':'正面','include_day_suffix':True})['value']
    assert table==[['1','10月2日','事件3','省报','']]

def test_package_field_calculations_fill_unbound_data_fields(tmp_path):
    from app.structured_writer import calculation_for
    from core.field_calculations import load as load_field_calculations
    binds=load_field_calculations('ruyuan_yuebao')
    assert binds['b1_web']['metric']=='platform_count'
    s,t=fixture(tmp_path);r=FrozenReport(s,'r')
    field={'id':'b1_web','owner':'data','display_name':'网页条数','binding':None}
    result=calculation_for(field,r,{},package='ruyuan_yuebao')
    assert result['value']=='4'
    full=calculation_for({'id':'b12_peak_date_full','owner':'data','display_name':'峰值日期全写','binding':None},r,{},package='ruyuan_yuebao')
    assert full['value']=='2026年10月2日'


def test_pending_charts_ignore_layout_cover_and_textbox(tmp_path):
    from app.structured_writer import pending_chart_count
    w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    a='http://schemas.openxmlformats.org/drawingml/2006/main'
    r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    c='http://schemas.openxmlformats.org/drawingml/2006/chart'
    wp='http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
    path=tmp_path/'layout.docx'
    deco=(f'<w:p><w:r><w:drawing><wp:docPr xmlns:wp="{wp}" name="图片 3"/><a:blip r:embed="cover"/></w:drawing></w:r></w:p>'
          f'<w:p><w:r><w:drawing><wp:docPr xmlns:wp="{wp}" name="文本框 9"/></w:drawing></w:r></w:p>')
    charts=''.join(f'<w:p><w:r><w:drawing><c:chart xmlns:c="{c}" r:id="rId{i}"/></w:drawing></w:r></w:p>' for i in range(4))
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('word/document.xml',f'<w:document xmlns:w="{w}" xmlns:a="{a}" xmlns:r="{r}"><w:body>{deco}{charts}</w:body></w:document>')
    template={'layout_source':str(path),'charts':[{'id':name} for name in ('platform','daily','platform_warning','theme')],'fields':[{'id':'w1'}]}
    filled={'platform':'a','daily':'b','platform_warning':'c','theme':'d'}
    assert pending_chart_count(template, filled)==0
    assert pending_chart_count(template, {'platform':'a','daily':'b'})==2
    # layouts that only use image placeholders and have no charts[] keep the legacy drawing count
    legacy={'layout_source':str(path),'fields':[]}
    assert pending_chart_count(legacy, filled)==2


def test_render_places_charts_on_chart_slots_not_cover_or_textbox(tmp_path):
    """封面图和文本框不占 drawing_index；统计图（无 blip 的 Word 图表）改成 PNG。

    已确认模板若仍按「前 4 个图形」写成 drawing_index=1..4（乳源现状），
    渲染也必须把 1 号图放到第一张统计图，而不是封面。
    """
    from lxml import etree as ET
    w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    a='http://schemas.openxmlformats.org/drawingml/2006/main'
    r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    c='http://schemas.openxmlformats.org/drawingml/2006/chart'
    wp='http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
    path=tmp_path/'layout.docx'
    deco=(f'<w:p><w:r><w:drawing><wp:inline xmlns:wp="{wp}"><wp:extent cx="100" cy="200"/><wp:docPr id="3" name="图片 3"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><a:blip r:embed="cover"/></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
          f'<w:p><w:r><w:drawing><wp:inline xmlns:wp="{wp}"><wp:docPr id="9" name="文本框 9"/></wp:inline></w:drawing></w:r></w:p>')
    slots=''.join(
        f'<w:p><w:r><w:t>图{i}</w:t><w:drawing><wp:inline xmlns:wp="{wp}"><wp:extent cx="5615940" cy="2983865"/><wp:docPr id="{10+i}" name="图表 {i}"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart xmlns:c="{c}" r:id="rIdChart{i}"/></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
        for i in range(1,5)
    )
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('word/document.xml',f'<w:document xmlns:w="{w}" xmlns:a="{a}" xmlns:r="{r}"><w:body>{deco}{slots}</w:body></w:document>')
        z.writestr('word/_rels/document.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
    s,template=fixture(tmp_path/'store')
    report=FrozenReport(s,'r')
    kinds=tuple(CHARTS[:4])
    charts={name:chart_payload(report,name) for name in kinds}
    template['layout_source']=str(path)
    template['source_reports']=[{'sha256':hashlib.sha256(path.read_bytes()).hexdigest()},{'sha256':'other'}]
    template['charts']=[{'id':name,'drawing_index':index,'title':name,'style':'pie','style_basis':'t','scope':'all','unit':'条'}
                        for index,name in enumerate(kinds,1)]
    values={f['id']:{'value':'已填','source_refs':[report.fact_ref]} for f in template['fields']}
    content=render_structured_docx(template,values,{report.fact_ref},require_complete=True,charts=charts)
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        frozen=[name for name in z.namelist() if 'frozen_chart_' in name]
        assert len(frozen)==4
        root=ET.fromstring(z.read('word/document.xml'))
        drawings=root.xpath('//*[local-name()="drawing"]')
        assert len(drawings)==6
        cover_blips=drawings[0].xpath('.//*[local-name()="blip"]')
        assert cover_blips and cover_blips[0].get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')=='cover'
        assert not drawings[1].xpath('.//*[local-name()="blip"]')
        assert '文本框 9' in (drawings[1].xpath('.//*[local-name()="docPr"]')[0].get('name') or '')
        embeds=[]
        for drawing in drawings[2:]:
            assert not drawing.xpath('.//*[local-name()="chart"]')
            blips=drawing.xpath('.//*[local-name()="blip"]')
            assert blips
            embeds.append(blips[0].get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed'))
        assert embeds==['rIdFrozenChart1','rIdFrozenChart2','rIdFrozenChart3','rIdFrozenChart4']
        xml=z.read('word/document.xml')
        assert b'{{CHART_' not in xml


def test_peak_date_honors_scope_and_differs_from_all_records(tmp_path):
    from core.frozen_report import Calculation
    s=Store(tmp_path/'store');tid='p'
    # 全量高峰在 10月2（5条未预警/正面），已预警负面高峰在 10月8（3条）。
    rows=[]
    for i in range(5):
        rows.append({'id':f'a{i}','title':f'信息{i}','summary':f'摘要{i}','source':'省报','media_level':'省级','published':'2026-10-02','sentiment':'正面','warning':'否','platform':'网站'})
    for i in range(3):
        rows.append({'id':f'n{i}','title':f'预警{i}','summary':f'预警摘要{i}','source':'省报','media_level':'省级','published':'2026-10-08','sentiment':'负面','warning':'是','platform':'网站'})
    rows.append({'id':'n3','title':'预警少','summary':'预警少摘要','source':'省报','media_level':'省级','published':'2026-10-05','sentiment':'负面','warning':'是','platform':'网站'})
    metrics={'record_count':len(rows),'sentiment':{'正面':5,'负面':4},'daily_count':{'2026-10-02':5,'2026-10-05':1,'2026-10-08':3},'platform':{'网站':len(rows)},'peak_day':'2026-10-02'}
    groups=[{'id':'gpos','representative_id':'a0','member_ids':[f'a{i}' for i in range(5)]},
            {'id':'gneg','representative_id':'n0','member_ids':['n0','n1','n2','n3']}]
    refs={'import_records':s.put_artifact(tid,'records',{'records':rows}),
          'calculate_metrics':s.put_artifact(tid,'metrics',metrics),
          'confirmed_event_groups':s.put_artifact(tid,'groups',{'groups':groups}),
          'confirmed_theme_groups':s.put_artifact(tid,'themes',{'groups':[]}),
          'resolve_locality':s.put_artifact(tid,'geo',{'items':[]})}
    fact=s.put_artifact(tid,'facts',{'metrics':metrics,'result_refs':refs,'report_month':'2026-10'})
    s.put_task(TaskState(id=tid,kind='report',phase='facts_frozen',fact_ref=fact,result_refs=refs))
    r=FrozenReport(s,tid)
    assert r.calculate({'metric':'peak_date'})['value']=='10月2'
    assert r.calculate({'metric':'peak_date','scope':'negative_warning_events'})['value']=='10月8'
    assert r.calculate({'metric':'peak_date','scope':'negative_warning_events','include_year':True,'include_day_suffix':True})['value']=='2026年10月8日'
    Calculation.model_validate({'metric':'peak_date','scope':'negative_warning_events'})
    with pytest.raises(Exception):
        Calculation.model_validate({'metric':'sentiment_count','sentiment':'负面','scope':'negative_warning_events'})
    from app.structured_writer import calculation_for
    full=calculation_for({'id':'b12_peak_date_full','owner':'data','display_name':'峰值日期全写','binding':None},r,{},package='ruyuan_yuebao')
    short=calculation_for({'id':'b12_peak_date_short','owner':'data','display_name':'峰值月日','binding':None},r,{},package='ruyuan_yuebao')
    assert full['value']=='2026年10月8日'
    assert short['value']=='10月8日'
