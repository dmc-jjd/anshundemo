"""S6 出口的 API 形状判据（C3/C4/C5）——全部用 `ast` / `app.openapi()` 机械判定，不靠肉眼。

- C5：52 个路由装饰器**仍在 `app/main.py`**，且 `(method, path)` 集合逐项等于 S6 前的字面表；
- C3：每个路由函数体 **≤20 行**；
- C4：`app/main.py` **≤620 行**；
- 下沉层：`app/api_views/*.py` 不碰 web 框架、不抛 HTTP 异常、不新建存储连接、不导入 main。
- C1 的数值判据在 `scripts/gate_openapi.py`（基线文件是唯一判据，此处只钉路径集合与运算数）。

**49 / 52 勘误**（`scripts/gate_openapi.py:8-12` 已记录）：52 是「方法+路径」运算数，唯一路径是 49
（3 个路径同时挂了 GET 与 POST）。故下面 `EXPECTED_PATHS` 49 条、`EXPECTED_ROUTES` 52 条。
"""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MAIN = REPO / 'app' / 'main.py'
API_VIEWS = REPO / 'app' / 'api_views'
HTTP_METHODS = ('get', 'post', 'put', 'patch', 'delete')

EXPECTED_ROUTES = [
    ('GET', '/'),
    ('GET', '/api/artifacts/{artifact_id}'),
    ('GET', '/api/artifacts/{artifact_id}/chart'),
    ('GET', '/api/artifacts/{artifact_id}/download'),
    ('GET', '/api/report-parameter-suggestions'),
    ('GET', '/api/status'),
    ('GET', '/api/tasks'),
    ('GET', '/api/tasks/{task_id}'),
    ('GET', '/api/tasks/{task_id}/charts/{name}'),
    ('GET', '/api/tasks/{task_id}/draft-view'),
    ('GET', '/api/tasks/{task_id}/events'),
    ('GET', '/api/tasks/{task_id}/historical-research'),
    ('GET', '/api/tasks/{task_id}/logs'),
    ('GET', '/api/tasks/{task_id}/reference-comparison'),
    ('GET', '/api/tasks/{task_id}/review-data'),
    ('GET', '/api/tasks/{task_id}/timing'),
    ('GET', '/api/tasks/{task_id}/usage'),
    ('GET', '/api/tasks/{task_id}/writing-review'),
    ('GET', '/api/template-docx'),
    ('GET', '/api/template-manifest'),
    ('GET', '/api/templates'),
    ('GET', '/api/templates/{task_id}/charts/{name}/source'),
    ('GET', '/api/templates/{task_id}/definition'),
    ('GET', '/api/templates/{task_id}/exceptions'),
    ('GET', '/api/templates/{task_id}/sources'),
    ('GET', '/api/token-pricing'),
    ('GET', '/api/workflow-graphs'),
    ('POST', '/api/files'),
    ('POST', '/api/report-tasks'),
    ('POST', '/api/tasks/{task_id}/approve'),
    ('POST', '/api/tasks/{task_id}/cancel'),
    ('POST', '/api/tasks/{task_id}/chart-settings'),
    ('POST', '/api/tasks/{task_id}/confirm-data'),
    ('POST', '/api/tasks/{task_id}/confirm-facts'),
    ('POST', '/api/tasks/{task_id}/decisions'),
    ('POST', '/api/tasks/{task_id}/event-settings'),
    ('POST', '/api/tasks/{task_id}/exports'),
    ('POST', '/api/tasks/{task_id}/pause'),
    ('POST', '/api/tasks/{task_id}/preview-draft'),
    ('POST', '/api/tasks/{task_id}/report-parameters'),
    ('POST', '/api/tasks/{task_id}/resume'),
    ('POST', '/api/tasks/{task_id}/review-draft'),
    ('POST', '/api/tasks/{task_id}/slot-values'),
    ('POST', '/api/tasks/{task_id}/writing-review/resolve'),
    ('POST', '/api/tasks/{task_id}/writing-review/{issue_id}/edit'),
    ('POST', '/api/template-tasks'),
    ('POST', '/api/templates/{task_id}/chart-version'),
    ('POST', '/api/templates/{task_id}/confirm'),
    ('POST', '/api/templates/{task_id}/exceptions/{batch_id}/resolve'),
    ('PUT', '/api/tasks/{task_id}/review-draft'),
    ('PUT', '/api/templates/{task_id}/definition'),
    ('PUT', '/api/token-pricing'),
]

