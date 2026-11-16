"""模板级「事件去重 / 自动分类」开关：配置 → 界面提交 → 裁剪 → 真不调用。

四层各有一个断言落点，缺一层就会出现"改了配置没生效"的假开关：

1. `rules.features` 随候选/已确认版本保存，缺省全开，且只提交口径时不被抹回默认；
2. 建报告任务时 `template_rules` 把开关带到任务上；
3. 给模型的工具清单被裁剪（不是只在执行层拒绝——模型看得到就会反复重试）；
4. 被关掉的步骤在 `execute_tool` 上真的 0 次调用，且流量仍能跑到人工数据审核。

全部走真实代码路径（真实 `Store`、真实工具子进程、真实报告图），只替换模型适配器：
否则验不到"关掉之后真的没跑"。
"""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

import app.main as main
import app.workflow as workflow
from app.schemas import TaskState
from app.storage import Store
from app.structured_template import load_confirmed_template
from app.workflow import Dependencies, run_template
from test_api_flow import analysis_adapter, sample_xlsx
from test_structured_template import pair, semantic_analyst

RULES = {'event_threshold': .65, 'first_warning_scope': 'negative_or_warning',
         'ranking': 'negative_warning_member_count'}
DEDUP_TOOLS = {'group_events'}
CLASSIFICATION_TOOLS = {'classify_records', 'cluster_event_themes', 'discover_topics'}


def _store_and_app(tmp_path, monkeypatch, adapter):
    store = Store(tmp_path / 'store')
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    monkeypatch.setattr(main, 'store', store)
    monkeypatch.setattr(main, 'deps', Dependencies(store, adapter))
    monkeypatch.setattr(main, 'UPLOADS', uploads)
    return store, uploads


def _template_task(store, tmp_path):
    docs = pair(tmp_path)
    store.put_task(TaskState(id='template', kind='template', phase='queued',
                             metadata={'paths': [d['path'] for d in docs]}))
    task = asyncio.run(run_template(Dependencies(store, semantic_analyst), 'template'))
    assert task.phase == 'awaiting_template_confirmation', task.metadata.get('template_error')
    return task


