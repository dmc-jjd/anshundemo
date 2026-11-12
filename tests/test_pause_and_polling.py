from fastapi.testclient import TestClient

import app.main as main
from app.schemas import TaskState
from app.storage import Store


def test_templates_skip_missing_artifact_and_tasks_return_summary(tmp_path, monkeypatch):
    store = Store(tmp_path / 'data')
    ref = store.put_artifact('template-task', 'template_version', {
        'writer_schema': {'fields': []}, 'source_reports': ['a.docx', 'b.docx']
    })
    with store.connect() as connection:
        connection.execute('UPDATE artifacts SET path=? WHERE id=?', (str(tmp_path / 'missing.json'), ref))
    (store.files / f'{ref}.json').unlink()
    store.put_task(TaskState(
        id='template-task', kind='template', phase='template_confirmed',
        metadata={'confirmed_template_ref': ref},
    ))
    store.put_task(TaskState(
        id='large-report', kind='report', phase='awaiting_review',
        metadata={'simulation': True, 'large_snapshot': 'x' * 100_000},
    ))
    monkeypatch.setattr(main, 'store', store)

    with TestClient(main.app) as client:
        response = client.get('/api/templates')
        assert response.status_code == 200
        assert [item['id'] for item in response.json()] == ['anshun-monthly-colored']

        response = client.get('/api/tasks')
        assert response.status_code == 200
        task = next(item for item in response.json() if item['id'] == 'large-report')
        assert task['metadata'] == {'simulation': True}
        assert 'large_snapshot' not in response.text
        assert 'result_refs' not in task and 'review_items' not in task


def test_pause_is_idempotent_rejects_terminal_and_resumes_human_wait(tmp_path, monkeypatch):
    store = Store(tmp_path / 'data')
    store.put_task(TaskState(id='waiting', kind='report', phase='awaiting_review'))
    store.put_task(TaskState(id='done', kind='report', phase='approved'))
    monkeypatch.setattr(main, 'store', store)

    with TestClient(main.app) as client:
        paused = client.post('/api/tasks/waiting/pause')
        assert paused.status_code == 200
        assert paused.json()['phase'] == 'paused'
        assert paused.json()['metadata']['paused_from_phase'] == 'awaiting_review'
        assert client.post('/api/tasks/waiting/pause').json()['revision'] == paused.json()['revision']
        assert client.post('/api/tasks/done/pause').status_code == 409

        resumed = client.post('/api/tasks/waiting/resume')
        assert resumed.status_code == 200
        assert resumed.json()['phase'] == 'awaiting_review'
        assert 'paused_from_phase' not in resumed.json()['metadata']
        assert 'paused_at' not in resumed.json()['metadata']


def test_background_write_cannot_clear_pause_and_timing_excludes_pause(tmp_path, monkeypatch):
    import core.timing as timing

    clock = ['2026-11-09T00:00:00+00:00']
    monkeypatch.setattr(timing, 'stamp', lambda: clock[0])
    store = Store(tmp_path / 'data')
    state = TaskState(id='clock', kind='report', phase='processing')
    store.put_task(state)

    clock[0] = '2026-11-09T00:00:10+00:00'
    state = store.get_task('clock')
    state.phase = 'paused'
    state.metadata.update(paused_from_phase='processing', paused_at=timing.stamp())
    store.put_task(state, state.revision, allow_resume=True)
    frozen = timing.snapshot(store.get_task('clock'), '2026-11-09T00:01:00+00:00')
    assert frozen['total_ms'] == 10_000
    assert frozen['processing_ms'] == 10_000
    assert frozen['paused_ms'] == 0
    assert frozen['current_bucket'] == 'paused_ms'

    state = store.get_task('clock')
    state.phase = 'processing'
    store.put_task(state, state.revision)
    assert store.get_task('clock').phase == 'paused'

    clock[0] = '2026-11-09T00:00:50+00:00'
    state = store.get_task('clock')
    state.phase = state.metadata.pop('paused_from_phase')
    state.metadata.pop('paused_at')
    store.put_task(state, state.revision, allow_resume=True)
    resumed = timing.snapshot(store.get_task('clock'), '2026-11-09T00:01:10+00:00')
    assert resumed['total_ms'] == 30_000
    assert resumed['processing_ms'] == 30_000
    assert resumed['paused_ms'] == 40_000


