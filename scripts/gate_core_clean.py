#!/usr/bin/env python
"""G-CORE-CLEAN 门禁：`core/` 内不许出现客户业务词。

存在理由：
    重构的硬边界是「基座代码不出现客户业务词」（计划书 §10）。这条边界必须能被
    机械判定，否则每个工作包都会各自"看了一遍觉得没问题"。

禁词表位置：
    `scripts/forbidden_terms.json` —— **不在 core 内**。若禁词以字面量定义在 core，
    本门禁扫描 core 时会命中定义本身，形成自指（S2-A 实测过）。

用法：
    python scripts/gate_core_clean.py            # 扫 core/
    python scripts/gate_core_clean.py --path core/tools   # 只扫子目录（调试用）

退出码：0 = CORE-CLEAN；1 = 有命中
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.ports import load_forbidden_terms, scan_forbidden_terms  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="core 解耦门禁")
    parser.add_argument("--path", default="core")
    parser.add_argument("--terms", default=str(REPO / "scripts" / "forbidden_terms.json"))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    target = REPO / args.path
    if not target.exists():
        print(f"[error] 扫描目标不存在: {target}", file=sys.stderr)
        return 2

    terms = load_forbidden_terms(args.terms)
    files = [
        (str(p.relative_to(REPO)), p.read_text(encoding="utf-8", errors="ignore"))
        for p in sorted(target.rglob("*.py"))
    ]
    hits = scan_forbidden_terms(files, terms)

    if hits:
        print(hits)
        print(f"RESULT: FAIL ({len(hits)} hits in {len(files)} files)")
        return 1

    if not args.quiet:
        print(f"CORE-CLEAN ({len(files)} files scanned, {len(terms)} terms)")
    else:
        print("CORE-CLEAN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
