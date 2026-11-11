#!/usr/bin/env python
"""G-CHARTS 门禁：5 张 Pillow 图的 PNG sha256 与基线逐字节相等。

为什么它必须先录基线再搬代码：
    它是"图表数据搬到客户包里、画出来的字节没变"的唯一判据。先改代码后录基线，
    基线就是自己给自己打分。

判据来源：
    `docs/team/baseline/charts-S3.json`（脚本内不重复硬编码哈希，避免双份漂移）。
    录一次后只读；`--record` 目标已存在时拒绝覆盖（除非 `--force`）。

用法：
    python scripts/gate_charts.py --record    # 录基线（存在即拒绝）
    python scripts/gate_charts.py             # 比对
    python scripts/gate_charts.py --twice     # 连跑两次并断言同值

退出码：0 PASS；1 FAIL（含两次不同值）；2 输入或基线缺失
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import PIL  # noqa: E402
from app.schemas import TaskState  # noqa: E402
from app.storage import Store  # noqa: E402
from app.tool import (  # noqa: E402
    calculate_metrics,
    cluster_event_themes,
    filter_records,
    import_records,
    render_chart,
    resolve_locality,
)
from app.tool_executor import RunContext  # noqa: E402

# 显式文件名：仓库里有两个含 "10" 的 xlsx，glob 猜文件属侥幸（任务分解 §0.7 F4）。
DEFAULT_XLSX = "安顺市委10月总数据.xlsx"
SHEET_INDEX = 3
CHART_TYPES = ("sentiment", "daily", "platform", "theme", "locality")
BASELINE = REPO / "docs" / "team" / "baseline" / "charts-S3.json"
FONT = Path("C:/Windows/Fonts/msyh.ttc")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def composite(charts: dict[str, dict]) -> str:
    payload = {kind: item["sha256"] for kind, item in charts.items()}
    return _sha(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def run_once(xlsx: Path) -> tuple[tuple[int, int], dict[str, dict]]:
    workdir = Path(tempfile.mkdtemp(prefix="charts-", dir=str(REPO / ".conda")))
    try:
        store = Store(workdir)
        store.put_task(TaskState(id="g", kind="report", phase="processing"))
        ctx = RunContext(store, "g")

        imp = import_records({"path": str(xlsx), "sheet_index": SHEET_INDEX}, ctx)
        flt = filter_records({"records_ref": imp.data_ref, "scope": "negative_or_warning"}, ctx)
        met = calculate_metrics({"records_ref": flt.data_ref}, ctx)
        clu = cluster_event_themes({"records_ref": flt.data_ref}, ctx)
        loc = resolve_locality({"records_ref": flt.data_ref}, ctx)
        counts = (
            len(store.get_artifact(imp.data_ref)["records"]),
            len(store.get_artifact(flt.data_ref)["records"]),
        )

        charts: dict[str, dict] = {}
        for kind in CHART_TYPES:
            arguments: dict = {"chart_type": kind, "metrics_ref": met.data_ref}
            if kind == "theme":
                arguments["cluster_ref"] = clu.data_ref
            elif kind == "locality":
                arguments["locality_ref"] = loc.data_ref
            result = render_chart(arguments, ctx)
            payload = store.get_artifact(result.data_ref)
            png = base64.b64decode(payload["png_base64"])
            charts[kind] = {
                "sha256": _sha(png),
                "bytes": len(png),
                "status": result.status,
                "title": payload["title"],
            }
        return counts, charts
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def report(counts: tuple[int, int], charts: dict[str, dict]) -> None:
    print("COUNTS", *counts)
    for kind in CHART_TYPES:
        item = charts[kind]
        print(f"CHART {kind:<10}{item['sha256']} {item['bytes']} {item['status']}")
    print("CHARTS-COMPOSITE", composite(charts))


def record(xlsx: Path, counts: tuple[int, int], charts: dict[str, dict], force: bool) -> int:
    if BASELINE.exists() and not force:
        print(f"[error] 基线已存在，拒绝覆盖: {BASELINE}（--force 才覆盖）", file=sys.stderr)
        return 2
    data = {
        "input": xlsx.name,
        "sheet_index": SHEET_INDEX,
        "counts": list(counts),
        "charts": charts,
        "composite": composite(charts),
        "pillow": PIL.__version__,
        "python": sys.version.split()[0],
        "font_sha256": _sha(FONT.read_bytes()) if FONT.exists() else None,
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("RECORDED", BASELINE.relative_to(REPO), "force" if force else "")
    return 0


def compare(counts: tuple[int, int], charts: dict[str, dict], baseline: dict) -> list[str]:
    problems: list[str] = []
    if baseline.get("counts") != list(counts):
        problems.append(f"counts: expected {baseline.get('counts')} got {list(counts)}")
    expected = baseline.get("charts") or {}
    for kind in CHART_TYPES:
        want, got = expected.get(kind), charts[kind]
        if not want:
            problems.append(f"{kind}: baseline missing")
            continue
        for key in ("sha256", "bytes", "status"):
            if want.get(key) != got[key]:
                problems.append(f"{kind}.{key}: expected {want.get(key)} got {got[key]}")
    if baseline.get("composite") != composite(charts):
        problems.append(f"composite: expected {baseline.get('composite')} got {composite(charts)}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="S3 图表 PNG 门禁")
    parser.add_argument("--xlsx", default="", help="输入 xlsx（默认显式总数据文件名）")
    parser.add_argument("--record", action="store_true", help="录基线")
    parser.add_argument("--force", action="store_true", help="配合 --record 覆盖已存在基线")
    parser.add_argument("--twice", action="store_true", help="连跑两次并断言同值")
    args = parser.parse_args()

    xlsx = Path(args.xlsx) if args.xlsx else REPO / DEFAULT_XLSX
    if not xlsx.exists():
        print(f"[error] 输入不存在: {xlsx}", file=sys.stderr)
        return 2

    counts, charts = run_once(xlsx)
    report(counts, charts)

    if args.record:
        rc = record(xlsx, counts, charts, args.force)
        if rc:
            return rc
        print("RESULT: PASS")
        return 0

    if not BASELINE.exists():
        print(f"[error] 基线缺失: {BASELINE}（先跑 --record）", file=sys.stderr)
        return 2
    baseline = json.loads(BASELINE.read_text(encoding="utf-8-sig"))

    if args.twice:
        counts2, charts2 = run_once(xlsx)
        print("CHARTS-COMPOSITE-2ND", composite(charts2))
        if (counts2, charts2) != (counts, charts):
            print("RESULT: FAIL (两次运行不同值，存在非确定性)")
            return 1
        print("DETERMINISM: OK")

    problems = compare(counts, charts, baseline)
    if problems:
        for line in problems:
            print("MISMATCH", line)
        print(f"RESULT: FAIL ({len(problems)} mismatches)")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
