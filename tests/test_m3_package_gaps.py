# -*- coding: utf-8 -*-
"""M3：按包缺口（editor / reference / hotspot / template_dir / 多 worker / 图）的机械判据。

每条对应 M2 报告里「仍落默认包」的一处，断言口径统一是**交叉**：B 的读不到 A 的、
A 的读不到 B 的。只测「B 能跑通」抓不住静默串包。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import app as _app  # noqa: F401  （宿主 import 期配置包上下文/数据基根）
from app.packages_api import root_for, store_for
from core import paths
from core.package_store import PackageStores
from core.schemas import TaskState
from core.storage import Store

A, B = 'anshun_monthly', 'demo_b'
SAMPLE = '安顺市平坝区社区卫生服务中心获评景区片区示范点，游客投诉明显下降'


def _task(stores: PackageStores, task_id: str, package: str) -> TaskState:
    state = TaskState(id=task_id, package=package, kind='report', phase='processing')
    stores.put_task(state)
    return state


# --------------------------------------------------------------------------- #
# 缺口 4：多 worker —— 另一个进程刚建的 B 任务，本进程不能 404
# --------------------------------------------------------------------------- #
def test_task_created_by_another_worker_is_visible_after_rescan(tmp_path: Path) -> None:
    """本进程只扫过一次之后，另一份 PackageStores（=另一个 worker）在建 B 任务。"""
    mine = PackageStores(tmp_path)
    _task(mine, 'task-a', A)
    assert mine.get_task('task-a').package == A          # 首次扫描完成（_scan_done=True）

    other_worker = PackageStores(tmp_path)               # 独立进程视角：共享同一个数据基根
    _task(other_worker, 'task-b', B)

    assert mine.package_of('task-b') == B                # miss 时必须重扫，不能回落默认包
    assert mine.get_task('task-b').package == B          # 拿得到，不 404


def test_unknown_task_still_raises_keyerror(tmp_path: Path) -> None:
    """重扫只解决「新任务可见」，不许把「真不存在」伪装成默认包任务。"""
    mine = PackageStores(tmp_path)
    _task(mine, 'task-a', A)
    with pytest.raises(KeyError):
        mine.get_task('no-such-task')


# --------------------------------------------------------------------------- #
# 缺口 1：editor_api 的 docx 列表按任务所属包
# --------------------------------------------------------------------------- #
def test_editor_docx_refs_use_task_package(tmp_path: Path) -> None:
    from app.editor_api import _docx_refs

    stores = PackageStores(tmp_path)
    _task(stores, 'task-a', A)
    _task(stores, 'task-b', B)
    ref_b = stores.put_artifact('task-b', 'final_docx', {'bytes': 4})
    ref_a = stores.put_artifact('task-a', 'final_docx', {'bytes': 4})
    (stores.files_for('task-b') / f'{ref_b}.docx').write_bytes(b'PK\x03\x04b')
    (stores.files_for('task-a') / f'{ref_a}.docx').write_bytes(b'PK\x03\x04a')

    b_refs = _docx_refs(stores, stores.get_task('task-b'))
    assert b_refs == [ref_b], f'B 的列表读到了别的包：{b_refs}'
    a_refs = _docx_refs(stores, stores.get_task('task-a'))
    assert a_refs == [ref_a]


# --------------------------------------------------------------------------- #
# 缺口 2：reference_comparison / hotspot 的数据根按包
# --------------------------------------------------------------------------- #
def test_reference_comparison_reads_task_package_root(tmp_path: Path) -> None:
    from app.reference_comparison import view

    stores = PackageStores(tmp_path)
    state = TaskState(id='task-b', package=B, kind='report', phase='processing', fact_ref='fact-b')
    stores.put_task(state)
    root_b = root_for(stores, 'task-b')
    folder = root_b / 'reference-comparison'
    folder.mkdir(parents=True)
    source = root_b / 'reference-source.json'
    source.write_bytes(b'{"rows": []}')
    (folder / 'summary.json').write_text(json.dumps({
        'task_id': 'task-b', 'fact_ref': 'fact-b', 'source': str(source),
        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
    }), encoding='utf-8')
    # A 的根里放一份诱饵：读错包就会命中它（task_id 不匹配 → reference_comparison_stale）
    decoy = stores.package_root(A) / 'reference-comparison'
    decoy.mkdir(parents=True)
    (decoy / 'summary.json').write_text(json.dumps({'task_id': 'task-a', 'fact_ref': 'fact-a'}),
                                        encoding='utf-8')

    assert view(stores, 'task-b')['task_id'] == 'task-b'


def test_hotspot_index_lives_in_target_package(tmp_path: Path) -> None:
    from app import hotspot

    stores = PackageStores(tmp_path)
    b_store = store_for(stores, B)
    assert hotspot._index_path(b_store) == tmp_path / 'packages' / B / 'hotspot' / 'latest.json'
    ref = b_store.put_artifact('hotspot-homepage', hotspot.KIND, {
        'items': [], 'collected_at': '2026-11-16T00:00:00+00:00',
        'window': {'from': '2026-11-13', 'to': '2026-11-16'}})
    hotspot._write_index(b_store, ref, b_store.get_artifact(ref))
    assert hotspot.latest(b_store)['ref'] == ref
    # 默认包的根里没有这份索引（没有串包）
    assert hotspot.latest(store_for(stores, A)) is None


# --------------------------------------------------------------------------- #
# 缺口 3：模板目录支持随包发布（packages/<pkg>/templates/），缺失如实报错
# --------------------------------------------------------------------------- #
def _package_with_templates(root: Path, name: str) -> Path:
    directory = root / name
    (directory / 'templates').mkdir(parents=True)
    (directory / 'manifest.yaml').write_bytes(
        f'package: {name}\nreport_type: 测试\nversion: 0.0.0\n'
        f'template: template.json\nprompts: prompts/\n'.encode('utf-8'))
    (directory / 'templates' / 'report.template.json').write_bytes(b'{}')
    return directory


def test_template_dir_supports_package_local_templates(tmp_path: Path, monkeypatch) -> None:
    packages_root = tmp_path / 'packages'
    package = _package_with_templates(packages_root, 'pkg_with_tpl')
    monkeypatch.setenv('REPORT_PACKAGES_ROOT', str(packages_root))
    monkeypatch.setenv('REPORT_TEMPLATES_ROOT', str(tmp_path / 'templates'))
    assert paths.template_dir('pkg_with_tpl') == package / 'templates'


def test_template_dir_missing_is_reported_not_defaulted(tmp_path: Path, monkeypatch) -> None:
    packages_root = tmp_path / 'packages'
    (packages_root / 'pkg_without_tpl').mkdir(parents=True)
    monkeypatch.setenv('REPORT_PACKAGES_ROOT', str(packages_root))
    monkeypatch.setenv('REPORT_TEMPLATES_ROOT', str(tmp_path / 'templates'))
    with pytest.raises(RuntimeError, match='template_dir_missing:pkg_without_tpl'):
        paths.template_dir('pkg_without_tpl')


def test_template_dir_accepts_legacy_host_layout(tmp_path: Path, monkeypatch) -> None:
    templates_root = tmp_path / 'templates'
    (templates_root / 'legacy_pkg').mkdir(parents=True)
    monkeypatch.setenv('REPORT_PACKAGES_ROOT', str(tmp_path / 'packages'))
    monkeypatch.setenv('REPORT_TEMPLATES_ROOT', str(templates_root))
    assert paths.template_dir('legacy_pkg') == templates_root / 'legacy_pkg'


# --------------------------------------------------------------------------- #
# 缺口 8：图结构可显式按包展示
# --------------------------------------------------------------------------- #
def test_workflow_graphs_can_be_built_for_an_explicit_package(tmp_path: Path) -> None:
    from app.api_views.graphs import workflow_graphs_view
    from app.workflow import Dependencies
    from fastapi import HTTPException

    stores = PackageStores(tmp_path)
    result = workflow_graphs_view(Dependencies(stores), B)
    assert set(result) == {'report', 'writing'}
    assert result['report']['nodes'] and result['writing']['nodes']
    assert 'graph TD' in result['report']['mermaid']
    with pytest.raises(HTTPException) as missing:
        workflow_graphs_view(Dependencies(stores), 'no_such_package')
    assert missing.value.status_code == 404


# --------------------------------------------------------------------------- #
# ① 验收：默认包（A）的父子进程分词一致（覆盖层由父/子各自按包读取）
# --------------------------------------------------------------------------- #
def test_default_package_tokenizer_matches_between_parent_and_worker() -> None:
    from core.text import tokenize

    expected = tokenize(SAMPLE, package=A)
    done = subprocess.run(
        [sys.executable, '-W', 'ignore', '-c',
         'import sys,json;sys.path.insert(0,sys.argv[1])\n'
         'from pathlib import Path\n'
         'from core.tool_executor import _configure_package\n'
         'from core.text import tokenize\n'
         '_configure_package(Path("packages")/sys.argv[2])\n'
         'print(json.dumps({"tokens":tokenize(sys.argv[3])},ensure_ascii=False))',
         str(REPO), A, SAMPLE],
        cwd=str(REPO), capture_output=True, text=True, encoding='utf-8', timeout=300)
    assert done.returncode == 0, done.stderr
    result = json.loads([line for line in done.stdout.splitlines() if line.startswith('{')][-1])
    assert result['tokens'] == expected, f'父子进程分词不一致：{result["tokens"]} vs {expected}'
    assert '平坝区' in expected
