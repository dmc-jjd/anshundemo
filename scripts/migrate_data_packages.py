#!/usr/bin/env python
"""把旧单根数据目录迁移成「一包一根」布局（M2）。

旧布局（M1 及之前）：
    <base>/demo.sqlite3  <base>/artifacts/  <base>/uploads/  <base>/hotspot/  <base>/token-pricing.json
新布局（M2）：
    <base>/packages/<包>/demo.sqlite3  artifacts/  uploads/  hotspot/
    <base>/shared/token-pricing.json          ← 部署级价目表，不按包分

设计要点（真实执行时按这些点验收）：
    * **默认 dry-run**：不加 `--apply` 只打印计划（文件数/字节/聚合 sha），不碰盘；
    * **搬前预检（失败即拒绝，不留半成品）**：db 被别的进程占用（Windows 上 `os.replace`
      会 `WinError 32`）或源里有 `-wal`/`-journal` → 明确拒绝并提示「先停服务」，此时
      **一个目录都不建**：空的目标目录正是旧回落判据误判「已迁移」的原因；
    * **幂等**：`.migration-state.json` 记录每一项的 files/bytes/sha/status；第二次跑
      「源里没东西了 + 目标根 db 与文件数都对得上」→ 打印 already_migrated 并退出 0，**零写入**；
      只有 state 说 done、目标根却是空目录/文件数不符 → 不算已迁移，照常重跑（已搬的按 sha 跳过）；
    * **逐项原子落盘**：每一项搬完立刻原子写 state（tmp+os.replace）；中途失败可重跑，
      已搬的文件按 sha 相等识别为「已搬」并跳过，不会半搬；
    * **失败清理**：任何异常路径都把自己本次创建、且仍为空的目录删掉，state 记
      `status: failed` + `error`；**绝不留空目录**（只删空目录，里面还有数据就原样留着）；
    * **不丢数据**：搬前算 `(相对路径 → sha256)` 聚合，搬后重算并逐项比对；DB 的
      tasks/artifacts/events 行数也前后比对；不一致 → 退出码 1（state 保留，便于排查）；
    * **artifacts.path 幂等改写**：旧行存绝对路径，搬到新根后按前缀 UPDATE（0 行 = 已改过）；
      `core/storage.py` 的 `files/{ref}.json` 回退仍然有效，改 path 是顺手把遗留收干净；
    * **回退**：`--apply --rollback` 把新根搬回旧根并把 path 改回去（state 标记 rolled_back）；
      没有 state 时按 README 用备份恢复（备份由执行人负责，脚本不碰备份目录）；
    * **不建 junction/软链**：旧根只留 `README-migrated.md`，让「忘改的调用点」立刻暴露。

用法：
    python scripts/migrate_data_packages.py                       # dry-run（默认）
    python scripts/migrate_data_packages.py --source .conda/m2-data-copy/data --package anshun_monthly --apply
    python scripts/migrate_data_packages.py --source .conda/m2-data-copy/data --apply --rollback
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

STATE_NAME = '.migration-state.json'
README_NAME = 'README-migrated.md'
#: 按包分家的目录项（旧根下的名字 → 新包根下的名字）。
PACKAGE_DIRS = ('artifacts', 'uploads', 'hotspot')
DB_NAME = 'demo.sqlite3'
PRICING_NAME = 'token-pricing.json'
#: 旧根里不参与迁移的项（新布局自己的目录 + 本脚本的产物）。
IGNORED = {'packages', 'shared', STATE_NAME, README_NAME, '__pycache__'}


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: dict) -> None:
    """原子写 JSON（UTF-8 / LF）：state 永远要么是旧版本、要么是新版本，不会是半个文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_bytes(json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8') + b'\n')
    os.replace(tmp, path)


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def files_under(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(path for path in root.rglob('*') if path.is_file())


def digest_of(root: Path) -> dict:
    """`(相对路径 → sha256)` 的聚合：files / bytes / sha256(排序后的清单)。"""
    files = files_under(root)
    base = root.parent if root.is_file() else root
    rows = [(path.relative_to(base).as_posix(), sha256_file(path)) for path in files]
    payload = ''.join(f'{name}\t{digest}\n' for name, digest in rows).encode('utf-8')
    return {'files': len(rows), 'bytes': sum(path.stat().st_size for path in files),
            'sha256': hashlib.sha256(payload).hexdigest(), 'rows': rows}


def db_counts(path: Path) -> dict:
    """DB 行数快照（只读打开；表不存在记 0）。"""
    if not path.is_file():
        return {}
    try:
        conn = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)
    except sqlite3.Error:
        return {}
    try:
        counts = {}
        for table in ('tasks', 'artifacts', 'events'):
            try:
                counts[table] = conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
            except sqlite3.Error:
                counts[table] = 0
        return counts
    finally:
        conn.close()


def db_ids(path: Path) -> list[str]:
    """DB 里全部 artifact id（排序）；搬前后逐条比对，证明「没丢行」。"""
    if not path.is_file():
        return []
    try:
        conn = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)
    except sqlite3.Error:
        return []
    try:
        try:
            return sorted(row[0] for row in conn.execute('SELECT id FROM artifacts'))
        except sqlite3.Error:
            return []
    finally:
        conn.close()


