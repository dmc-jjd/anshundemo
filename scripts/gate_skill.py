#!/usr/bin/env python
"""G-SKILL 门禁：固定输入经 `detect_style` 产出的 `style_detection` packet 规范化哈希与基线逐字符相等。

为什么它必须先录基线再搬代码：
    245 个测试里只有 1 个用例弱断言 skill 产物（任务分解-S4 §0.6），唯一能证明"搬完还是同一套判读"
    的是同一份固定输入产出的工件哈希。先改代码后录基线，基线就是自己给自己打分。

三条口径（任一条被"优化"都会改变哈希）：
    1. 哈希对象 = 整个 packet，口径逐字等于 `app/storage.py:23`：
       `sha256(json.dumps(packet, ensure_ascii=False, sort_keys=True, default=str).encode())`。
       **不传 separators**——实测那会算出完全不同的值（§1 口径 1）。
    2. `ref` 是同一哈希的前 20 位（`app/storage.py:24` `aid=f'{kind}-{digest[:20]}'`），
       故本脚本顺带做内部一致性校验（免费的检验）。
    3. 输入必须是字面量（§0.7 F2）：fixture 里 `draft.content_hash` 固定为 `'skill-gate-v1'`。
       禁止用 `save_draft`/`fixture()` 造 draft——`DraftVersion` 内含 uuid4
       （`app/structured_writer.py:83/87`），会把框架固有不确定性误判成改码。

判据来源：
    `docs/team/baseline/skill-S4.json`（脚本内不重复硬编码哈希，避免双份漂移）。
    录一次后只读；`--record` 目标已存在时拒绝覆盖（除非 `--force`）——覆盖 = 门禁自证循环。

用法：
    python scripts/gate_skill.py --record    # 录基线（存在即拒绝）
    python scripts/gate_skill.py             # 比对
    python scripts/gate_skill.py --twice     # 连跑两次并断言同值

退出码：0 PASS；1 FAIL（含两次不同值）；2 输入或基线缺失
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app import style_skill  # noqa: E402  （只依赖 app 层；core.skills 落地前本尺子就要能跑）
from app.storage import Store  # noqa: E402

FIXTURE = REPO / "docs" / "team" / "baseline" / "skill-S4-fixture.json"
BASELINE = REPO / "docs" / "team" / "baseline" / "skill-S4.json"
TARGET = "style_detection"
CORE_KEYS = ("packet_sha256", "ref", "packet_bytes", "documents", "counts", "labels")


def _canonical(packet: dict) -> bytes:
    # 逐字对齐 app/storage.py:23；不传 separators。
    return json.dumps(packet, ensure_ascii=False, sort_keys=True, default=str).encode()


def run_once() -> dict:
    """跑一次固定输入，返回基线与比对共用的可观测量。无副作用，可被测试直接复用。"""
    data = json.loads(FIXTURE.read_text(encoding="utf-8-sig"))
    workdir = Path(tempfile.mkdtemp(prefix="skill-", dir=str(REPO / ".conda")))
    try:
        store = Store(workdir)
        ref, packet = style_skill.detect_style(store, "r", data["draft"], data["fields"])
    finally:
        gc.collect()  # sqlite3 连接靠 GC 回收；Win 下不回收则 rmtree 静默失败，临时目录越积越多
        shutil.rmtree(workdir, ignore_errors=True)

    raw = _canonical(packet)
    labels: dict[str, list] = {}
    for candidate in packet["semantic_candidates"]:
        labels.setdefault(candidate["kind"], candidate["allowed_labels"])
    counts = {kind: 0 for kind in labels}
    for candidate in packet["semantic_candidates"]:
        counts[candidate["kind"]] += 1
    counts["candidates"] = len(packet["semantic_candidates"])
    counts["project_findings"] = len(packet["project_findings"])
    return {
        "packet_sha256": hashlib.sha256(raw).hexdigest(),
        "ref": ref,
        "packet_bytes": len(raw),
        "skill": {key: packet["skill"][key] for key in ("name", "commit", "sha256")},
        "documents": list(packet["documents"]),
        "counts": counts,
        "labels": labels,
    }


def report(observed: dict) -> None:
    counts = observed["counts"]
    kinds = [key for key in counts if key not in ("candidates", "project_findings")]
    pairs = [f"{key}={counts[key]}" for key in kinds]
    pairs += [f"candidates={counts['candidates']}", f"findings={counts['project_findings']}"]
    print(f"{'G-SKILL':<14}{observed['packet_sha256']}")
    print(f"{'G-SKILL-REF':<14}{observed['ref']}")
    print(f"{'G-SKILL-SKILL':<14}{observed['skill']['sha256']}")
    print("G-SKILL-COUNTS", " ".join(pairs))
    print(f"{'G-SKILL-DOCS':<14}{','.join(observed['documents'])}")


def compare(observed: dict, baseline: dict) -> list[str]:
    """逐项比对——只比总哈希会给不出归因。"""
    problems: list[str] = []
    for key in CORE_KEYS:
        if observed[key] != baseline.get(key):
            problems.append(f"{key}: expected {baseline.get(key)} got {observed[key]}")
    for key in ("name", "commit", "sha256"):
        want = (baseline.get("skill") or {}).get(key)
        if observed["skill"][key] != want:
            problems.append(f"skill.{key}: expected {want} got {observed['skill'][key]}")
    return problems


def record(observed: dict, force: bool) -> int:
    if BASELINE.exists() and not force:
        print(f"[error] 基线已存在，拒绝覆盖: {BASELINE}（--force 才覆盖）", file=sys.stderr)
        return 2
    data = {
        "fixture": FIXTURE.relative_to(REPO).as_posix(),
        "packet_sha256": observed["packet_sha256"],
        "ref": observed["ref"],
        "packet_bytes": observed["packet_bytes"],
        "skill": observed["skill"],
        "documents": observed["documents"],
        "counts": observed["counts"],
        "labels": observed["labels"],
        "python": sys.version.split()[0],
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("RECORDED", BASELINE.relative_to(REPO).as_posix(), "force" if force else "")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="S4 技能检测门禁（style_detection 工件哈希）")
    parser.add_argument("--record", action="store_true", help="录基线")
    parser.add_argument("--force", action="store_true", help="配合 --record 覆盖已存在基线")
    parser.add_argument("--twice", action="store_true", help="连跑两次并断言同值")
    args = parser.parse_args()

    if not FIXTURE.exists():
        print(f"[error] 固定输入缺失: {FIXTURE}", file=sys.stderr)
        return 2

    observed = run_once()
    report(observed)

    expected_ref = f"{TARGET}-{observed['packet_sha256'][:20]}"
    problems = [] if observed["ref"] == expected_ref else [
        f"ref: expected {expected_ref} got {observed['ref']}"]

    if args.record:
        if problems:
            for line in problems:
                print("MISMATCH", line)
            print(f"RESULT: FAIL ({len(problems)} mismatches)")
            return 1
        rc = record(observed, args.force)
        if rc:
            return rc
        print("RESULT: PASS")
        return 0

    if not BASELINE.exists():
        print(f"[error] 基线缺失: {BASELINE}（先跑 --record）", file=sys.stderr)
        return 2
    baseline = json.loads(BASELINE.read_text(encoding="utf-8-sig"))

    if args.twice:
        second = run_once()
        print(f"{'G-SKILL-2ND':<14}{second['packet_sha256']}")
        if second["packet_sha256"] != observed["packet_sha256"]:
            print("RESULT: FAIL (非确定性)")
            return 1
        print("DETERMINISM: OK")

    problems += compare(observed, baseline)
    if problems:
        for line in problems:
            print("MISMATCH", line)
        print(f"RESULT: FAIL ({len(problems)} mismatches)")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
