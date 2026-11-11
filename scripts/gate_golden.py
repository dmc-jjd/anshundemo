#!/usr/bin/env python
"""G-GOLDEN 门禁：S2 期间「行为不变」的唯一判据。

为什么要它：
    S2 的每个工作包都在搬代码，唯一能证明"没改行为"的是：同一份真实数据跑完整条
    确定性流水线，产物规范化哈希与基线逐字符相等。把这段逻辑固化成脚本，而不是让
    每个工作包各粘一份 heredoc —— 否则命令一漂移，哈希就不可比（实测过：少写一个
    separators 参数，G-SPECS 就算出完全不同的值）。

覆盖 13 段：import / filter×6 / metrics / locality / classify / cluster / materials / groups

用法：
    python scripts/gate_golden.py            # 单次
    python scripts/gate_golden.py --twice    # 连跑两次并断言同值（防随机性）

退出码：0 = 与基线相等；1 = 不等或两次不同值
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.schemas import TaskState  # noqa: E402
from app.storage import Store  # noqa: E402
from app.tool import (  # noqa: E402
    calculate_metrics,
    classify_records,
    cluster_event_themes,
    filter_records,
    group_events,
    import_records,
    resolve_locality,
    select_materials,
)
from app.tool_executor import RunContext  # noqa: E402

EXPECTED = "3f59d6c694783bb9b7fccd2c173c6876f2fd20defdaa368cc249e9b6113f3a90"
EXPECTED_COUNTS = (28789, 3914, 1990)


def canon(payload) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def run_once(xlsx: Path) -> tuple[tuple[int, int, int], str]:
    workdir = Path(tempfile.mkdtemp(prefix="golden-", dir=str(REPO / ".conda")))
    store = Store(workdir)
    store.put_task(TaskState(id="g", kind="report", phase="processing"))
    ctx = RunContext(store, "g")
    parts: dict[str, str] = {}

    imp = import_records({"path": str(xlsx), "sheet_index": 3}, ctx)
    parts["import"] = canon(store.get_artifact(imp.data_ref))

    flt = filter_records({"records_ref": imp.data_ref, "scope": "negative_or_warning"}, ctx)
    parts["filter"] = canon(store.get_artifact(flt.data_ref))

    for scope in ("positive", "neutral", "negative", "warning"):
        r = filter_records({"records_ref": imp.data_ref, "scope": scope}, ctx)
        parts["filter_" + scope] = canon(store.get_artifact(r.data_ref))

    met = calculate_metrics({"records_ref": flt.data_ref}, ctx)
    parts["metrics"] = canon(store.get_artifact(met.data_ref))

    level = next(iter(store.get_artifact(met.data_ref)["platform"]))
    r = filter_records({"records_ref": imp.data_ref, "scope": "media", "media_level": level}, ctx)
    parts["filter_media"] = canon(store.get_artifact(r.data_ref))

    loc = resolve_locality({"records_ref": flt.data_ref}, ctx)
    parts["locality"] = canon(store.get_artifact(loc.data_ref))

    cls = classify_records({"records_ref": flt.data_ref}, ctx)
    parts["classify"] = canon(store.get_artifact(cls.data_ref))

    clu = cluster_event_themes({"records_ref": flt.data_ref}, ctx)
    parts["cluster"] = canon(store.get_artifact(clu.data_ref))

    mat = select_materials({"records_ref": flt.data_ref, "limit": 10}, ctx)
    parts["materials"] = canon(store.get_artifact(mat.data_ref))

    grp = group_events({"records_ref": flt.data_ref, "threshold": 0.65}, ctx)
    parts["groups"] = canon(store.get_artifact(grp.data_ref))

    counts = (
        len(store.get_artifact(imp.data_ref)["records"]),
        len(store.get_artifact(flt.data_ref)["records"]),
        len(store.get_artifact(grp.data_ref)["groups"]),
    )
    shutil.rmtree(workdir, ignore_errors=True)
    return counts, canon(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="S2 golden 门禁")
    parser.add_argument("--twice", action="store_true", help="连跑两次并断言同值")
    parser.add_argument("--xlsx", default="")
    args = parser.parse_args()

    xlsx = Path(args.xlsx) if args.xlsx else next(p for p in REPO.glob("*.xlsx") if "10" in p.name)
    if not xlsx.exists():
        print(f"[error] 输入不存在: {xlsx}", file=sys.stderr)
        return 2

    counts, digest = run_once(xlsx)
    print("COUNTS", *counts)
    print("S2-GOLDEN", digest)

    ok = digest == EXPECTED and counts == EXPECTED_COUNTS

    if args.twice:
        counts2, digest2 = run_once(xlsx)
        print("COUNTS-2ND", *counts2)
        print("S2-GOLDEN-2ND", digest2)
        if digest2 != digest:
            print("RESULT: FAIL (两次运行不同值，存在非确定性)")
            return 1
        print("DETERMINISM: OK")

    if ok:
        print("RESULT: PASS")
        return 0
    print(f"RESULT: FAIL (expected {EXPECTED} {EXPECTED_COUNTS})")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