def missing_artifact_files(db: Path) -> list[str]:
    """DB 里登记了、但目标 artifacts 目录里没有的 `.json` 文件名（应为空）。"""
    if not db.is_file():
        return []
    artifacts = db.parent / 'artifacts'
    conn = sqlite3.connect(f'file:{db.as_posix()}?mode=ro', uri=True)
    try:
        try:
            rows = [row[0] for row in conn.execute('SELECT path FROM artifacts')]
        except sqlite3.Error:
            return []
    finally:
        conn.close()
    missing = []
    for path in rows:
        name = Path(str(path)).name
        if name.endswith('.json') and not (artifacts / name).is_file():
            missing.append(name)
    return missing


def rewrite_db_paths(db: Path, old_root, new_root) -> int:
    """把 `artifacts.path` 的根从 `old_root` 改到 `new_root`；返回改动行数（0 = 已改过）。

    为什么不用 `UPDATE ... replace(path, old, new)`：`new_root` 可能是 `old_root` 的
    子路径（`data` → `data/packages/x`），前缀替换分不清「还没搬」和「已经搬到新根」，
    重跑一次就把 `.../packages/x/packages/x/...` 再套一层（实测踩过）。
    这里按**结构**改：只改「当前根 = old_root 且父目录名是 artifacts」的行，目标路径由
    basename 重新拼（`new_root/artifacts/<文件名>`）。正向/回退/重跑三种情况都唯一。
    """
    if not db.is_file():
        return 0
    old_prefix = str(old_root)
    changed = 0
    conn = sqlite3.connect(str(db), timeout=30)
    try:
        rows = conn.execute('SELECT id, path FROM artifacts').fetchall()
        for ref, raw in rows:
            path = str(raw or '')
            if not path.startswith(old_prefix):
                continue
            if Path(path).parent.name != 'artifacts':
                continue
            target = str(Path(new_root) / 'artifacts' / Path(path).name)
            if path == target:
                continue
            conn.execute('UPDATE artifacts SET path = ? WHERE id = ?', (target, ref))
            changed += 1
        conn.commit()
    finally:
        conn.close()
    return changed


def _mkdir_tracked(directory: Path, created: list[Path]) -> None:
    """按需逐级建目录，并把**本次运行新建**的目录记进 `created`（失败时只回收这些）。

    为什么不在执行前预建目标根：迁移可能第一步就失败（db 被占用），预建目录会留下空的
    `packages/<包>/`；旧回落判据看目录存在，于是下次启动读空包根、0 条任务。
    """
    missing: list[Path] = []
    current = directory
    while not current.exists():
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    for path in reversed(missing):
        try:
            path.mkdir()
        except FileExistsError:
            continue
        created.append(path)


def _cleanup_created(created: list[Path]) -> list[str]:
    """删掉本次运行创建、且**仍为空**的目录（自底向上）；返回删掉的路径。

    只删空目录：`rmdir` 对非空目录抛 OSError，那里的东西是数据不是残渣，原样留着给人看。
    """
    removed: list[str] = []
    for directory in sorted(created, key=lambda path: -len(path.parts)):
        try:
            directory.rmdir()
        except OSError:
            continue
        removed.append(str(directory))
    return removed


