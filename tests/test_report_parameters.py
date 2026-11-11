import io,zipfile,json
from pathlib import Path
from fastapi.testclient import TestClient
from app.report_parameters import suggestions
from app.storage import Store
from app.schemas import TaskState
from app.frozen_report import FrozenReport
from test_frozen_writer import fixture

def source(tmp_path,month,issue,year=2026):
    path=tmp_path/f'{year}-{month}.docx'
    from test_structured_template import docx
    return docx(path,f'{year}年第{issue}期 {year}年{month}月网络舆情分析报告')

def test_issue_inference_needs_consistent_history_and_resets_across_years(tmp_path):
    template={'source_reports':[{'path':str(tmp_path/'6.docx')}]}
    # Use actual Word headers, not filename-based period guesses.
    from test_structured_template import docx
    paths=[tmp_path/f'{month}.docx' for month in (6,7,8)]
    for month,path in zip((6,7,8),paths):docx(path,f'2026年第{month}期 安顺市2026年{month}月网络舆情分析报告')
    template={'source_reports':[{'path':str(p)} for p in paths]}
    assert suggestions(template,'2026-10')['issue_number']==10
    assert suggestions(template,'2027-01')['issue_number'] is None
    docx(paths[-1],'2026年第99期 安顺市2026年8月网络舆情分析报告')
    assert suggestions(template,'2026-10')['issue_number'] is None
    assert suggestions(template,'2026-08')['issue_number']==99

def test_parameters_can_be_saved_before_data_confirmation_without_model(tmp_path,monkeypatch):
    import app.main as main
    store,template=fixture(tmp_path);state=store.get_task('r');state.phase='awaiting_review';store.put_task(state,state.revision)
    fact=state.fact_ref
    monkeypatch.setattr(main,'store',store)
    with TestClient(main.app) as client:
        reply=client.post('/api/tasks/r/report-parameters',json={'expected_revision':state.revision,'issue_number':10,'publication_date':'2026-11-04'})
        assert reply.status_code==200,reply.text
        current=store.get_task('r');assert current.fact_ref==fact
        report=FrozenReport(store,'r')
        assert report.calculate({'metric':'issue_number'})['value']=='10'
        assert report.calculate({'metric':'publish_month'})['value']=='11'
        assert report.calculate({'metric':'publish_day'})['value']=='4'
        assert client.post('/api/tasks/r/report-parameters',json={'expected_revision':state.revision,'issue_number':11}).status_code==409
        assert not any(e['type'].startswith('model_') for e in store.events('r'))

def test_report_creation_carries_explicit_parameters_without_generating_them(tmp_path,monkeypatch):
    import app.main as main
    store=Store(tmp_path/'store');uploads=tmp_path/'uploads';uploads.mkdir()
    monkeypatch.setattr(main,'store',store);monkeypatch.setattr(main,'UPLOADS',uploads)
    async def no_processing(*args):pass
    monkeypatch.setattr(main,'run_report_graph',no_processing)
    (uploads/'f.xlsx').write_bytes(b'fixture; processing disabled')
    with TestClient(main.app) as client:
        result=client.post('/api/report-tasks',json={'file_ids':['f'],'template_ref':'anshun-monthly-colored','report_month':'2026-10','issue_number':10,'publication_date':'2026-11-04'})
        assert result.status_code==200,result.text
        t=store.get_task(result.json()['id'])
        assert t.metadata['report_parameters']=={'issue_number':10,'publication_date':'2026-11-04'}
        invalid=client.post('/api/report-tasks',json={'file_ids':['f'],'template_ref':'anshun-monthly-colored','issue_number':10,'publication_date':'2026-13-04'})
        assert invalid.status_code==422
