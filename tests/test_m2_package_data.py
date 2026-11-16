"""M2：数据按包隔离 + 客户包注册表 + 分词跨进程口径统一。

为什么这些用例必须存在（M2 的四个坑，每个一条机械判据）：
    ① 子进程数据根写死：`_configure_package` 不再 `package_dir.parent.parent`，必须吃
       显式 data_base，包根按包名派生；
    ② Store 按包：默认根随包解析，`PackageStores` 按 task_id 路由且交叉查不到对方；
    ③ 旧任务（`TaskState.package == ''`）回落默认包仍能读；
    ④ 分词：**同一句文本**在父进程与工具子进程对非默认包必须切出同一组 token
       （M1 的「首个声明者赢」会让 B 的父子进程各用一套机制）。
另加注册表：坏包在册但 `usable=False`，建任务 404/422，**绝不回落默认包**。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

from core import paths
from core.package_store import PackageStores
from core.packages import registry
from core.schemas import TaskState
from core.storage import Store

REPO = Path(__file__).resolve().parents[1]
A = 'anshun_monthly'
B = 'demo_b'
SAMPLE = '安顺市平坝区社区卫生服务中心获评景区片区示范点，游客投诉明显下降'


@pytest.fixture
def base(tmp_path):
    """临时部署数据基根；结束时还原进程里的基根（别污染 300+ 既有用例）。"""
    try:
        old = paths.data_root_base()
    except RuntimeError:          # 本文件单独跑：宿主尚未 import，没有基根可还原
        old = None
    paths.configure_data_root(tmp_path)
    try:
        yield tmp_path
    finally:
        if old is not None:
            paths.configure_data_root(old)


# --------------------------------------------------------------------------- #
# ① 路径：按包分家 + 旧根一次回落
# --------------------------------------------------------------------------- #
def test_data_root_is_per_package(base: Path) -> None:
    assert paths.data_root(A) == base / 'packages' / A
    assert paths.data_root(B) == base / 'packages' / B
    assert paths.data_root() == base / 'packages' / A          # 未绑定上下文 → 默认包
    assert paths.shared_data_root() == base / 'shared'
    with paths._context.package_context(B):
        assert paths.data_root() == base / 'packages' / B      # ContextVar 覆盖


def test_unmigrated_root_falls_back_once_with_warning(base: Path, monkeypatch, caplog) -> None:
    """旧单根布局：默认包回落旧根并 warning；非默认包永不回落（否则 B 读到 A 的数据）。"""
    (base / 'demo.sqlite3').write_bytes(b'')
    monkeypatch.setattr(paths, '_legacy_root_warned', False)
    with caplog.at_level('WARNING', logger='core.paths'):
        assert paths.data_root(A) == base
        assert any('legacy_data_root_in_use' in record.getMessage() for record in caplog.records)
        assert paths.data_root(B) == base / 'packages' / B
    # 新根一旦出现，自动走新布局（不再回落）
    (base / 'packages' / A).mkdir(parents=True)
    assert paths.data_root(A) == base / 'packages' / A


# --------------------------------------------------------------------------- #
# ② Store 按包 + 路由交叉隔离
# --------------------------------------------------------------------------- #
def test_store_default_root_follows_current_package(base: Path) -> None:
    assert Store().root == base / 'packages' / A
    with paths._context.package_context(B):
        assert Store().root == base / 'packages' / B
    explicit = Store(base / 'explicit-root')
    assert explicit.root == base / 'explicit-root'              # 显式给根的旧口径不变
    assert explicit.package is None


def test_package_stores_route_tasks_and_artifacts_by_package(tmp_path: Path) -> None:
    stores = PackageStores(tmp_path)
    states = {}
    for package in (A, B):
        state = TaskState(id=f'task-{package}', package=package, kind='report', phase='queued')
        stores.put_task(state)
        states[package] = state
        ref = stores.put_artifact(state.id, 'm2_probe', {'package': package})
        state.metadata['ref'] = ref
    assert stores.get_task('task-' + A).package == A
    assert stores.get_task('task-' + B).package == B
    assert stores.package_of('task-' + B) == B
    root_a, root_b = tmp_path / 'packages' / A, tmp_path / 'packages' / B
    assert (root_a / 'demo.sqlite3').is_file() and (root_b / 'demo.sqlite3').is_file()
    assert (root_a / 'artifacts' / f"{states[A].metadata['ref']}.json").is_file()
    assert (root_b / 'artifacts' / f"{states[B].metadata['ref']}.json").is_file()
    # 交叉查不到（这是「静默串包」的唯一机械判据）
    with pytest.raises(KeyError):
        Store(root_a).get_task('task-' + B)
    with pytest.raises(KeyError):
        Store(root_b).get_task('task-' + A)
    with pytest.raises(KeyError):
        Store(root_a).get_artifact(states[B].metadata['ref'])
    assert {task.id for task in stores.list_tasks()} == {'task-' + A, 'task-' + B}


def test_legacy_task_without_package_reads_from_default(tmp_path: Path) -> None:
    stores = PackageStores(tmp_path)
    stores.put_task(TaskState(id='legacy', kind='report', phase='queued'))
    state = stores.get_task('legacy')
    assert state.package == ''                                  # 旧字段原样保留
    assert stores.package_of('legacy') == A                     # 读时回落默认包
    assert (tmp_path / 'packages' / A / 'demo.sqlite3').is_file()


def test_artifact_file_resolves_across_packages(tmp_path: Path) -> None:
    stores = PackageStores(tmp_path)
    stores.put_task(TaskState(id='t-b', package=B, kind='report', phase='queued'))
    ref = stores.put_artifact('t-b', 'export_meta', {'mode': 'draft'})
    target = stores.files_for('t-b') / f'{ref}.docx'
    target.write_bytes(b'docx-bytes')
    assert stores.artifact_file(ref) == target


# --------------------------------------------------------------------------- #
# ③ 注册表：坏包在册、不可用、不回落
# --------------------------------------------------------------------------- #
def _make_packages(root: Path) -> None:
    shutil.copytree(REPO / 'packages' / B, root / 'good_b')
    broken = root / 'bad_manifest'
    broken.mkdir(parents=True)
    (broken / 'manifest.yaml').write_bytes(
        'package: bad_manifest\nreport_type: 坏包\n'.encode('utf-8'))
    broken_template = root / 'bad_template'
    broken_template.mkdir(parents=True)
    (broken_template / 'manifest.yaml').write_bytes(
        ('package: bad_template\nreport_type: 坏包\nversion: 0.0.1\n'
         'template: template.json\nprompts: prompts/\n').encode('utf-8'))
    (broken_template / 'template.json').write_bytes(b'{not json')


def test_registry_lists_broken_packages_without_hiding_them(tmp_path, monkeypatch) -> None:
    root = tmp_path / 'packages'
    _make_packages(root)
    monkeypatch.setenv('REPORT_PACKAGES_ROOT', str(root))
    entries = {entry['package']: entry for entry in registry.catalog()}
    assert set(entries) == {'good_b', 'bad_manifest', 'bad_template'}
    assert entries['good_b']['usable'] is True
    assert entries['good_b']['status'] == 'ok'
    assert entries['bad_manifest']['usable'] is False
    assert 'manifest_missing_keys' in entries['bad_manifest']['error']
    assert entries['bad_template']['usable'] is False
    assert 'template_unreadable' in entries['bad_template']['error']


def test_create_task_on_broken_package_is_rejected_not_defaulted(tmp_path, monkeypatch) -> None:
    from app.packages_api import resolve_package

    root = tmp_path / 'packages'
    _make_packages(root)
    monkeypatch.setenv('REPORT_PACKAGES_ROOT', str(root))
    assert resolve_package('good_b') == 'good_b'
    with pytest.raises(HTTPException) as broken:
        resolve_package('bad_manifest')
    assert broken.value.status_code == 422
    assert 'package_unavailable:bad_manifest' in broken.value.detail
    with pytest.raises(HTTPException) as unknown:
        resolve_package('no_such_package')
    assert unknown.value.status_code == 404


# --------------------------------------------------------------------------- #
# ④ 分词：父子进程同口径（M2 的核心决定）
# --------------------------------------------------------------------------- #
def _run_worker(script: str, *args: str) -> dict:
    done = subprocess.run([sys.executable, '-W', 'ignore', '-c', script, *args],
                          cwd=str(REPO), capture_output=True, text=True,
                          encoding='utf-8', timeout=300)
    assert done.returncode == 0, done.stderr
    return json.loads([line for line in done.stdout.splitlines() if line.startswith('{')][-1])


def test_worker_tokenizer_matches_parent_for_non_default_package() -> None:
    """B 的工具子进程必须与父进程切出同一组 token（M1 会差一组：社区/卫生 vs 社区卫生）。"""
    from core.text import tokenize

    expected = tokenize(SAMPLE, package=B)
    result = _run_worker(
        'import sys,json;sys.path.insert(0,sys.argv[1])\n'
        'from pathlib import Path\n'
        'from core.tool_executor import _configure_package\n'
        'from core.text import tokenize\n'
        '_configure_package(Path("packages")/sys.argv[2])\n'
        'print(json.dumps({"tokens":tokenize(sys.argv[3])},ensure_ascii=False))',
        str(REPO), B, SAMPLE)
    assert result['tokens'] == expected
    # 默认包不受影响：显式传包名与不传包名逐字节一致
    assert tokenize(SAMPLE) == tokenize(SAMPLE, package=A)


def test_worker_data_root_comes_from_explicit_base(tmp_path: Path) -> None:
    """坑①：子进程数据根必须来自父进程传的 data_base，不是 package_dir.parent.parent。

    数据根可以指到仓库外（这里是 tmp），技能资产仍随代码部署根解析（`packages/` 的上一级），
    所以不需要在 tmp 下复制 skills/。
    """
    project = tmp_path / 'proj'
    result = _run_worker(
        'import sys,json;sys.path.insert(0,sys.argv[1])\n'
        'from pathlib import Path\n'
        'from core.tool_executor import _configure_package\n'
        'from core import paths\n'
        '_configure_package(Path(sys.argv[1])/"packages"/"demo_b",Path(sys.argv[2]))\n'
        'print(json.dumps({"base":str(paths.data_root_base()),\n'
        '                  "b":str(paths.data_root("demo_b")),\n'
        '                  "a":str(paths.data_root("anshun_monthly"))},ensure_ascii=False))',
        str(REPO), str(project / 'data'))
    assert result['base'] == str(project / 'data')
    assert result['b'] == str(project / 'data' / 'packages' / 'demo_b')
    assert result['a'] == str(project / 'data' / 'packages' / A)


# --------------------------------------------------------------------------- #
# 三不变量：package 不进 artifact payload
# --------------------------------------------------------------------------- #
def test_package_never_enters_artifact_payload(tmp_path: Path) -> None:
    stores = PackageStores(tmp_path)
    state = TaskState(id='t', package=B, kind='report', phase='queued')
    stores.put_task(state)
    ref = stores.put_artifact('t', 'm2_probe', {'value': 1})
    payload = stores.get_artifact(ref)
    assert payload == {'value': 1}
    assert 'package' not in payload
    assert set(TaskState.model_fields) >= {'package'}          # 只进任务状态