def move_file(src: Path, dst: Path, created: list[Path] | None = None) -> str:
    """搬一个文件；目标已存在且内容相同 → 视为已搬（重跑/续搬），返回 'skipped'。"""
    _mkdir_tracked(dst.parent, created if created is not None else [])
    if dst.exists():
        if sha256_file(dst) != sha256_file(src):
            raise RuntimeError(f'migration_conflict: {src} 与 {dst} 内容不同，拒绝合并')
        src.unlink()
        return 'skipped'
    os.replace(src, dst)
    return 'moved'


def move_tree(src: Path, dst: Path, created: list[Path] | None = None) -> dict:
    """逐文件搬 + 清空旧目录；返回 {'moved': n, 'skipped': n}。"""
    counts = {'moved': 0, 'skipped': 0}
    tracker = created if created is not None else []
    if src.is_file():
        counts[move_file(src, dst, tracker)] += 1
        return counts
    root = src
    for path in files_under(root):
        relative = path.relative_to(root)
        counts[move_file(path, dst / relative, tracker)] += 1
    # 自底向上删空目录（非空目录说明还有别的东西，留着让执行人看见）
    for directory in sorted((p for p in root.rglob('*') if p.is_dir()), key=lambda p: -len(p.parts)):
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        root.rmdir()
    except OSError:
        pass
    return counts


def candidate_items(source: Path, package: str) -> list[dict]:
    """全部候选项（不判存在性）：迁移与回退共用同一张 src/dst 对照表。"""
    target = source / 'packages' / package
    items = [{'name': DB_NAME, 'kind': 'file', 'src': source / DB_NAME, 'dst': target / DB_NAME,
              'group': 'package'}]
    items += [{'name': name, 'kind': 'dir', 'src': source / name, 'dst': target / name,
               'group': 'package'} for name in PACKAGE_DIRS]
    items.append({'name': PRICING_NAME, 'kind': 'file', 'src': source / PRICING_NAME,
                  'dst': source / 'shared' / PRICING_NAME, 'group': 'shared'})
    return items


def plan(source: Path, package: str) -> list[dict]:
    """计划项（只含源里真实存在的项）；每项带搬前 files/bytes/sha。"""
    rows = []
    for item in candidate_items(source, package):
        if not item['src'].exists():
            continue
        snapshot = digest_of(item['src'])
        item = {**item, **snapshot,
                'db_before': db_counts(item['src']) if item['kind'] == 'file'
                and item['name'] == DB_NAME else {},
                'db_ids': db_ids(item['src']) if item['kind'] == 'file'
                and item['name'] == DB_NAME else []}
        rows.append(item)
    return rows


def source_leftovers(source: Path) -> list[str]:
    try:
        return sorted(entry.name for entry in source.iterdir() if entry.name not in IGNORED)
    except OSError:
        return []


def describe(source: Path, package: str, rows: list[dict]) -> dict:
    return {'source': str(source), 'package': package,
            'target': str(source / 'packages' / package),
            'shared': str(source / 'shared'),
            'items': [{key: item[key] for key in ('name', 'group', 'kind', 'files', 'bytes', 'sha256')}
                      for item in rows],
            'files': sum(item['files'] for item in rows),
            'bytes': sum(item['bytes'] for item in rows)}


def preflight(source: Path) -> None:
    """搬任何东西之前的预检：失败即拒绝，且**一个目录都不建**。

    Windows 上 `os.replace` 搬一个正被 sqlite 打开的库会 `PermissionError: [WinError 32]`。
    探测用 `os.replace` 本身（改名 → 立刻改回），**不是** `open('r+b')`：sqlite 以
    `FILE_SHARE_READ|FILE_SHARE_WRITE` 打开库，服务占着时 `open('r+b')` 照样成功（实测），
    只有「改名/删除」这一步才会撞上共享冲突。改名-改回成对出现，不改文件内容。
    """
    for suffix in ('-wal', '-journal'):
        if (source / f'{DB_NAME}{suffix}').exists():
            raise RuntimeError(f'source_db_active_writer: 发现 {DB_NAME}{suffix}；'
                               '先停写库进程（uvicorn）再 --apply，避免搬一个正在写的库')
    database = source / DB_NAME
    if not database.is_file():
        return
    probe = database.with_name(f'.{database.name}.probe')
    if probe.exists():
        raise SystemExit(
            f'migration_aborted: 发现上次探测残留 {probe.name} 而 {DB_NAME} 情况不确定，'
            '先人工确认库文件再去掉残留')
    try:
        os.replace(database, probe)
    except OSError as exc:
        raise SystemExit(
            f'migration_aborted: {DB_NAME} 正被其它进程占用（先停止服务再迁移）：{exc}') from exc
    try:
        os.replace(probe, database)
    except OSError as exc:
        raise SystemExit(
            f'migration_aborted: 探测后无法把 {DB_NAME} 改回原名'
            f'（内容暂存于 {probe}，先人工改名回来）：{exc}') from exc


