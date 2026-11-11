#!/usr/bin/env python
"""G-CORE-ISO 门禁：S7 基座的「身份」（字节）与「方向」（core 是否反向依赖 app）。

存在理由：
    S2–S6 的门禁没有一条钉住 `core/` 的字节身份，`G-CORE-CLEAN` 只查 5 个业务词，
    `G-PYTEST` 只查行为。于是「加了一个包、core 没动」今天无法机械判定；而
    「core 不依赖 app」今天是假的（15 站点 / 8 文件）。本尺子同时量这两件事。

四条判据：
    CORE-HASH    `core/**` 全部文件（27 个 `.py` + 1 个基座 JSON 描述符
                 `core/skills/skill-core/lieflat-less-ai-tone.json`；排除 `__pycache__`/`*.pyc`）
                 逐文件 sha256 的映射再规范化哈希（见 `_canonical`）
    CORE-FILES   上述文件数（起点 28 = 27 `.py` + 1 基座 JSON 描述符）
    CORE-DEP     ast 扫 `core/**/*.py` 的 Import/ImportFrom，命中 `app`/`app.*` 的站点数 / 文件数
    APP-HASH     同 CORE-HASH 口径，但只扫 `app/**/*.py`（宿主零改动的依据）

与 `gate_core_clean.py` 打印的 27 不矛盾（两个口径，各查一件事）：
    clean 只扫 `.py`，查的是「代码里有没有客户业务词」；
    iso 的 CORE-FILES 是 28，查的是「基座身份有没有被动过」，技能描述符 JSON 也是身份的一部分。
    只有改动其中一方的扫描面，两行数字才会真的打架。

判据来源：
    `docs/team/baseline/core-S7-start.json`（`--record` 生成，禁止手写）。
    A 包之后 `--record` 到 `core-S7-preB.json` 由 WP-S7-B 做；脚本内**不存任何期望值**。

用法：
    python scripts/gate_core_iso.py --record    # 录基线（存在即拒绝，--force 才覆盖）
    python scripts/gate_core_iso.py             # 比对（--check 为默认）
    python scripts/gate_core_iso.py --twice     # 连跑两次并断言同值

退出码：0 PASS；1 FAIL；2 输入或基线缺失
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = REPO / "docs" / "team" / "baseline" / "core-S7-start.json"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(payload: object) -> str:
    # 既有 gate 口径（app/storage.py:23、scripts/gate_skill.py:_canonical）：不传 separators。
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return _sha(raw.encode())


def tree_files(root: Path, pattern: str) -> list[Path]:
    """`root` 下匹配 pattern 的文件，按 posix 相对路径排序；排除 `__pycache__` 与 `*.pyc`。"""
    files = [
        p for p in root.rglob(pattern)
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    ]
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def py_files(root: Path) -> list[Path]:
    return tree_files(root, "*.py")


def tree_hash(root: Path, pattern: str) -> dict[str, str]:
    """`{f'{root.name}/{rel}': sha256(bytes)}`——带包名前缀，便于差异行直接归因。"""
    if not root.is_dir():
        return {}
    return {f"{root.name}/{p.relative_to(root).as_posix()}": _sha(p.read_bytes()) for p in tree_files(root, pattern)}


def tree_digest(root: Path, pattern: str) -> str:
    return _canonical(tree_hash(root, pattern))


def dep_sites(root: Path) -> list[dict]:
    """ast 逐站点扫 `root` 对 `app` / `app.*` 的反向依赖；`file` 带包名前缀。"""
    rows: list[dict] = []
    for path in py_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = f"{root.name}/{path.relative_to(root).as_posix()}"
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names if a.name == "app" or a.name.startswith("app.")]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level == 0 and (module == "app" or module.startswith("app.")):
                    modules = [module]
            rows += [{"file": rel, "line": node.lineno, "module": m} for m in modules]
    return sorted(rows, key=lambda r: (r["file"], r["line"], r["module"]))


def dep_counts(entries: list[dict]) -> tuple[int, int]:
    return len(entries), len({e["file"] for e in entries})


def observe(core_root: Path, app_root: Path) -> dict:
    """一次完整观测；`--twice` 与测试都复用它。纯读盘，无副作用。"""
    core_map = tree_hash(core_root, "*")
    app_map = tree_hash(app_root, "*.py")
    entries = dep_sites(core_root)
    sites, files = dep_counts(entries)
    return {
        "core_files": len(core_map),
        "core_hash": _canonical(core_map),
        "core_files_detail": core_map,
        "core_dep": {"sites": sites, "files": files, "entries": entries},
        "app_files": len(app_map),
        "app_hash": _canonical(app_map),
        "app_files_detail": app_map,
    }


def report(observed: dict) -> None:
    print(f"{'CORE-FILES':<12}{observed['core_files']}")
    dep = observed["core_dep"]
    print(f"{'CORE-DEP':<12}{dep['sites']} sites / {dep['files']} files")
    print(f"{'CORE-HASH':<12}{observed['core_hash']}")
    print(f"{'APP-HASH':<12}{observed['app_hash']}")
    for entry in dep["entries"]:
        print(f"{'CORE-DEP-ENTRY':<16}{entry['file']}:{entry['line']} {entry['module']}")


def _tree_diff(want: dict, got: dict) -> list[str]:
    lines = [f"  - {rel}" for rel in sorted(set(want) - set(got))]
    lines += [f"  + {rel}" for rel in sorted(set(got) - set(want))]
    lines += [f"  ~ {rel}" for rel in sorted(set(want) & set(got)) if want[rel] != got[rel]]
    return lines


def compare(observed: dict, baseline: dict) -> list[str]:
    """逐判据比对——只比总哈希给不出归因。"""
    problems: list[str] = []

    want_hash = baseline.get("core_hash")
    if want_hash != observed["core_hash"]:
        problems.append(f"CORE-HASH: expected {want_hash} got {observed['core_hash']}")
        problems += [f"CORE-HASH {line}" for line in
                     _tree_diff(baseline.get("core_files_detail") or {}, observed["core_files_detail"])]

    want_files = baseline.get("core_files")
    if want_files != observed["core_files"]:
        problems.append(f"CORE-FILES: expected {want_files} got {observed['core_files']}")

    want_dep = baseline.get("core_dep") or {}
    if (want_dep.get("sites"), want_dep.get("files")) != dep_counts(observed["core_dep"]["entries"]):
        problems.append(
            f"CORE-DEP: expected {want_dep.get('sites')} sites / {want_dep.get('files')} files "
            f"got {observed['core_dep']['sites']} sites / {observed['core_dep']['files']} files"
        )
    want_entries = {(e["file"], e["line"], e["module"]) for e in want_dep.get("entries") or []}
    got_entries = {(e["file"], e["line"], e["module"]) for e in observed["core_dep"]["entries"]}
    problems += [f"CORE-DEP missing {f}:{l} {m}" for f, l, m in sorted(want_entries - got_entries)]
    problems += [f"CORE-DEP extra {f}:{l} {m}" for f, l, m in sorted(got_entries - want_entries)]

    if baseline.get("app_hash") != observed["app_hash"]:
        problems.append(f"APP-HASH: expected {baseline.get('app_hash')} got {observed['app_hash']}")
        problems += [f"APP-HASH {line}" for line in
                     _tree_diff(baseline.get("app_files_detail") or {}, observed["app_files_detail"])]
    return problems


def record(baseline_path: Path, observed: dict, force: bool) -> int:
    if baseline_path.exists() and not force:
        print(f"[error] 基线已存在，拒绝覆盖: {baseline_path}（--force 才覆盖）", file=sys.stderr)
        return 2
    data = dict(observed)
    data["python"] = sys.version.split()[0]
    data["recorded_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("RECORDED", baseline_path.as_posix(), "force" if force else "")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="S7 基座身份与方向门禁（G-CORE-ISO）")
    parser.add_argument("--record", action="store_true", help="录基线")
    parser.add_argument("--check", action="store_true", help="比对（默认）")
    parser.add_argument("--twice", action="store_true", help="连跑两次并断言同值")
    parser.add_argument("--with-app", action="store_true", help="兼容规格：APP-HASH 恒输出")
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--force", action="store_true", help="配合 --record 覆盖已存在基线")
    parser.add_argument("--expect-dep-zero", action="store_true", help="CORE-DEP>0 时 FAIL（S7 出口用）")
    args = parser.parse_args()

    core_root = REPO / "core"
    if not core_root.is_dir():
        print(f"[error] core 目录缺失: {core_root}", file=sys.stderr)
        return 2
    baseline_path = Path(args.baseline)

    observed = observe(core_root, REPO / "app")
    report(observed)

    if args.twice:
        second = observe(core_root, REPO / "app")
        print(f"{'CORE-HASH-2ND':<16}{second['core_hash']}")
        if second != observed:
            print("RESULT: FAIL (两次运行不同值，存在非确定性)")
            return 1
        print("DETERMINISM: OK")

    if args.record:
        rc = record(baseline_path, observed, args.force)
        if rc:
            return rc
        print("RESULT: PASS")
        return 0

    if not baseline_path.exists():
        print(f"[error] 基线缺失: {baseline_path}（先跑 --record）", file=sys.stderr)
        return 2
    baseline = json.loads(baseline_path.read_text(encoding="utf-8-sig"))

    problems = compare(observed, baseline)
    if args.expect_dep_zero and observed["core_dep"]["sites"]:
        problems.append(f"CORE-DEP-ZERO: expected 0 sites got {observed['core_dep']['sites']}")
    if problems:
        for line in problems:
            print("MISMATCH", line)
        print(f"RESULT: FAIL ({len(problems)} mismatches)")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
