#!/usr/bin/env python
"""G-PROMPTS / G-PROMPTS-ORDER 门禁：提示词四个数据对象的规范化哈希与基线逐字符相等。

为什么它必须先录基线再搬代码：
    现有 259 个用例里没有一条能证明「32 条提示词一个字节都没变」——最强的
    `test_instruction_literals_only_live_in_agent_registry` 只证明字面量不在别处，
    其余全是弱子串断言（任务分解-S5 §0.6）。S5 搬的是纯文本，搬完源文件本身变了，
    「文件内容对比」不再成立；唯一判据只剩「外置前后同一份规范化哈希」。

口径（四条，任一条被"优化"都会改变哈希）：
    1. 规范化口径 = 项目主流 canon，逐字等于 `app/storage.py:23`（`Store.put_artifact`）
       与 `gate_skill.py` / `gate_golden.py`：
       `sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode())`。
       **不传 separators**——那是 `gate_specs` 一家的口径，实测会算出另一个值。
    2. 四个对象一个 JSON：`AGENT_PROMPTS` / `AGENT_DEFINITIONS` / `TEMPLATE_POLICY` /
       `REPORT_PROMPT_PROFILES`，键名逐字如上。`DEFAULT_PROMPT_PROFILE` 不进哈希
       （裸字符串，由 `G-PROMPTS-COUNT ... default=` 一行单独钉住）。
    3. `default=str` 不是可选项：`AGENT_DEFINITIONS` 的值是 `AgentDefinition` frozen
       dataclass，只有它能进 JSON；副作用是哈希同时钉住了类型（改成普通 dict 立刻红，
       而 `model_client.py:73` 用属性访问，dict 会 AttributeError——正是我们要的）。
    4. 基线只读：`docs/team/baseline/prompts-S5.json` 在任何 S5 编辑之前由 `--record`
       生成一次，此后不得覆盖（覆盖 = 门禁自证循环）。

为什么还要 G-PROMPTS-ORDER：
    `sort_keys=True` 对**键序**天生失明（§0.8 两个探针实测 PASS）。而 `TEMPLATE_POLICY`
    的键序是语义——`template_review.py:39` 把 `deepcopy(TEMPLATE_POLICY)` 塞进 policy，
    最终由 `model_client.py:75` 的 `json.dumps(payload, ensure_ascii=False)`（**不排序**）
    序列化进模型 user 消息。键序变 = 发给模型的文本变 = 模型输出变。
    故另设 order-sensitive 哈希 + 六层字面键序（顶层/嵌套），四条独立钉住。

判据来源：
    `docs/team/baseline/prompts-S5.json`（脚本内不重复硬编码哈希，避免双份漂移）。

用法：
    python scripts/gate_prompts.py --record    # 录基线（存在即拒绝，--force 才覆盖）
    python scripts/gate_prompts.py             # 比对
    python scripts/gate_prompts.py --twice     # 连跑两次并断言同值

退出码：0 PASS；1 FAIL（含两次不同值）；2 输入或基线缺失
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# 只依赖 app 层：core.prompts 落地前本尺子就要能跑（同 gate_skill.py 不 import core.skills 的纪律）。
from app import agent  # noqa: E402
from app import reviewers  # noqa: E402

BASELINE = REPO / "docs" / "team" / "baseline" / "prompts-S5.json"
BUNDLE_KEYS = ("AGENT_PROMPTS", "AGENT_DEFINITIONS", "TEMPLATE_POLICY", "REPORT_PROMPT_PROFILES")
COUNT_KEYS = ("prompts", "roles", "policy_top", "profiles", "default")
ORDER_HASH_KEYS = ("policy_sha256_unsorted", "all_sha256_unsorted")
ORDER_KEY_KEYS = ("prompt_keys", "role_keys", "policy_keys",
                  "recommendations_keys", "top10_keys", "review_controls_keys")
# 六行指纹表（任务分解-S5 §0.5）。None = 用 prompt_fingerprint 的默认 prefixes。
FINGERPRINT_ARGS = (
    ("default", None),
    ("historical_researcher", ("historical_researcher.",)),
    ("writer.analysis", ("writer.analysis",)),
    ("writer.outlook", ("writer.outlook", "historical_researcher.")),
    ("writer.general", ("writer.general",)),
)


def canonical(obj) -> bytes:
    """逐字对齐 app/storage.py:23；不传 separators。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode()


