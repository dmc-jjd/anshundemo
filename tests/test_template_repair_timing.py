import asyncio
import json
from fastapi.testclient import TestClient
from app.storage import Store
from app.schemas import TaskState
from app.workflow import Dependencies,run_template
from app.timing import snapshot
from test_semantic_template import reports
from test_structured_template import semantic_analyst


def task_store(tmp_path):
    docs=reports(tmp_path);store=Store(tmp_path/'store')
    store.put_task(TaskState(id='repair',kind='template',phase='queued',metadata={'paths':[d['path'] for d in docs]}))
    return store


def corrupt(raw):
    """让一份结构合法的模型稿带上结构错误（owner 冲突 + 来源片段伪造）。"""
    raw=__import__('copy').deepcopy(raw)
    raw['fields'][0]['source_type']='statistics'
    raw['fields'][0]['sources'][0]['text']='不存在的原文片段'
    return raw


def test_structural_errors_flow_through_rounds_until_round_three_passes(tmp_path):
    """结构错误不是硬失败：r1/r2 带错继续流转，错误清单喂给下一轮；r3 修正后终审成候选。"""
    store=task_store(tmp_path);requests=[]
    async def analyst(role,payload):
        requests.append(payload)
        good=await semantic_analyst(role,payload)
        return corrupt(good) if len(requests)<3 else good
    result=asyncio.run(run_template(Dependencies(store,analyst),'repair'))
    assert result.phase=='awaiting_template_confirmation',result.metadata.get('template_error')
    assert [p['semantic_round']['round'] for p in requests]==[1,2,3]
    # r2 输入带 r1 的结构错误；r3 输入带 r2 错误与前两轮 history。
    codes={e['code'] for e in requests[1]['semantic_round']['structural_errors']}
    assert {'statistics_owned_by_data','source_text_mismatch'}<=codes
    assert {h['round'] for h in requests[2]['semantic_round']['history']}=={1,2}
    batch=next(iter(result.metadata['template_batches'].values()))
    assert batch['final_round']==3 and batch['terminal']=='candidate_ready'
    assert all(r['elapsed_ms']>=0 and r['model_elapsed_ms']>=0 and r['request_ref'] for r in batch['rounds'])
    assert snapshot(result)['rounds'][-1]['status']=='passed'


def test_three_invalid_structures_keep_human_editor_and_correction_goes_to_confirmation(tmp_path,monkeypatch):
    import app.main as main
    store=task_store(tmp_path);calls=[];good_candidate=None
    async def analyst(role,payload):
        nonlocal good_candidate
        calls.append(payload);good_candidate=await semantic_analyst(role,payload)
        return corrupt(good_candidate)
    deps=Dependencies(store,analyst)
    failed=asyncio.run(run_template(deps,'repair'))
    # 三轮响应结构全部非法 → 可审阅结构存在 → 人工异常研判。
    assert failed.phase=='template_manual_review' and len(calls)==3
    assert [p['semantic_round']['round'] for p in calls]==[1,2,3]
    asyncio.run(run_template(deps,'repair'))
    assert len(calls)==3
    monkeypatch.setattr(main,'store',store);monkeypatch.setattr(main,'deps',deps)
    with TestClient(main.app) as client:
        view=client.get('/api/templates/repair/exceptions').json()
        batch=view['batches'][0]
        assert len(view['sources'])==3
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
        # 人工修正确认后直接进人工确认页，不再补发模型研判轮。
        assert ready.phase=='awaiting_template_confirmation' and len(calls)==3
        assert ready.metadata['template_validation_ref'] and not ready.metadata.get('confirmed_template_ref')
        assert client.post(url,json=body).status_code==409


def test_transport_failure_resumes_from_persisted_rounds_without_losing_r1(tmp_path):
    """验收 4：r1 已完成后 r2 传输失败，恢复时从 r2 续跑，不重发 r1。"""
    store=task_store(tmp_path)
    calls=[]
    async def fails_after_r1(role,payload):
        calls.append(payload)
        good=await semantic_analyst(role,payload)
        if payload['semantic_round']['round']==2:
            raise TimeoutError('test network timeout')
        return good
    failed=asyncio.run(run_template(Dependencies(store,fails_after_r1),'repair'))
    assert failed.phase=='template_review_failed'
    batch=next(iter(failed.metadata['template_batches'].values()))
    assert batch['rounds'][0]['status']=='passed' and batch['rounds'][-1]['status']=='transport_error'
    second=[]
    async def resume_analyst(role,payload):
        second.append(payload)
        return await semantic_analyst(role,payload)
    ready=asyncio.run(run_template(Dependencies(store,resume_analyst),'repair'))
    assert ready.phase=='awaiting_template_confirmation',ready.metadata.get('template_error')
    # 恢复后只补发 r2（携带 r1 稿与意见），r1 不重发。
    assert [p['semantic_round']['round'] for p in second]==[2]
    assert second[0]['semantic_round']['prior_round']['template']['blocks']
    batch=next(iter(ready.metadata['template_batches'].values()))
    assert batch['final_round']==2 and batch['rounds'][-1]['number']==2 and batch['rounds'][-1]['status']=='passed'


def test_transport_failure_before_r1_still_restarts_cleanly(tmp_path):
    store=task_store(tmp_path)
    async def timeout(role,payload):raise TimeoutError('test network timeout')
    failed=asyncio.run(run_template(Dependencies(store,timeout),'repair'))
    assert failed.phase=='template_review_failed'
    batch=next(iter(failed.metadata['template_batches'].values()))
    assert batch['rounds'][0]['status']=='transport_error'
    ready=asyncio.run(run_template(Dependencies(store,semantic_analyst),'repair'))
    assert ready.phase=='awaiting_template_confirmation',ready.metadata.get('template_error')
    batch=next(iter(ready.metadata['template_batches'].values()))
    assert [r['number'] for r in batch['rounds']]==[1,2]
    assert batch['rounds'][-1]['status']=='passed'


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
    state.metadata['template_batches']={str(i):{'targets':[i],'rounds':[
        {'number':1,'stage':'first','started_at':'2026-11-07T00:00:00+00:00','status':'running'}]} for i in range(2)}
    result=snapshot(state,'2026-11-07T00:00:01+00:00')
    assert result['processing_ms']==1_000 and sum(r['elapsed_ms'] for r in result['rounds'])==2_000