def apply_forward(source: Path, package: str, rows: list[dict], state_path: Path) -> dict:
    """预检 + 失败兜底：拒绝时不留半成品；任何异常都删掉本次建的空目录并记 `failed`。"""
    created: list[Path] = []
    try:
        preflight(source)
        return _apply_forward(source, package, rows, state_path, created)
    except BaseException as exc:
        removed = _cleanup_created(created)
        state = read_json(state_path) or {
            'version': 1, 'source': str(source), 'package': package, 'items': {}}
        state.update(version=1, source=str(source), package=package,
                     target=str(source / 'packages' / package),
                     shared=str(source / 'shared'),
                     status='failed', error=str(exc) or exc.__class__.__name__,
                     failed_at=stamp(), updated_at=stamp(),
                     cleanup_removed_dirs=removed)
        write_json(state_path, state)
        raise


def _apply_forward(source: Path, package: str, rows: list[dict], state_path: Path,
                   created: list[Path]) -> dict:
    state = read_json(state_path) or {
        'version': 1, 'source': str(source), 'package': package,
        'target': str(source / 'packages' / package), 'shared': str(source / 'shared'),
        'status': 'in_progress', 'started_at': stamp(), 'items': {}}
    state.update(version=1, source=str(source), package=package,
                 target=str(source / 'packages' / package), shared=str(source / 'shared'),
                 status='in_progress', updated_at=stamp())
    write_json(state_path, state)

    # 崩溃恢复：DB 已搬、但 state 没来得及记「已改 path」时补一次（幂等 UPDATE 兜底）。
    db_item = next(item for item in candidate_items(source, package) if item['name'] == DB_NAME)
    if (not db_item['src'].exists() and db_item['dst'].exists()
            and state['items'].get(DB_NAME, {}).get('status') != 'moved'):
        rewrites = rewrite_db_paths(db_item['dst'], str(source), str(db_item['dst'].parent))
        recovered = digest_of(db_item['dst'])
        state['items'][DB_NAME] = {
            'status': 'moved', 'group': 'package', 'files': recovered['files'],
            'bytes': recovered['bytes'], 'sha256': recovered['sha256'], 'moved_at': stamp(),
            'move': {'moved': 0, 'skipped': 0}, 'db_path_rewrites': rewrites,
            'db_before': db_counts(db_item['dst']), 'db_after': db_counts(db_item['dst']),
            'recovered': True}
        write_json(state_path, state)

    for item in rows:
        entry = state['items'].get(item['name'], {})
        if entry.get('status') == 'moved' and not item['src'].exists() and item['dst'].exists():
            continue
        if item['name'] == DB_NAME and item['src'].exists():
            item['db_before'] = db_counts(item['src'])
            item['db_ids'] = db_ids(item['src'])
        counts = move_tree(item['src'], item['dst'], created)
        rewrites = 0
        if item['name'] == DB_NAME and item['dst'].exists():
            rewrites = rewrite_db_paths(item['dst'], str(source), str(item['dst'].parent))
            # DB 不是普通文件：改 path 会改字节，所以「不丢数据」按**逻辑内容**验
            # （行数 + artifact id 全集 + 每个登记文件都在），并把改写后的摘要作为新期望。
            after_counts = db_counts(item['dst'])
            after_ids = db_ids(item['dst'])
            if item.get('db_before') and after_counts != item['db_before']:
                raise RuntimeError(f"verify_failed: db counts {item['db_before']} -> {after_counts}")
            if item.get('db_ids') and after_ids != item['db_ids']:
                raise RuntimeError('verify_failed: db artifact id set changed')
            # 注意：artifact 文件晚于 DB 搬（items 顺序），故「登记文件是否都在」放到全量
            # verify_forward 里查——在搬 DB 的这一刻查必然缺（会误报 verify_failed）。
            rewritten = digest_of(item['dst'])
            item.update(files=rewritten['files'], bytes=rewritten['bytes'], sha256=rewritten['sha256'])
        after = digest_of(item['dst'])
        if (after['files'], after['sha256']) != (item['files'], item['sha256']):
            raise RuntimeError(f"verify_failed: {item['name']} files {item['files']}->{after['files']} "
                               f"sha {item['sha256']}->{after['sha256']}")
        state['items'][item['name']] = {
            'status': 'moved', 'group': item['group'], 'files': after['files'],
            'bytes': after['bytes'], 'sha256': after['sha256'], 'moved_at': stamp(),
            'move': counts, 'db_path_rewrites': rewrites,
            'db_before': item.get('db_before') or {}, 'db_after': db_counts(item['dst']),
        }
        write_json(state_path, state)

    # 全量再验一次（逐项 + DB 行数）
    verify = verify_forward(source, package, rows, state)
    state['verify'] = verify
    state['verified'] = verify['ok']
    state['status'] = 'done' if verify['ok'] else 'verify_failed'
    state['updated_at'] = stamp()
    write_json(state_path, state)
    if verify['ok']:
        write_readme(source, package, state_path)
    return state