def unsorted_bytes(obj) -> bytes:
    """order-sensitive 口径：sort_keys=False（键序进哈希）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=False, default=str).encode()


def digest(obj) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def hash_bundle(mapping) -> str:
    """纯函数：吃 `{四对象名: 值}`（允许子集/脏值），返回规范化哈希。负向探针复用它。"""
    return digest(mapping)


def order_hash(mapping) -> str:
    """纯函数：同上但键序敏感。"""
    return hashlib.sha256(unsorted_bytes(mapping)).hexdigest()


def bundle() -> dict:
    return {key: getattr(agent, key) for key in BUNDLE_KEYS}


def run_once() -> dict:
    """测一次，返回基线与比对共用的可观测量。无副作用，可被测试直接复用。"""
    data = bundle()
    policy = agent.TEMPLATE_POLICY
    return {
        "prompts_sha256": hash_bundle(data),
        "parts": {key: hash_bundle(value) for key, value in data.items()},
        "counts": {
            "prompts": len(agent.AGENT_PROMPTS),
            "roles": len(agent.AGENT_DEFINITIONS),
            "policy_top": len(policy),
            "profiles": len(agent.REPORT_PROMPT_PROFILES),
            "default": agent.DEFAULT_PROMPT_PROFILE,
        },
        "order": {
            "policy_sha256_unsorted": order_hash(policy),
            "all_sha256_unsorted": order_hash(data),
            "prompt_keys": list(agent.AGENT_PROMPTS),
            "role_keys": list(agent.AGENT_DEFINITIONS),
            "policy_keys": list(policy),
            "recommendations_keys": list(policy["recommendations"]),
            "top10_keys": list(policy["top10"]),
            "review_controls_keys": list(policy["review_controls"]),
        },
        "fingerprints": {
            name: (agent.prompt_fingerprint() if prefixes is None
                   else agent.prompt_fingerprint(agent.DEFAULT_PROMPT_PROFILE, prefixes))
            for name, prefixes in FINGERPRINT_ARGS
        },
        "review_policy": reviewers.review_policy(agent.DEFAULT_PROMPT_PROFILE),
        "skill_sha256": reviewers.skill_context()["sha256"],
    }


def report(observed: dict) -> None:
    """11 行数据面（--twice 再补 3 行）；列宽 16 + 两个空格，不用 tab。"""
    counts = observed["counts"]
    line = lambda label, value: print(f"{label:<16}  {value}")  # noqa: E731
    line("G-PROMPTS", observed["prompts_sha256"])
    line("G-PROMPTS-PARTS", " ".join(observed["parts"][key] for key in BUNDLE_KEYS))
    line("G-PROMPTS-COUNT", " ".join(f"{key}={counts[key]}" for key in COUNT_KEYS))
    line("G-PROMPTS-ORDER", observed["order"]["policy_sha256_unsorted"])
    line("G-PROMPTS-ALLORD", observed["order"]["all_sha256_unsorted"])
    labels = ("G-PROMPT-FP", "G-PROMPT-FP-HIST", "G-PROMPT-FP-ANA",
              "G-PROMPT-FP-OUT", "G-PROMPT-FP-GEN")
    for label, (name, _) in zip(labels, FINGERPRINT_ARGS):
        line(label, observed["fingerprints"][name])
    line("G-PROMPT-POLICY", observed["review_policy"])


def _key_problem(name: str, want, got) -> list[str]:
    """键序漂移的归因：先报增删，纯顺序变化单独报。"""
    if want == got:
        return []
    want = list(want or [])
    got = list(got or [])
    missing = [key for key in want if key not in got]
    extra = [key for key in got if key not in want]
    problems = []
    if missing:
        problems.append(f"order.{name}: missing keys {missing}")
    if extra:
        problems.append(f"order.{name}: unexpected keys {extra}")
    if not missing and not extra:
        problems.append(f"order.{name}: key ORDER changed {want} -> {got}")
    return problems


def compare(observed: dict, baseline: dict) -> list[str]:
    """逐项比对——只比总哈希会给不出归因。"""
    problems: list[str] = []
    if observed["prompts_sha256"] != baseline.get("prompts_sha256"):
        problems.append(f"prompts_sha256: expected {baseline.get('prompts_sha256')} "
                        f"got {observed['prompts_sha256']}")
    for key in BUNDLE_KEYS:
        want = (baseline.get("parts") or {}).get(key)
        if observed["parts"][key] != want:
            problems.append(f"part {key}: expected {want} got {observed['parts'][key]}")
    for key in COUNT_KEYS:
        want = (baseline.get("counts") or {}).get(key)
        if observed["counts"][key] != want:
            problems.append(f"counts.{key}: expected {want} got {observed['counts'][key]}")
    for key in ORDER_HASH_KEYS:
        want = (baseline.get("order") or {}).get(key)
        if observed["order"][key] != want:
            problems.append(f"order.{key}: expected {want} got {observed['order'][key]}")
    for key in ORDER_KEY_KEYS:
        problems += _key_problem(key, (baseline.get("order") or {}).get(key),
                                 observed["order"][key])
    for name, _ in FINGERPRINT_ARGS:
        want = (baseline.get("fingerprints") or {}).get(name)
        if observed["fingerprints"][name] != want:
            problems.append(f"fingerprint {name}: expected {want} "
                            f"got {observed['fingerprints'][name]}")
    for key in ("review_policy", "skill_sha256"):
        if observed[key] != baseline.get(key):
            problems.append(f"{key}: expected {baseline.get(key)} got {observed[key]}")
    return problems


def record(observed: dict, force: bool) -> int:
    if BASELINE.exists() and not force:
        print(f"[error] 基线已存在，拒绝覆盖: {BASELINE}（--force 才覆盖）", file=sys.stderr)
        return 2
    data = {
        "canon": "sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,default=str).encode())",
        "prompts_sha256": observed["prompts_sha256"],
        "parts": observed["parts"],
        "counts": observed["counts"],
        "order": observed["order"],
        "fingerprints": observed["fingerprints"],
        "review_policy": observed["review_policy"],
        "skill_sha256": observed["skill_sha256"],
        "python": sys.version.split()[0],
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("RECORDED", BASELINE.relative_to(REPO).as_posix() + (" (force)" if force else ""))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="S5 提示词门禁（四个数据对象的规范化哈希）")
    parser.add_argument("--record", action="store_true", help="录基线")
    parser.add_argument("--force", action="store_true", help="配合 --record 覆盖已存在基线")
    parser.add_argument("--twice", action="store_true", help="连跑两次并断言同值")
    args = parser.parse_args()

    observed = run_once()
    report(observed)

    if args.record:
        rc = record(observed, args.force)
        if rc:
            return rc
        print("RESULT: PASS")
        return 0

    baseline = load_baseline_or_report()
    if baseline is None:
        return 2
    problems = compare(observed, baseline)

    if args.twice:
        second = run_once()
        print(f"{'G-PROMPTS-2ND':<16}  {second['prompts_sha256']}")
        if second["prompts_sha256"] != observed["prompts_sha256"]:
            print("RESULT: FAIL (非确定性)")
            return 1
        print("DETERMINISM: OK")

    if problems:
        for line in problems:
            print("MISMATCH", line)
        print(f"RESULT: FAIL ({len(problems)} mismatches)")
        return 1
    print("RESULT: PASS")
    return 0


def load_baseline_or_report():
    """基线缺失 → 打 stderr 并返回 None（退出码 2 由 main 给）。"""
    if not BASELINE.exists():
        print(f"[error] 基线缺失: {BASELINE}（先跑 --record）", file=sys.stderr)
        return None
    return json.loads(BASELINE.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    raise SystemExit(main())
