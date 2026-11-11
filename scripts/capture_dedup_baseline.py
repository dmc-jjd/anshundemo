#!/usr/bin/env python
"""捕获「旧实现」的去重（事件归并）基线，供 S2 去重剥离做 L1/L2 比对。

为什么需要它：
    去重要从 `app/event_grouping.py` 搬到 `core/tools/dedup.py`，要求**行为不变**。
    但"行为不变"不能靠肉眼判断——必须先有旧实现在真实数据上的产物快照。

用法：
    $py scripts/capture_dedup_baseline.py --out docs/team/baseline/dedup-old.json
    $py scripts/capture_dedup_baseline.py --xlsx 安顺市委10月总数据.xlsx --sheet 3 --scope negative_or_warning

产出（规范化后可逐字段比对）：
    - 输入记录数、筛选后记录数
    - 事件组数、每组的成员 id（排序后）
    - 每条记录的相似度分数（保留 6 位）
    - borderline 候选对
    - 以上全部内容的 sha256（作为单值门禁）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schemas import TaskState  # noqa: E402
from app.storage import Store  # noqa: E402
from app.tool import filter_records, group_events, import_records  # noqa: E402
from app.tool_executor import RunContext  # noqa: E402


def canonical(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build(xlsx: Path, sheet: int, scope: str, threshold: float, workdir: Path) -> dict:
    store = Store(workdir)
    task_id = "baseline-dedup"
    store.put_task(TaskState(id=task_id, kind="report", phase="processing"))
    ctx = RunContext(store, task_id)

    imported = import_records({"path": str(xlsx), "sheet_index": sheet}, ctx)
    if imported.status == "error":
        raise SystemExit(f"import_records failed: {imported.error_code}")
    records = store.get_artifact(imported.data_ref)["records"]

    filtered = filter_records({"records_ref": imported.data_ref, "scope": scope}, ctx)
    if filtered.status == "error":
        raise SystemExit(f"filter_records failed: {filtered.error_code}")
    selected = store.get_artifact(filtered.data_ref)["records"]

    grouped = group_events({"records_ref": filtered.data_ref, "threshold": threshold}, ctx)
    if grouped.status == "error":
        raise SystemExit(f"group_events failed: {grouped.error_code}")
    result = store.get_artifact(grouped.data_ref)

    groups = [
        {"id": g["id"], "title": g["title"], "member_ids": sorted(g["member_ids"])}
        for g in result["groups"]
    ]
    groups.sort(key=lambda g: (len(g["member_ids"]), g["id"]), reverse=True)

    return {
        "kind": "dedup-baseline",
        "source": {"xlsx": xlsx.name, "sheet": sheet, "scope": scope, "threshold": threshold},
        "counts": {
            "imported": len(records),
            "selected": len(selected),
            "group_count": len(groups),
            "multi_member_groups": sum(1 for g in groups if len(g["member_ids"]) > 1),
        },
        "groups": groups,
        "member_scores": dict(sorted(result["member_scores"].items())),
        "borderline_candidates": result["borderline_candidates"],
        "method": result["method"],
    }


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="捕获旧实现去重基线")
    parser.add_argument("--xlsx", default=str(repo / "安顺市委10月总数据.xlsx"))
    parser.add_argument("--sheet", type=int, default=3)
    parser.add_argument("--scope", default="negative_or_warning")
    parser.add_argument("--threshold", type=float, default=0.65)
    parser.add_argument("--out", required=True)
    parser.add_argument("--workdir", default="")
    args = parser.parse_args()

    xlsx = Path(args.xlsx)
    if not xlsx.exists():
        print(f"[error] 输入不存在: {xlsx}", file=sys.stderr)
        return 2

    if args.workdir:
        Path(args.workdir).mkdir(parents=True, exist_ok=True)
    # ignore_cleanup_errors：Store 持有 sqlite 连接，Windows 上临时目录删不掉，
    # 这是清理阶段的问题，不应让已算好的基线丢失。
    with tempfile.TemporaryDirectory(dir=args.workdir or None, ignore_cleanup_errors=True) as tmp:
        payload = build(xlsx, args.sheet, args.scope, args.threshold, Path(tmp))

    digest = hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()
    payload["content_sha256"] = digest

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    counts = payload["counts"]
    print(f"imported={counts['imported']} selected={counts['selected']} "
          f"groups={counts['group_count']} multi={counts['multi_member_groups']}")
    print(f"content_sha256={digest}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
