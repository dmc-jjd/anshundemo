from __future__ import annotations
import io,zipfile
from fastapi.testclient import TestClient
import app.main as main
from app.storage import Store
from app.workflow import Dependencies

async def analysis_adapter(role,payload):
    if role=='event_judge' and 'events' in payload:return {'groups':[{'group_ids':[x['id']]} for x in payload['events']],'uncertain_pairs':[]}
    if role=='event_judge':return {'items':[{'id':x['id'],'decision':'different','reason':'synthetic test'} for x in payload['pairs']]}
    if role=='event_classifier':return {'items':[{'id':x['id'],'category':'其他','status':'classified','reason':'synthetic test'} for x in payload['events']]}
    if role=='event_summarizer':return {'items':[{'id':x['id'],'status':'complete','summary':'来源记录反映有关问题，具体情况以原文为准。','source_refs':[x['evidence'][0]['ref']]} for x in payload['events']]}
    raise ValueError('unexpected role')

HEADERS=['标题','发布时间','来源信息','作者','作者Id','事件分类','网址','媒体环节','媒体属性','媒体级别','舆情调性','是否预警','摘要']

def sample_xlsx():
    def cell(col,row,value):
        return f'<c r="{chr(65+col)}{row}" t="inlineStr"><is><t>{value}</t></is></c>'
    rows=[HEADERS]
    for i,(title,sentiment,warning) in enumerate([('景区游客投诉排队','负面','已预警'),('景区游客后续反馈','负面','未预警'),('本地学校活动','正面','未预警'),('社区服务消息','中性','未预警'),('市场监管通报','负面','已预警'),('医院服务报道','正面','未预警')],2):
        rows.append([title,'2026-10-'+str(i).zfill(2),'测试来源','','','','','网站','其他','其他',sentiment,warning,title])
    xml='<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(f'<row r="{i}">'+''.join(cell(j,i,v) for j,v in enumerate(row))+'</row>' for i,row in enumerate(rows,1))+'</sheetData></worksheet>'
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z: z.writestr('xl/worksheets/sheet3.xml',xml)
    return out.getvalue()

def test_public_api_fallback_keeps_scope_and_human_gate(tmp_path,monkeypatch):
    store=Store(tmp_path/'data'); uploads=tmp_path/'uploads'; uploads.mkdir()
    monkeypatch.setattr(main,'store',store); monkeypatch.setattr(main,'deps',Dependencies(store,analysis_adapter)); monkeypatch.setattr(main,'UPLOADS',uploads)
    with TestClient(main.app) as client:
        up=client.post('/api/files',files={'file':('sample.xlsx',sample_xlsx(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
        assert up.status_code==200
        body={'file_ids':[up.json()['id']],'sheet_index':3,'mode':'fallback','report_month':'2026-10','template_ref':'anshun-monthly-colored'}
        task=client.post('/api/report-tasks',json=body,headers={'Idempotency-Key':'sample-v1'})
        assert task.status_code==200
        task_id=task.json()['id']
        duplicate=client.post('/api/report-tasks',json=body,headers={'Idempotency-Key':'sample-v1'})
        assert duplicate.json()['id']==task_id
        state=client.get('/api/tasks/'+task_id).json()
        assert state['phase']=='awaiting_review'
        refs=state['result_refs']
        assert len(store.get_artifact(refs['filter_records:positive'])['records'])==2
        assert len(store.get_artifact(refs['filter_records:neutral'])['records'])==1
        assert len(store.get_artifact(refs['filter_records:negative'])['records'])==3
        assert len(store.get_artifact(refs['filter_records:warning'])['records'])==2
        assert len(store.get_artifact(refs['filter_records:negative_or_warning'])['records'])==3
        assert len(store.get_artifact(refs['group_events'])['all_record_ids'])==3
        assert client.post(f'/api/tasks/{task_id}/confirm-facts').status_code==409
        assert client.post(f'/api/tasks/{task_id}/preview-draft').status_code==409
        assert [x['kind'] for x in state['review_items'] if x['status']=='open']==['data_review']
        review=client.get(f'/api/tasks/{task_id}/review-data').json()
        assert len(review['records'])==3
        assert client.post(f'/api/tasks/{task_id}/event-settings',json={'expected_revision':review['revision'],'threshold':1.5}).status_code==422
        assert client.post(f'/api/tasks/{task_id}/event-settings',json={'expected_revision':review['revision']-1,'threshold':.6}).status_code==409
        changed=client.post(f'/api/tasks/{task_id}/event-settings',json={'expected_revision':review['revision'],'threshold':.6})
        assert changed.status_code==200
        review=client.get(f'/api/tasks/{task_id}/review-data').json()
        assert review['method']['threshold']==.6
        bad=client.post(f'/api/tasks/{task_id}/confirm-data',json={'expected_revision':review['revision'],'groups':[],'themes':review['themes']})
        assert bad.status_code==409
        accepted=client.post(f'/api/tasks/{task_id}/confirm-data',json={'expected_revision':review['revision'],'groups':review['event_groups'],'themes':review['themes']})
        assert accepted.status_code==200 and accepted.json()['fact_ref']
        assert accepted.json()['phase']=='facts_frozen'
        assert client.post(f'/api/tasks/{task_id}/event-settings',json={'expected_revision':accepted.json()['revision'],'threshold':.5}).status_code==409
        assert client.post(f'/api/tasks/{task_id}/confirm-data',json={'expected_revision':review['revision'],'groups':review['event_groups'],'themes':review['themes']}).status_code==409
        events=client.get(f'/api/tasks/{task_id}/logs').json()
        assert len(client.get(f'/api/tasks/{task_id}/events?limit=5').json())==5
        assert any(e['type']=='fallback_started' and e['goal_by_step']['filter_union_scope']==['B30_categories_districts_top10'] for e in events)