EXPECTED_PATHS = [
    '/',
    '/api/artifacts/{artifact_id}',
    '/api/artifacts/{artifact_id}/chart',
    '/api/artifacts/{artifact_id}/download',
    '/api/files',
    '/api/report-parameter-suggestions',
    '/api/report-tasks',
    '/api/status',
    '/api/tasks',
    '/api/tasks/{task_id}',
    '/api/tasks/{task_id}/approve',
    '/api/tasks/{task_id}/cancel',
    '/api/tasks/{task_id}/chart-settings',
    '/api/tasks/{task_id}/charts/{name}',
    '/api/tasks/{task_id}/confirm-data',
    '/api/tasks/{task_id}/confirm-facts',
    '/api/tasks/{task_id}/decisions',
    '/api/tasks/{task_id}/draft-view',
    '/api/tasks/{task_id}/event-settings',
    '/api/tasks/{task_id}/events',
    '/api/tasks/{task_id}/exports',
    '/api/tasks/{task_id}/historical-research',
    '/api/tasks/{task_id}/logs',
    '/api/tasks/{task_id}/pause',
    '/api/tasks/{task_id}/preview-draft',
    '/api/tasks/{task_id}/reference-comparison',
    '/api/tasks/{task_id}/report-parameters',
    '/api/tasks/{task_id}/resume',
    '/api/tasks/{task_id}/review-data',
    '/api/tasks/{task_id}/review-draft',
    '/api/tasks/{task_id}/slot-values',
    '/api/tasks/{task_id}/timing',
    '/api/tasks/{task_id}/usage',
    '/api/tasks/{task_id}/writing-review',
    '/api/tasks/{task_id}/writing-review/resolve',
    '/api/tasks/{task_id}/writing-review/{issue_id}/edit',
    '/api/template-docx',
    '/api/template-manifest',
    '/api/template-tasks',
    '/api/templates',
    '/api/templates/{task_id}/chart-version',
    '/api/templates/{task_id}/charts/{name}/source',
    '/api/templates/{task_id}/confirm',
    '/api/templates/{task_id}/definition',
    '/api/templates/{task_id}/exceptions',
    '/api/templates/{task_id}/exceptions/{batch_id}/resolve',
    '/api/templates/{task_id}/sources',
    '/api/token-pricing',
    '/api/workflow-graphs',
]

MAX_ROUTE_BODY_LINES = 20
MAX_MAIN_LINES = 620


def _route_decorator(node):
    """`@app.<method>('<path>', …)` -> (METHOD, path)；非路由装饰器 -> None。"""
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            continue
        target, method = decorator.func.value, decorator.func.attr
        if not isinstance(target, ast.Name) or target.id != 'app' or method not in HTTP_METHODS:
            continue
        if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
            continue
        return method.upper(), decorator.args[0].value
    return None


def route_functions():
    """`app/main.py` 里带路由装饰器的函数：[(METHOD, path, name, 函数体行数)]。"""
    tree = ast.parse(MAIN.read_text(encoding='utf-8'))
    found = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        route = _route_decorator(node)
        if route:
            found.append((route[0], route[1], node.name, node.end_lineno - node.lineno + 1))
    return found


def _api_view_trees():
    return [(path, ast.parse(path.read_text(encoding='utf-8'))) for path in sorted(API_VIEWS.glob('*.py'))]


def test_all_52_decorators_still_in_main():
    routes = route_functions()
    assert len(routes) == 52, f'路由装饰器数应为 52，实测 {len(routes)}'
    assert {(method, path) for method, path, _name, _len in routes} == set(EXPECTED_ROUTES)
    assert len(set(EXPECTED_ROUTES)) == 52 and len(set(EXPECTED_PATHS)) == 49


def test_every_route_is_thin():
    offenders = [(name, lines) for _m, _p, name, lines in route_functions() if lines > MAX_ROUTE_BODY_LINES]
    assert offenders == [], f'以下路由函数体超过 {MAX_ROUTE_BODY_LINES} 行：{offenders}'


def test_main_has_no_route_body_over_20():
    over = [(f'{method} {path} -> {name}', lines)
           for method, path, name, lines in route_functions() if lines > MAX_ROUTE_BODY_LINES]
    details = '\n'.join(f'  {name}: {lines} 行' for name, lines in over)
    assert over == [], f'路由函数体超长（上限 {MAX_ROUTE_BODY_LINES}）：\n{details}'


def test_api_views_are_http_free():
    offenders = []
    for path, tree in _api_view_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders.extend(f'{path.name}:{node.lineno} import {alias.name}'
                                 for alias in node.names if alias.name.split('.')[0] in ('fastapi', 'starlette'))
            elif isinstance(node, ast.ImportFrom) and (node.module or '').split('.')[0] in ('fastapi', 'starlette'):
                offenders.append(f'{path.name}:{node.lineno} from {node.module}')
            elif isinstance(node, ast.Name) and node.id in ('FastAPI', 'HTTPException'):
                offenders.append(f'{path.name}:{node.lineno} 使用 {node.id}')
            elif isinstance(node, ast.Attribute) and node.attr == 'mount':
                offenders.append(f'{path.name}:{node.lineno} 调用 .mount(...)')
    assert offenders == [], 'api_views 必须框架无关：' + ', '.join(offenders)