def verify_forward(source: Path, package: str, rows: list[dict], state: dict) -> dict:
    """按 state 逐项复核目的地：files/sha 与搬前（DB 用改写后的摘要）一致，DB 行数一致。"""
    candidates = {item['name']: item for item in candidate_items(source, package)}
    problems = []
    for name, entry in state.get('items', {}).items():
        if entry.get('status') != 'moved':
            continue
        item = candidates.get(name)
        if item is None or not item['dst'].exists():
            problems.append(f'missing:{name}')
            continue
        after = digest_of(item['dst'])
        if (after['files'], after['sha256']) != (entry.get('files'), entry.get('sha256')):
            problems.append(f"sha:{name}")
        if name == DB_NAME:
            before = entry.get('db_before') or {}
            current = db_counts(item['dst'])
            if before and current != before:
                problems.append(f'db_counts:{before}->{current}')
            missing = missing_artifact_files(item['dst'])
            if missing:
                problems.append(f'artifact_files_missing:{missing[:5]}')
    leftovers = source_leftovers(source)
    if leftovers:
        problems.append(f'leftovers:{leftovers}')
    return {'ok': not problems, 'problems': problems,
            'items': {name: entry.get('files', 0) for name, entry in state.get('items', {}).items()},
            'db_path_rewrites': sum(entry.get('db_path_rewrites', 0)
                                    for entry in state.get('items', {}).values())}


def write_readme(source: Path, package: str, state_path: Path) -> None:
    """旧根留一张说明：新根在哪、怎么回退。**不建软链/junction**（会把漏改点永久藏起来）。"""
    target = source / 'packages' / package
    text = (
        '# 数据根已迁移（M2）\n\n'
        f'- 迁移时间：{stamp()}\n'
        f'- 旧根：`{source}`\n'
        f'- 新根（默认包 `{package}`）：`{target}`\n'
        f'- 共享数据：`{source / "shared"}`（例如 `token-pricing.json`）\n'
        f'- 迁移台账：`{state_path}`\n\n'
        '本目录不再存放业务数据，也不提供软链/junction（那会把忘改的调用点永久藏起来）。\n\n'
        '回退：\n'
        '```\n'
        f'python scripts/migrate_data_packages.py --source "{source}" --package {package} --apply --rollback\n'
        '```\n'
        '或从迁移前的备份整体恢复 `data/`（备份由执行人负责）。\n'
    )
    (source / README_NAME).write_bytes(text.encode('utf-8'))


def apply_rollback(source: Path, state_path: Path, package: str) -> dict:
    state = read_json(state_path)
    if not state:
        raise RuntimeError(f'rollback_state_missing: {state_path}')
    if state.get('status') == 'rolled_back':
        return state
    if state.get('status') != 'done':
        raise RuntimeError(f"rollback_requires_done_state: status={state.get('status')}")
    for item in candidate_items(source, package):
        dst = Path(item['dst'])
        src = Path(item['src'])
        if not dst.exists():
            continue
        if item['name'] == DB_NAME:
            rewrite_db_paths(dst, str(dst.parent), str(source))
        counts = move_tree(dst, src)
        state['items'].setdefault(item['name'], {})['rolled_back'] = {**counts, 'at': stamp()}
        write_json(state_path, state)
    readme = source / README_NAME
    if readme.exists():
        readme.unlink()
    state['status'] = 'rolled_back'
    state['updated_at'] = stamp()
    write_json(state_path, state)
    return state