def test_paused_task_does_not_start_another_model_call(tmp_path):
    import asyncio
    import pytest
    from app.model_client import TaskPaused, invoke_agent
    from app.schemas import ToolDecision
    from app.tool_executor import RunContext

    store = Store(tmp_path / 'data')
    store.put_task(TaskState(id='model', kind='report', phase='paused'))
    calls = 0

    async def adapter(role, payload):
        nonlocal calls
        calls += 1
        return {'action': 'finish_processing', 'reason': 'should not run'}

    with pytest.raises(TaskPaused):
        asyncio.run(invoke_agent('data_processor', {}, ToolDecision, RunContext(store, 'model', model_adapter=adapter)))
    assert calls == 0


def test_report_graph_returns_normally_when_paused(tmp_path, monkeypatch):
    import asyncio
    import app.workflow as workflow
    from app.model_client import TaskPaused

    store = Store(tmp_path / 'data')
    store.put_task(TaskState(id='graph', kind='report', phase='paused'))

    class PausedGraph:
        async def ainvoke(self, value, config=None):
            raise TaskPaused()

    monkeypatch.setattr(workflow, 'build_report_graph', lambda dependencies: PausedGraph())
    result = asyncio.run(workflow.run_report_graph(workflow.Dependencies(store), 'graph'))
    assert result.phase == 'paused'


def test_get_artifact_uses_current_store_when_recorded_path_is_stale(tmp_path):
    store = Store(tmp_path / 'data')
    payload = {'content': 'still available'}
    ref = store.put_artifact('report', 'facts', payload)
    with store.connect() as connection:
        connection.execute(
            'UPDATE artifacts SET path=? WHERE id=?',
            (str(tmp_path / 'old-project' / 'data' / 'artifacts' / f'{ref}.json'), ref),
        )

    assert store.get_artifact(ref) == payload


def test_chart_definitions_use_current_upload_when_layout_path_is_stale(tmp_path, monkeypatch):
    import zipfile
    import app.chart_spec as chart_spec

    data = tmp_path / 'data'
    uploads = data / 'uploads'
    uploads.mkdir(parents=True)
    current = uploads / 'layout.docx'
    with zipfile.ZipFile(current, 'w') as document:
        document.writestr(
            'word/document.xml',
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:drawing/></w:body></w:document>',
        )
    # WP-S8-L2：DATA 的家已随 chart_spec 进 core，patch 必须打在 core.chart_spec 上。
    import core.chart_spec as chart_spec_impl
    monkeypatch.setattr(chart_spec_impl, 'DATA', data, raising=False)
    stale = tmp_path / 'old-project' / 'data' / 'uploads' / current.name

    definitions = chart_spec.definitions({'layout_source': str(stale)})
    assert [item['id'] for item in definitions] == ['sentiment']


def test_structured_writing_uses_current_upload_when_layout_path_is_stale(tmp_path, monkeypatch):
    import asyncio
    from pathlib import Path
    import app.structured_writer as writer
    import app.chart_spec as chart_spec
    from app.workflow import Dependencies
    from test_frozen_writer import fixture

    store, template = fixture(tmp_path)
    data = tmp_path / 'data'
    uploads = data / 'uploads'
    uploads.mkdir(parents=True)
    current = uploads / 'layout.docx'
    current.write_bytes(Path(template['layout_source']).read_bytes())
    stale = tmp_path / 'old-project' / 'data' / 'uploads' / current.name
    template['layout_source'] = str(stale)
    state = store.get_task('r')
    state.template_ref = store.put_artifact('r', 'template', template)
    store.put_task(state, state.revision)
    monkeypatch.setattr(writer, 'DATA', data, raising=False)
    # WP-S8-L2：DATA 的家已随 chart_spec 进 core，patch 必须打在 core.chart_spec 上（打壳=改副本，静默失效）。
    import core.chart_spec as chart_spec_impl
    monkeypatch.setattr(chart_spec_impl, 'DATA', data)

    async def model(role, payload):
        assert role == 'writer'
        return {'values': {
            key: {'value': '测试文字', 'source_refs': [payload['evidence'][0]['ref']]}
            for key in payload['remaining_fields']
        }}

    state = asyncio.run(writer.write_structured_preview(Dependencies(store, model), 'r'))
    draft = store.get_artifact(state.draft_ref)
    assert state.metadata['structured_writer_version'] == 2
    assert draft['slot_values']['w1']['value'] == '测试文字'
