#!/usr/bin/env python
"""L1 确定性层门禁：对指定产物做 sha256 快照比对。

用法：
    # 录制基线
    python scripts/verify_snapshot.py record --config scripts/snapshot_targets.json --out docs/team/baseline/snapshot-S0.json

    # 比对（退出码 0=一致，1=有差异）
    python scripts/verify_snapshot.py check --config scripts/snapshot_targets.json --baseline docs/team/baseline/snapshot-S0.json

设计约束：
- 只做文件字节 hash，不解释内容；解释内容归 verify_structure.py（L2）。
- 只记录相对路径，仓库搬家不影响比对。
- 空 glob 不算失败，但会在报告里列出来（防止"目标写错了却显示全绿"）。
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import sys
from pathlib import Path

DEFAULT_CONFIG = {
    "root": ".",
    "targets": [
        {"name": "docs", "globs": ["docs/**/*.md"], "optional": True},
    ],
    "exclude_globs": ["**/__pycache__/**", "**/.git/**"],
}


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_config(path: Path, root: Path) -> dict:
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_CONFIG))
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.setdefault("root", ".")
    cfg.setdefault("targets", [])
    cfg.setdefault("exclude_globs", [])
    return cfg


def collect(cfg: dict, root: Path) -> dict[str, str]:
    base = (root / cfg.get("root", ".")).resolve()
    excludes = cfg.get("exclude_globs") or []
    result: dict[str, str] = {}
    empty: list[str] = []

    for target in cfg.get("targets", []):
        name = target.get("name") or ",".join(target.get("globs", []))
        matched = 0
        for pattern in target.get("globs", []):
            for fp in base.glob(pattern):
                if not fp.is_file():
                    continue
                rel = fp.resolve().relative_to(root).as_posix()
                if any(fnmatch.fnmatch(rel, ex) for ex in excludes):
                    continue
                result[rel] = sha256(fp)
                matched += 1
        if matched == 0 and not target.get("optional"):
            empty.append(name)

    for name in empty:
        print(f"[warn] 目标未匹配到任何文件: {name}", file=sys.stderr)

    return dict(sorted(result.items()))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def compare(baseline: dict[str, str], current: dict[str, str]) -> dict:
    base_keys, cur_keys = set(baseline), set(current)
    changed = sorted(k for k in base_keys & cur_keys if baseline[k] != current[k])
    return {
        "added": sorted(cur_keys - base_keys),
        "removed": sorted(base_keys - cur_keys),
        "changed": changed,
        "identical": sorted(k for k in base_keys & cur_keys if baseline[k] == current[k]),
    }


def cmd_record(args) -> int:
    root = repo_root()
    cfg = load_config(Path(args.config), root)
    files = collect(cfg, root)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"kind": "snapshot", "targets_config": args.config, "files": files}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"recorded {len(files)} files -> {out}")
    return 0


def cmd_check(args) -> int:
    root = repo_root()
    cfg = load_config(Path(args.config), root)
    baseline_path = Path(args.baseline)
    if not baseline_path.exists():
        print(f"[error] 基线不存在: {baseline_path}", file=sys.stderr)
        return 2

    baseline = json.loads(baseline_path.read_text(encoding="utf-8")).get("files", {})
    current = collect(cfg, root)
    diff = compare(baseline, current)

    print(f"baseline files : {len(baseline)}")
    print(f"current  files : {len(current)}")
    print(f"identical      : {len(diff['identical'])}")
    for label in ("changed", "added", "removed"):
        items = diff[label]
        if items:
            print(f"\n[{label}] {len(items)}")
            for item in items[: args.max_print]:
                print(f"  {item}")
            if len(items) > args.max_print:
                print(f"  ... 还有 {len(items) - args.max_print} 条")

    failed = bool(diff["changed"] or diff["added"] or diff["removed"])
    print("\nRESULT:", "FAIL" if failed else "PASS")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="L1 确定性层快照门禁")
    sub = parser.add_subparsers(dest="cmd", required=True)

    rec = sub.add_parser("record", help="录制基线快照")
    rec.add_argument("--config", default="scripts/snapshot_targets.json")
    rec.add_argument("--out", required=True)
    rec.set_defaults(func=cmd_record)

    chk = sub.add_parser("check", help="与基线比对")
    chk.add_argument("--config", default="scripts/snapshot_targets.json")
    chk.add_argument("--baseline", required=True)
    chk.add_argument("--max-print", type=int, default=30)
    chk.set_defaults(func=cmd_check)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