def _upload(client):
    upload = client.post('/api/files', files={'file': (
        'sample.xlsx', sample_xlsx(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert upload.status_code == 200
    return upload.json()['id']


def _confirmed_template_with(tmp_path, monkeypatch, features):
    """确认一个带指定开关的模板版本，返回 (store, template_ref)。"""
    store, _ = _store_and_app(tmp_path, monkeypatch, analysis_adapter)
    task = _template_task(store, tmp_path)
    with TestClient(main.app) as client:
        definition = client.get('/api/templates/template/definition').json()
        response = client.post('/api/templates/template/confirm', json={
            'expected_revision': task.revision, 'candidate_ref': task.metadata['structured_template_ref'],
            'reason': '验收用模板确认', 'rules': {**RULES, 'features': features}})
        assert response.status_code == 200, response.text
        assert definition['revision'] == task.revision
    return store, response.json()['metadata']['confirmed_template_ref']


def _run_report(tmp_path, monkeypatch, features, seen=None, calls=None):
    """建报告任务并跑数据处理；返回任务状态、给模型的工具清单、execute_tool 的调用记录。"""
    store, template_ref = _confirmed_template_with(tmp_path, monkeypatch, features)

    async def adapter(role, payload):
        if role == 'data_processor':
            if seen is not None:
                seen.append([tool['name'] for tool in payload['tools']])
            raise ValueError('probe_stop')          # 只取清单，随后走公开保底链路
        return await analysis_adapter(role, payload)

    real_execute = workflow.execute_tool

    async def recording_execute(call, context):
        if calls is not None:
            calls.append(call.tool_name)
        return await real_execute(call, context)

    monkeypatch.setattr(main, 'deps', Dependencies(store, adapter))
    monkeypatch.setattr(workflow, 'execute_tool', recording_execute)
    with TestClient(main.app) as client:
        file_id = _upload(client)
        created = client.post('/api/report-tasks', json={
            'file_ids': [file_id], 'template_ref': template_ref, 'report_month': '2026-10',
            'sheet_index': 3, 'mode': 'dynamic'})
        assert created.status_code == 200, created.text
        task_id = created.json()['id']
        state = client.get('/api/tasks/' + task_id).json()
        events = client.get(f'/api/tasks/{task_id}/events?limit=200').json()
    return state, events


def test_template_features_persist_and_cannot_be_rewritten_after_confirm(tmp_path, monkeypatch):
    store, _ = _store_and_app(tmp_path, monkeypatch, analysis_adapter)
    task = _template_task(store, tmp_path)
    off = {'dedup': False, 'classification': False, 'first_warning': False, 'top10': False}
    with TestClient(main.app) as client:
        definition = client.get('/api/templates/template/definition').json()
        # 未写过这两个键 = 默认全开（老模板行为不变）
        assert 'features' not in (definition['definition'].get('rules') or {})
        patched = client.put('/api/templates/template/definition', json={
            'expected_revision': definition['revision'], 'fields': {}, 'rules': {**RULES, 'features': off}})
        assert patched.status_code == 200, patched.text
        assert patched.json()['definition']['rules']['features'] == off
        # 只提交口径（不带 features）不能把已保存的开关抹回默认
        only_rules = client.put('/api/templates/template/definition', json={
            'expected_revision': patched.json()['revision'], 'fields': {}, 'rules': dict(RULES)})
        assert only_rules.json()['definition']['rules']['features'] == off
        # 确认后随 template_version 一起保存
        confirmed = client.post('/api/templates/template/confirm', json={
            'expected_revision': only_rules.json()['revision'],
            'candidate_ref': only_rules.json()['artifact_ref'],
            'reason': '验收用模板确认', 'rules': dict(RULES)})
        assert confirmed.status_code == 200, confirmed.text
        ref = confirmed.json()['metadata']['confirmed_template_ref']
        assert load_confirmed_template(store, ref)['rules']['features'] == off
        # 已确认版本不允许再改（沿用既有语义，不新增错误码）
        assert client.put('/api/templates/template/definition', json={
            'expected_revision': confirmed.json()['revision'], 'fields': {}}).status_code == 409


def test_default_template_keeps_dedup_and_classification_tools(tmp_path, monkeypatch):
    seen, calls = [], []
    state, events = _run_report(tmp_path, monkeypatch, {'dedup': True, 'classification': True}, seen, calls)
    assert seen, '规划器没有被调用'
    assert DEDUP_TOOLS <= set(seen[0])
    assert CLASSIFICATION_TOOLS <= set(seen[0])
    assert DEDUP_TOOLS <= set(state['metadata']['available_tools'])
    assert DEDUP_TOOLS <= set(calls) and CLASSIFICATION_TOOLS & set(calls)
    assert DEDUP_TOOLS <= set(state['result_refs'])
    feature_events = [e for e in events if e['type'] == 'processing_features']
    assert feature_events and feature_events[0]['dedup'] is True and feature_events[0]['classification'] is True


def test_both_switches_off_prune_tools_and_skip_steps(tmp_path, monkeypatch):
    seen, calls = [], []
    state, events = _run_report(tmp_path, monkeypatch, {'dedup': False, 'classification': False}, seen, calls)
    assert seen, '规划器没有被调用'
    assert not DEDUP_TOOLS & set(seen[0])
    assert not CLASSIFICATION_TOOLS & set(seen[0])
    assert not DEDUP_TOOLS & set(state['metadata']['available_tools'])
    assert not DEDUP_TOOLS & set(calls) and not CLASSIFICATION_TOOLS & set(calls)
    assert 'group_events' not in state['result_refs'] and 'cluster_event_themes' not in state['result_refs']
    feature_events = [e for e in events if e['type'] == 'processing_features']
    assert feature_events and feature_events[0]['dedup'] is False and feature_events[0]['classification'] is False
    # 缺两步不阻断流量：仍停在人工数据审核，而不是 failed
    assert state['phase'] == 'awaiting_review', state.get('metadata', {}).get('failure_message')


def test_classification_only_off_keeps_dedup(tmp_path, monkeypatch):
    seen, calls = [], []
    state, _events = _run_report(tmp_path, monkeypatch, {'dedup': True, 'classification': False}, seen, calls)
    assert DEDUP_TOOLS <= set(seen[0])
    assert not CLASSIFICATION_TOOLS & set(seen[0])
    assert DEDUP_TOOLS <= set(calls)
    assert not CLASSIFICATION_TOOLS & set(calls)
    assert 'group_events' in state['result_refs']
    assert 'cluster_event_themes' not in state['result_refs']
