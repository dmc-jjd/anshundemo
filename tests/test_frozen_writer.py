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
