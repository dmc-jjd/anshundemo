import asyncio
import copy
import json
from fastapi.testclient import TestClient
from app.storage import Store
from app.schemas import TaskState
from app.workflow import Dependencies,run_template
from app.template_validation import collect_errors
from app.timing import snapshot
from test_semantic_template import reports
from test_structured_template import semantic_analyst


def task_store(tmp_path):
    docs=reports(tmp_path);store=Store(tmp_path/'store')
    store.put_task(TaskState(id='repair',kind='template',phase='queued',metadata={'paths':[d['path'] for d in docs]}))
    return store


def corrupt(raw):
    raw=copy.deepcopy(raw)
    raw['fields'][0]['source_type']='statistics'
    raw['fields'][0]['sources'][0]['text']='不存在的原文片段'
    return raw


def test_all_errors_sent_together_and_third_round_can_pass(tmp_path):
    store=task_store(tmp_path);requests=[]
    async def analyst(role,payload):
        requests.append(payload)
        good=await semantic_analyst(role,payload)
        return corrupt(good) if len(requests)<3 else good
    result=asyncio.run(run_template(Dependencies(store,analyst),'repair'))
    assert result.phase=='awaiting_template_confirmation',result.metadata.get('template_error')
    assert len(requests)==3
    codes={e['code'] for e in requests[1]['repair']['errors']}
    assert {'statistics_owned_by_data','source_text_mismatch'}<=codes
    assert len(requests[2]['repair']['history'])==2
    batch=next(iter(result.metadata['template_batches'].values()))
    assert [r['number'] for r in batch['rounds']]==[1,2,3]
    assert all(r['elapsed_ms']>=0 and r['model_elapsed_ms']>=0 and r['validation_elapsed_ms']>=0 and r['request_ref'] for r in batch['rounds'])
    assert snapshot(result)['rounds'][-1]['status']=='passed'


def test_third_failure_has_human_editor_and_cannot_be_bypassed(tmp_path,monkeypatch):
    import app.main as main
    store=task_store(tmp_path);calls=[];good_candidate=None
    async def analyst(role,payload):
        nonlocal good_candidate
        calls.append(payload);good_candidate=await semantic_analyst(role,payload)
        return corrupt(good_candidate)
    deps=Dependencies(store,analyst)
    failed=asyncio.run(run_template(deps,'repair'))
    assert failed.phase=='template_manual_review' and len(calls)==3
    asyncio.run(run_template(deps,'repair'))
    assert len(calls)==3
    monkeypatch.setattr(main,'store',store);monkeypatch.setattr(main,'deps',deps)
    with TestClient(main.app) as client:
        view=client.get('/api/templates/repair/exceptions').json()
        batch=view['batches'][0]
        assert len(batch['rounds'])==3 and len(view['sources'])==3
        assert client.post('/api/tasks/repair/resume').status_code==409
        assert client.post('/api/templates/repair/confirm',json={'expected_revision':failed.revision,'candidate_ref':'anything','reason':'bypass'}).status_code==409
        item=failed.review_items[0]
        assert client.post('/api/tasks/repair/decisions',json={'item_id':item['id'],'expected_revision':failed.revision,'action':'confirm','reason':'bypass'}).status_code==409
        body={'expected_revision':view['revision'],'input_ref':view['input_ref'],'candidate':batch['candidate'],'reason':'按原文修正字段用途与来源'}
        url=f'/api/templates/repair/exceptions/{batch["id"]}/resolve'
        invalid=client.post(url,json=body)
        assert invalid.status_code==422 and len(invalid.json()['errors'])>=2
        assert store.get_task('repair').phase=='template_manual_review'
        body['candidate']=good_candidate
        accepted=client.post(url,json=body)
        assert accepted.status_code==200
        ready=store.get_task('repair')
        assert ready.phase=='awaiting_template_confirmation' and len(calls)==3
        assert ready.metadata['template_validation_ref'] and not ready.metadata.get('confirmed_template_ref')
        assert client.post(url,json=body).status_code==409


def test_transport_failure_does_not_become_human_review_or_use_semantic_round(tmp_path):
    store=task_store(tmp_path)
    async def timeout(role,payload):raise TimeoutError('test network timeout')
    failed=asyncio.run(run_template(Dependencies(store,timeout),'repair'))
    assert failed.phase=='template_review_failed'
    batch=next(iter(failed.metadata['template_batches'].values()))
    assert batch['rounds'][0]['status']=='transport_error'
    assert not any(r['status']=='invalid' for r in batch['rounds'])
    ready=asyncio.run(run_template(Dependencies(store,semantic_analyst),'repair'))
    assert ready.phase=='awaiting_template_confirmation'
    batch=next(iter(ready.metadata['template_batches'].values()))
    assert batch['rounds'][-1]['number']==1 and batch['rounds'][-1]['status']=='passed'


def test_timing_survives_reload_does_not_reset_on_updates_and_separates_wait(tmp_path,monkeypatch):
    import core.timing as timing
    clock=['2026-11-07T00:00:00+00:00']
    monkeypatch.setattr(timing,'stamp',lambda:clock[0])
    store=Store(tmp_path/'store');state=TaskState(id='clock',kind='template',phase='queued');store.put_task(state)
    clock[0]='2026-11-07T00:00:10+00:00';state.phase='template_model_reviewing';store.put_task(state,state.revision)
    clock[0]='2026-11-07T00:00:20+00:00';store.put_task(state,state.revision)
    clock[0]='2026-11-07T00:00:40+00:00';state.phase='template_manual_review';store.put_task(state,state.revision)
    value=timing.snapshot(Store(tmp_path/'store').get_task('clock'),'2026-11-07T00:01:40+00:00')
    assert value['total_ms']==100_000 and value['processing_ms']==40_000 and value['human_wait_ms']==60_000
    clock[0]='2026-11-07T00:02:00+00:00';state.phase='template_confirmed';store.put_task(state,state.revision)
    stopped=timing.snapshot(state,'2026-11-07T02:00:00+00:00')
    assert stopped['total_ms']==120_000 and stopped['human_wait_ms']==80_000


def test_parallel_round_durations_are_not_added_to_wall_time(tmp_path,monkeypatch):
    import core.timing as timing
    monkeypatch.setattr(timing,'stamp',lambda:'2026-11-07T00:00:00+00:00')
    store=Store(tmp_path/'store');state=TaskState(id='parallel',kind='template',phase='template_model_reviewing');store.put_task(state)
    state.metadata['template_batches']={str(i):{'targets':[i],'rounds':[{'number':1,'started_at':'2026-11-07T00:00:00+00:00','status':'running'}]} for i in range(2)}
    result=snapshot(state,'2026-11-07T00:00:01+00:00')
    assert result['processing_ms']==1_000 and sum(r['elapsed_ms'] for r in result['rounds'])==2_000
