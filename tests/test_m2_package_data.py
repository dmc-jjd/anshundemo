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
    (base / 'demo.sqlite3').write_bytes(b'SQLite format 3\x00legacy')
    monkeypatch.setattr(paths, '_legacy_root_warned', False)
    with caplog.at_level('WARNING', logger='core.paths'):
        assert paths.data_root(A) == base
        assert any('legacy_data_root_in_use' in record.getMessage() for record in caplog.records)
        assert paths.data_root(B) == base / 'packages' / B
    # 包里一旦有了非空 db，自动走新布局（不再回落）
    (base / 'packages' / A).mkdir(parents=True)
    (base / 'packages' / A / 'demo.sqlite3').write_bytes(b'SQLite format 3\x00migrated')
    assert paths.data_root(A) == base / 'packages' / A


def test_empty_package_dir_is_not_a_migrated_root(base: Path, monkeypatch, caplog) -> None:
    """★ 迁移失败残留的空 `packages/<包>/` 必须回落旧根（否则应用读空包根 = 0 条任务）。"""
    (base / 'demo.sqlite3').write_bytes(b'SQLite format 3\x00legacy')
    (base / 'packages' / A).mkdir(parents=True)                 # 只有空目录，没有 db
    monkeypatch.setattr(paths, '_legacy_root_warned', False)
    with caplog.at_level('WARNING', logger='core.paths'):
        assert paths.data_root(A) == base
        assert paths.data_root(A) == base                       # 再问一次仍回落
    messages = [record.getMessage() for record in caplog.records
                if 'legacy_data_root_in_use' in record.getMessage()]
    assert len(messages) == 1                                   # 恰一次，不刷屏
    assert 'demo.sqlite3' in messages[0] and str(base) in messages[0]
    assert '迁移未完成或失败残留' in messages[0]


def test_zero_byte_package_db_is_not_migrated(base: Path, monkeypatch) -> None:
    """0 字节的库是坏数据，不算「已迁移」——仍回落旧根（判据是存在且 size>0）。"""
    (base / 'demo.sqlite3').write_bytes(b'SQLite format 3\x00legacy')
    (base / 'packages' / A).mkdir(parents=True)
    (base / 'packages' / A / 'demo.sqlite3').write_bytes(b'')
    monkeypatch.setattr(paths, '_legacy_root_warned', False)
    assert paths.data_root(A) == base


def test_non_default_package_never_falls_back_even_with_empty_dir(base: Path) -> None:
    """非默认包永不回落（M2 串包语义不变：空目录返回空包根，绝不串到默认包的旧根）。"""
    (base / 'demo.sqlite3').write_bytes(b'SQLite format 3\x00legacy')
    (base / 'packages' / B).mkdir(parents=True)
    assert paths.data_root(B) == base / 'packages' / B


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