def already_migrated(source: Path, package: str, state: dict, rows: list[dict]) -> bool:
    """「真的已迁移」= state 说 done **且** 目标根对得上（非空 db + 文件数一致）。

    只看 state 会把「上次迁移失败留下的空目录 + 旧 done 台账」当成完成；只看目录存在更糟
    （空目录 = 有效包根 → 应用读空库）。两条都对齐才算；否则照常重跑（已搬的按 sha 跳过，
    幂等）。`rows` 非空 = 旧根还有东西没搬，同样不算完成。
    """
    if state.get('status') != 'done' or rows or source_leftovers(source):
        return False
    target = source / 'packages' / package
    database = target / DB_NAME
    try:
        if not (database.is_file() and database.stat().st_size > 0):
            return False
    except OSError:
        return False
    expected = sum(int(entry.get('files') or 0)
                   for entry in state.get('items', {}).values()
                   if entry.get('group') == 'package' and entry.get('status') == 'moved')
    actual = digest_of(target)['files'] if target.is_dir() else 0
    return expected > 0 and actual == expected


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='旧单根 data/ → data/packages/<包>/ 迁移（默认 dry-run）')
    parser.add_argument('--source', default=None, help='旧数据根（默认：REPORT_DEMO_DATA 或 <repo>/data）')
    parser.add_argument('--package', default=None, help='目标包名（默认：REPORT_PACKAGE 或 anshun_monthly）')
    parser.add_argument('--state', default=None, help=f'迁移台账路径（默认：<source>/{STATE_NAME}）')
    parser.add_argument('--apply', action='store_true', help='真正执行（缺省只打印计划）')
    parser.add_argument('--rollback', action='store_true', help='与 --apply 连用：把新根搬回旧根')
    parser.add_argument('--json', action='store_true', help='输出 JSON（便于留证）')
    args = parser.parse_args(argv)

    from core.packages.context import default_package

    source = Path(args.source) if args.source else None
    if source is None:
        from core import paths
        try:
            source = paths.data_root_base()
        except RuntimeError:
            from core.config import DATA as _base
            source = Path(_base)
    source = source.resolve()
    package = args.package or default_package()
    state_path = Path(args.state) if args.state else source / STATE_NAME
    if not source.is_dir():
        print(f'[error] 源目录不存在：{source}', file=sys.stderr)
        return 2

    rows = plan(source, package)
    if args.rollback:
        if not args.apply:
            state = read_json(state_path) or {}
            print(json.dumps({'mode': 'rollback-dry-run', 'state': state.get('status'),
                              'target': state.get('target')}, ensure_ascii=False, indent=2))
            return 0
        state = apply_rollback(source, state_path, package)
        print(json.dumps({'mode': 'rollback', 'status': state['status'],
                          'source': str(source)}, ensure_ascii=False, indent=2))
        return 0

    state = read_json(state_path) or {}
    if already_migrated(source, package, state, rows):
        payload = {'mode': 'already-migrated', 'source': str(source), 'package': package,
                   'target': state.get('target'), 'verified': state.get('verified'),
                   'db_path_rewrites': state.get('verify', {}).get('db_path_rewrites')}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else
              f"already_migrated source={source} target={state.get('target')} "
              f"files={sum(i.get('files', 0) for i in state.get('items', {}).values())}")
        return 0

    description = describe(source, package, rows)
    if not args.apply:
        payload = {'mode': 'dry-run', **description}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(json.dumps({'mode': 'apply', **description}, ensure_ascii=False, indent=2))
    try:
        state = apply_forward(source, package, rows, state_path)
    except SystemExit as exc:          # 预检拒绝：state 已记 failed，这里只把话说清楚
        print(f'[error] {exc}', file=sys.stderr)
        return 2
    summary = {'mode': 'apply-done', 'status': state['status'], 'verified': state.get('verified'),
               'verify': state.get('verify'), 'target': state['target'],
               'db_path_rewrites': state.get('verify', {}).get('db_path_rewrites'),
               'items': {name: {key: entry.get(key) for key in ('files', 'bytes', 'sha256', 'db_path_rewrites')}
                         for name, entry in state['items'].items()}}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if state.get('verified') else 1


if __name__ == '__main__':
    raise SystemExit(main())
