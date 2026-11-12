"""把客户包 manifest 的 `features.event_classification.stages` 装配成可执行降级链。

为什么需要这一层（verifier 抓到的真问题）：
    之前 `features` 只被解析进 `Manifest.features`，**没有任何生产消费者**，
    于是"未来只改 manifest"是一句空话——客户改 yaml 不会产生任何效果。
    这个模块是那个缺失的装配器，`build_classification_chain()` 是唯一入口。

设计取舍：
    - 只装配**已实现**的 kind；未实现的 kind（如 llm）跳过并在返回值里报告，
      不许静默当成"已启用"（否则客户以为开了 LLM，实际没生效）。
    - 客户包里不写凭据：bge 的 base_url/api_key 从**部署侧配置**读（环境变量），
      manifest 只声明"开不开、阈值多少"。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from core.classify import StageSpec, Verdict, run_chain
from core.classify.bge import BgeStage
from core.classify.dictionary import DictionaryStage

#: 已实现的 kind → 工厂（入参是部署侧配置，不是客户包）
_IMPLEMENTED = {"bge", "dictionary"}


@dataclass(frozen=True, slots=True)
class ChainPlan:
    """装配结果：可执行的级 + 未能装配的声明（用于报错/审计）。"""

    stages: tuple[tuple[StageSpec, Callable[[Sequence[Mapping[str, Any]], StageSpec], list[Verdict]]], ...] = ()
    skipped: tuple[str, ...] = ()
    notes: Mapping[str, str] = field(default_factory=dict)


def _deploy_config(kind: str, options: Mapping[str, Any]) -> dict[str, Any]:
    """部署侧配置：优先 manifest 的 options（非敏感项），凭据只从环境变量取。"""
    if kind == "bge":
        return {
            "base_url": os.getenv("CLASSIFY_BASE_URL", ""),
            "api_key": os.getenv("CLASSIFY_API_KEY", ""),
            "timeout": float(options.get("timeout", 30.0)),
        }
    return {}


def build_classification_chain(
    features: Mapping[str, Mapping[str, Any]],
) -> ChainPlan:
    """按客户包声明装配分类降级链。

    `features['event_classification']['stages']` 是**有序数组**；每一级声明
    `kind` / `enabled` / `confidence_threshold` / `options`。

    返回的 `skipped` 里列出"声明了但没实现"的 kind——调用方应把它报进任务事件，
    因为客户会以为它生效了。
    """
    config = features.get("event_classification") or {}
    if not config.get("enabled"):
        return ChainPlan(skipped=(), notes={"event_classification": "disabled"})

    raw_stages = config.get("stages") or []
    specs: list[StageSpec] = []
    runners: list[Callable[[Sequence[Mapping[str, Any]], StageSpec], list[Verdict]]] = []
    skipped: list[str] = []
    notes: dict[str, str] = {}

    for raw in raw_stages:
        kind = str(raw.get("kind") or "")
        if kind not in _IMPLEMENTED:
            # 未实现：跳过但必须报告，不许假装生效
            skipped.append(kind)
            notes[kind] = "not_implemented"
            continue

        spec = StageSpec(
            kind=kind,
            enabled=bool(raw.get("enabled", True)),
            confidence_threshold=(None if raw.get("confidence_threshold") is None
                                  else float(raw["confidence_threshold"])),
            options=dict(raw.get("options") or {}),
        )
        specs.append(spec)

        if kind == "dictionary":
            instance = DictionaryStage()
            runners.append(lambda recs, stage_spec, _i=instance: _i.classify(recs, stage_spec))
        elif kind == "bge":
            deploy = _deploy_config(kind, spec.options)
            instance = BgeStage(**deploy)
            if not deploy["base_url"]:
                notes["bge"] = "base_url_missing_will_degrade"
            runners.append(lambda recs, stage_spec, _i=instance: _i.classify(recs, stage_spec))

    return ChainPlan(
        stages=tuple(zip(specs, runners)),
        skipped=tuple(skipped),
        notes=notes,
    )


def classify_records_with_features(
    records: Sequence[Mapping[str, Any]],
    features: Mapping[str, Mapping[str, Any]],
) -> tuple[list[Verdict], dict[str, int], ChainPlan]:
    """一步到位：装配 + 执行。调用方拿到判定、各级计数、以及装配报告。"""
    plan = build_classification_chain(features)
    verdicts, stats = run_chain(records, plan.stages)
    return verdicts, stats, plan