# --------------------------------------------------------------------------- #
# ⑤ 迁移脚本：失败不留空目录 / failed 台账 / 不轻信过期 done
#    为什么必须机械钉住：脚本先建目录再搬文件，失败残留的空 `packages/<包>/` 会把
#    「迁移失败」伪装成「已迁移」，应用随即读空库（用户视角：数据全没了）。
# --------------------------------------------------------------------------- #
def _load_migrator():
    import importlib.util

    path = REPO / 'scripts' / 'migrate_data_packages.py'
    spec = importlib.util.spec_from_file_location('migrate_data_packages_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_legacy_root(root: Path) -> None:
    """造一份最小旧单根数据：真 sqlite 库（含 artifacts 行）+ artifacts/ + uploads/。"""
    import sqlite3

    root.mkdir(parents=True, exist_ok=True)
    (root / 'artifacts').mkdir()
    (root / 'artifacts' / 'a1.json').write_bytes(b'{"value":1}\n')
    (root / 'uploads').mkdir()
    (root / 'uploads' / 'u1.bin').write_bytes(b'upload-bytes')
    conn = sqlite3.connect(str(root / 'demo.sqlite3'))
    try:
        conn.execute('CREATE TABLE tasks (id TEXT PRIMARY KEY)')
        conn.execute('CREATE TABLE artifacts (id TEXT PRIMARY KEY, path TEXT)')
        conn.execute('CREATE TABLE events (id INTEGER PRIMARY KEY)')
        conn.execute("INSERT INTO tasks (id) VALUES ('t1')")
        conn.execute("INSERT INTO artifacts (id, path) VALUES ('a1', ?)",
                     (str(root / 'artifacts' / 'a1.json'),))
        conn.commit()
    finally:
        conn.close()


def test_migrate_failure_removes_own_empty_dirs_and_records_failed(tmp_path, monkeypatch) -> None:
    """搬到目标根时失败（WinError 32 同型 PermissionError）→ 不留空目录 + status failed。

    preflight 自己的「改名→改回」探测不拦（那个动作必须成功），只拦**搬进 `packages/`** 的
    那一次 `os.replace`：这正是老 bug 的现场——目录已建、文件没搬成。
    """
    module = _load_migrator()
    root = tmp_path / 'data'
    _seed_legacy_root(root)
    state_path = root / module.STATE_NAME
    rows = module.plan(root, A)
    before = sorted(path.name for path in root.iterdir())

    real_replace = module.os.replace

    def picky_replace(src, dst):
        target = Path(str(dst))
        if 'packages' in target.parts and target.name == module.DB_NAME:
            raise PermissionError(32, 'The process cannot access the file '
                                      'because it is being used by another process')
        return real_replace(src, dst)

    monkeypatch.setattr(module.os, 'replace', picky_replace)
    with pytest.raises(PermissionError):
        module.apply_forward(root, A, rows, state_path)
    monkeypatch.undo()

    assert not (root / 'packages').exists()                    # ★ 失败绝不留空目录
    assert sorted(path.name for path in root.iterdir()) == sorted([*before, module.STATE_NAME])
    assert (root / 'demo.sqlite3').is_file() and (root / 'uploads' / 'u1.bin').is_file()
    recorded = json.loads(state_path.read_text(encoding='utf-8'))
    assert recorded['status'] == 'failed'
    assert '32' in recorded['error'] or 'PermissionError' in recorded['error']
    assert any(str(part).endswith('packages') for part in recorded['cleanup_removed_dirs'])


def test_migrate_refuses_before_creating_anything_when_wal_present(tmp_path) -> None:
    """预检发现 -wal 残留 → 拒绝；一个目录都不建，但台账要记 failed。"""
    module = _load_migrator()
    root = tmp_path / 'data'
    _seed_legacy_root(root)
    (root / f'{module.DB_NAME}-wal').write_bytes(b'')
    state_path = root / module.STATE_NAME
    rows = module.plan(root, A)

    with pytest.raises(RuntimeError, match='source_db_active_writer'):
        module.apply_forward(root, A, rows, state_path)
    assert not (root / 'packages').exists()
    recorded = json.loads(state_path.read_text(encoding='utf-8'))
    assert recorded['status'] == 'failed'
    assert 'source_db_active_writer' in recorded['error']


def test_migrate_already_migrated_requires_target_db_and_file_count(tmp_path) -> None:
    """state 说 done 但目标根是空目录/文件数不符 → 不算已迁移（否则把失败残留当完成）。"""
    module = _load_migrator()
    root = tmp_path / 'data'
    (root / 'packages' / A).mkdir(parents=True)                # 只有空目录
    state = {'status': 'done',
             'items': {module.DB_NAME: {'status': 'moved', 'group': 'package', 'files': 1}}}
    assert module.already_migrated(root, A, state, []) is False
    (root / 'packages' / A / module.DB_NAME).write_bytes(b'SQLite format 3\x00')  # 有库无文件
    assert module.already_migrated(root, A, state, []) is True