def test_api_views_do_not_open_store():
    def binds_main(module):
        return module == 'app' or module == 'app.main' or module.startswith('app.main.')

    offenders = []
    for path, tree in _api_view_trees():
        if 'Store(' in path.read_text(encoding='utf-8'):
            offenders.append(f'{path.name} 出现 Store( 字面量')
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'Store':
                offenders.append(f'{path.name}:{node.lineno} 调用 Store(...)')
            elif isinstance(node, ast.ImportFrom) and binds_main(node.module or ''):
                offenders.append(f'{path.name}:{node.lineno} 从 {node.module} 导入（会绑死注入面）')
            elif isinstance(node, ast.Import):
                offenders.extend(f'{path.name}:{node.lineno} import {alias.name}'
                                 for alias in node.names if binds_main(alias.name))
    assert offenders == [], '下沉层不许新建连接、不许导入 main：' + ', '.join(offenders)


def test_openapi_path_set_matches_expected():
    import app.main as main

    spec = main.app.openapi()
    assert set(spec['paths']) == set(EXPECTED_PATHS)
    operations = {(method.upper(), path) for path, methods in spec['paths'].items()
                  for method, operation in methods.items() if isinstance(operation, dict)}
    assert operations == set(EXPECTED_ROUTES)
    assert len(operations) == 52


def test_main_line_count_within_budget():
    """C4：`main.py` ≤620 行（本判据不在 §3 的 6 条列表里，但它是 C4 的机械判据，故补一条）。"""
    lines = len(MAIN.read_text(encoding='utf-8').splitlines())
    assert lines <= MAX_MAIN_LINES, f'app/main.py 现有 {lines} 行，超过预算 {MAX_MAIN_LINES}'


# ---------------------------------------------------------------------------
# `resume` 下沉（WP-S6-E）的分支级行为断言：RISK-11 要求「只搬阶段判定」，
# `preview_draft` 的直接调用与 `background_tasks.add_task(...)` 必须仍留在 main.py，
# 且「该启哪张图」的判定结果要经 main.py 真的落到对应图函数上（含注入面）。
# ---------------------------------------------------------------------------

class _Recorder:
    def __init__(self): self.calls = []
    def __call__(self, *args, **kwargs): self.calls.append((args, kwargs))


def _resume_env(tmp_path, monkeypatch, **patch):
    from app.storage import Store
    import app.main as main

    store = Store(tmp_path / 'store')
    monkeypatch.setattr(main, 'store', store)
    for name, value in patch.items():
        monkeypatch.setattr(main, name, value)
    return main, store


def test_resume_keeps_direct_preview_draft_call(tmp_path, monkeypatch):
    """`facts_frozen` 的报告任务：resume 仍**直接调用** `preview_draft`（不是重发 HTTP、不是复制逻辑）。"""
    from app.schemas import TaskState
    from fastapi.testclient import TestClient

    drafted = []

    async def fake_draft(task_id, review_only=False):
        drafted.append((task_id, review_only))

    main, store = _resume_env(tmp_path, monkeypatch, generate_draft=fake_draft)
    fact = store.put_artifact('r', 'facts', {'metrics': {}})
    store.put_task(TaskState(id='r', kind='report', phase='facts_frozen', fact_ref=fact))

    with TestClient(main.app) as client:
        response = client.post('/api/tasks/r/resume')

    assert response.status_code == 200, response.text
    assert response.json()['phase'] == 'writing'
    assert drafted == [('r', False)]


def test_resume_rejects_template_analysis_in_progress(tmp_path, monkeypatch):
    from app.schemas import TaskState
    from fastapi.testclient import TestClient

    main, store = _resume_env(tmp_path, monkeypatch)
    store.put_task(TaskState(id='t', kind='template', phase='processing'))

    with TestClient(main.app) as client:
        response = client.post('/api/tasks/t/resume')

    assert response.status_code == 409
    assert response.json()['detail'] == 'template_analysis_in_progress'


def test_resume_paused_template_restarts_template_graph(tmp_path, monkeypatch):
    from app.schemas import TaskState
    from fastapi.testclient import TestClient

    recorder = _Recorder()
    main, store = _resume_env(tmp_path, monkeypatch, run_template_graph=recorder)
    store.put_task(TaskState(id='t', kind='template', phase='paused',
                             metadata={'paused_from_phase': 'processing'}))

    with TestClient(main.app) as client:
        response = client.post('/api/tasks/t/resume')

    assert response.status_code == 200, response.text
    assert response.json()['phase'] == 'queued'
    assert len(recorder.calls) == 1 and recorder.calls[0][0][1] == 't'


def test_resume_requeues_report_graph_for_stalled_analysis(tmp_path, monkeypatch):
    from app.schemas import TaskState
    from fastapi.testclient import TestClient

    recorder = _Recorder()
    main, store = _resume_env(tmp_path, monkeypatch, run_report_graph=recorder)
    store.put_task(TaskState(id='r', kind='report', phase='analysis_pending'))

    with TestClient(main.app) as client:
        response = client.post('/api/tasks/r/resume')

    assert response.status_code == 200, response.text
    assert response.json()['phase'] == 'queued'
    assert len(recorder.calls) == 1 and recorder.calls[0][0][1] == 'r'
