"""可插拔分类能力：多级降级链的基座契约。

为什么要有这一层：
    现在 `classify_records` 只读源表的「事件分类」列（它不是分类器），而
    `cluster_event_themes` 是词典打分——两个语义不同的东西被当成一个"分类能力"用。
    客户想要的是一条**有序降级链**：

        BGE(微调模型) → 词典 → LLM → 人工

    前一级判不出（置信度低 / 判为新簇）才进下一级。链由客户包 manifest 声明，
    基座只负责按顺序执行与合流，不认识任何具体客户。

本模块只管契约与合流；具体实现（bge/llm/dictionary）各自一个模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

#: 判定来源，写进产物便于审计
SOURCE_BGE = "bge"
SOURCE_DICTIONARY = "dictionary"
SOURCE_LLM = "llm"
SOURCE_UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class Verdict:
    """单条记录的判定结果。"""

    record_id: str
    category: str | None = None
    confidence: float = 0.0
    source: str = SOURCE_UNRESOLVED
    #: 该判定是否"边界"——需要交给下一级。None 表示由外层按阈值判断
    borderline: bool | None = None
    reason: str = ""

    @property
    def decided(self) -> bool:
        return bool(self.category) and self.source != SOURCE_UNRESOLVED


@dataclass(frozen=True, slots=True)
class StageSpec:
    """一级判定的声明（来自 manifest 的 features.event_classification.stages[]）。"""

    kind: str                      # bge | dictionary | llm
    enabled: bool = True
    confidence_threshold: float | None = None   # 低于此值判为边界
    options: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class ClassifyStage(Protocol):
    """一级判定器。实现方只负责"我能判的判掉，判不了的标边界"。"""

    kind: str

    def classify(self, records: Sequence[Mapping[str, Any]], spec: StageSpec) -> list[Verdict]: ...


def _rid(record: Mapping[str, Any], index: int = -1) -> str:
    """把记录 id 规范成字符串（唯一口径）。

    早先 `decided` 用 `str(...)` 作键、`pending` 却用原始 `r["id"]` 过滤，
    于是 int id（Excel 行号是最自然的误用）会静默丢结论并重复调用下一级。

    无 id 的记录**不再静默消失**：给一个可识别的合成键 `__row_<idx>`，
    让判定照常产出，由调用方按前缀识别并转人工（verifier 实证过 3 条→2 条）。
    """
    value = record.get("id")
    if value is None or (isinstance(value, str) and not value.strip()):
        return f"__row_{index}" if index >= 0 else ""
    return str(value)


def run_chain(
    records: Sequence[Mapping[str, Any]],
    stages: Sequence[tuple[StageSpec, Callable[[Sequence[Mapping[str, Any]], StageSpec], list[Verdict]]]],
) -> tuple[list[Verdict], dict[str, int]]:
    """按声明顺序跑降级链，返回（最终判定, 各级贡献计数）。

    规则：
    - 只把"还没判出"的记录喂给下一级（不重复花钱、不重复计算）
    - `enabled: false` 的级直接跳过
    - 全部跑完后仍未判出的，统一标 `unresolved`（由调用方转人工）
    - 后一级**不许覆盖**前一级已判出的结果（这就是"降级"而非"投票"）

    为什么不用投票/融合：客户的要求是"边界 case 才往下走"，投票会让词典改写
    BGE 的判断，与需求相反。
    """
    #: 用「(记录, 规范 id)」配对，保证无 id 记录也能被回填而不是静默消失
    pairs: list[tuple[Mapping[str, Any], str]] = [(_r, _rid(_r, i)) for i, _r in enumerate(records)]
    decided: dict[str, Verdict] = {}
    #: 以「第几级:kind」为键，避免同 kind 出现两级时计数互相覆盖
    stats: dict[str, int] = {}
    duplicates = 0
    seen: set[str] = set()
    for _, rid in pairs:
        if rid in seen:
            duplicates += 1
        seen.add(rid)

    for index, (spec, runner) in enumerate(stages):
        key = f"{index}:{spec.kind}"
        pending = [_r for _r, rid in pairs if rid not in decided]
        if not pending or not spec.enabled:
            stats[key] = 0
            continue

        verdicts = runner(pending, spec)
        taken = 0
        for verdict in verdicts:
            if not verdict.decided:
                continue
            rid = str(verdict.record_id)
            if rid in decided:                    # 前一级已判出，不覆盖
                continue
            if verdict.borderline:                # 显式边界：留给下一级
                continue
            if spec.confidence_threshold is not None and verdict.confidence < spec.confidence_threshold:
                continue
            decided[rid] = verdict
            taken += 1
        stats[key] = taken

    for _r, rid in pairs:
        if rid and rid not in decided:
            reason = "missing_id" if rid.startswith("__row_") else "all_stages_borderline"
            decided[rid] = Verdict(record_id=rid, source=SOURCE_UNRESOLVED, reason=reason)

    if duplicates:
        # 重复 id 不再静默吞并：调用方需要知道有几条被判成同一条
        stats["__duplicate_ids"] = duplicates

    ordered = [decided[rid] for _, rid in pairs if rid in decided]
    return ordered, stats
