"""可插拔分类能力：降级链与词典 stage 的等价性。

两块判据：
1. **词典 stage 必须与现有 `cluster_event_themes` 同口径** —— 否则引入这条链就改了行为。
2. **降级链语义** —— 前一级判出就不进下一级；边界才下移；后一级不许覆盖前一级。
"""

from __future__ import annotations

import re

import pytest

from app.config import PACKAGE_DIR
from core.classify import SOURCE_BGE, SOURCE_DICTIONARY, SOURCE_UNRESOLVED, StageSpec, Verdict, run_chain
from core.classify.dictionary import DictionaryStage
from core.manifest import load_manifest


# ---------------------------------------------------------------- manifest 声明


def test_manifest_declares_three_pluggable_features():
    features = load_manifest(PACKAGE_DIR).features

    assert set(features) >= {"locality", "event_classification", "dedup"}
    assert features["locality"]["enabled"] is True
    assert features["dedup"]["similarity"]["threshold"] == 0.65


def test_classification_stages_are_ordered_and_degradable():
    stages = load_manifest(PACKAGE_DIR).features["event_classification"]["stages"]

    kinds = [s["kind"] for s in stages]
    assert kinds == ["bge", "dictionary", "llm"], "降级链顺序必须是 bge→dictionary→llm"
    # 现在没有微调模型，bge 与 llm 必须关闭，词典是唯一生效级
    by_kind = {s["kind"]: s for s in stages}
    assert by_kind["bge"]["enabled"] is False
    assert by_kind["llm"]["enabled"] is False
    assert by_kind["dictionary"]["enabled"] is True


# ---------------------------------------------------------- 词典 stage 与现状等价


def _legacy_theme(record, terms):
    """复刻 `core/tools/events.py:cluster_event_themes` 的打分口径（不改它，只对照）。"""
    text = str(record.get("title") or "") + " " + str(record.get("summary") or "")
    order = list(terms)
    scores = {label: sum(text.count(word) for word in words) for label, words in terms.items()}
    best = max(scores.values()) if scores else 0
    if best <= 0:
        return None
    return next(label for label in order if scores[label] == best)


def test_dictionary_stage_matches_legacy_theme_scoring():
    from core.tools import vocabulary

    terms = vocabulary.cluster_terms()
    records = [
        {"id": "a", "title": "公交车司机与乘客争执", "summary": "道路交通拥堵"},
        {"id": "b", "title": "景区门票涨价引发游客投诉", "summary": "黄果树旅游"},
        {"id": "c", "title": "完全无关的内容", "summary": "xyz"},
        {"id": "d", "title": "火灾爆炸事故", "summary": "消防安全生产"},
        {"id": "e", "title": "学校和教师考试问题", "summary": "校园"},
    ]

    verdicts = {v.record_id: v for v in DictionaryStage().classify(records, StageSpec(kind="dictionary"))}

    for record in records:
        expected = _legacy_theme(record, terms)
        got = verdicts[record["id"]]
        if expected is None:
            assert got.category is None
            assert got.source == SOURCE_UNRESOLVED
        else:
            assert got.category == expected, f"{record['id']} 与 cluster_event_themes 不一致"
            assert got.source == SOURCE_DICTIONARY


# ------------------------------------------------------------------ 降级链语义


def _stage(kind, *, enabled=True, threshold=None):
    return StageSpec(kind=kind, enabled=enabled, confidence_threshold=threshold)


def test_chain_stops_at_first_deciding_stage():
    records = [{"id": "1"}, {"id": "2"}]

    def bge(recs, spec):
        return [Verdict("1", "文化旅游", 0.9, SOURCE_BGE), Verdict("2", source=SOURCE_UNRESOLVED, borderline=True)]

    def dictionary(recs, spec):
        assert [r["id"] for r in recs] == ["2"], "已判出的记录不该再进下一级"
        return [Verdict("2", "交通管理", 0.8, SOURCE_DICTIONARY)]

    verdicts, stats = run_chain(records, [(_stage("bge"), bge), (_stage("dictionary"), dictionary)])

    assert {v.record_id: v.category for v in verdicts} == {"1": "文化旅游", "2": "交通管理"}
    assert stats["0:bge"] == 1
    assert stats["1:dictionary"] == 1


def test_disabled_stage_is_skipped_without_calling_it():
    records = [{"id": "1"}]
    called = {"bge": False}

    def bge(recs, spec):
        called["bge"] = True
        return []

    def dictionary(recs, spec):
        return [Verdict("1", "社会民生", 0.9, SOURCE_DICTIONARY)]

    verdicts, stats = run_chain(
        records, [(_stage("bge", enabled=False), bge), (_stage("dictionary"), dictionary)]
    )

    assert called["bge"] is False, "enabled: false 的级不应被调用"
    assert stats["0:bge"] == 0
    assert verdicts[0].category == "社会民生"


def test_low_confidence_falls_through_to_next_stage():
    records = [{"id": "1"}]

    def bge(recs, spec):
        return [Verdict("1", "文化旅游", 0.4, SOURCE_BGE)]   # 低于阈值 0.75

    def dictionary(recs, spec):
        return [Verdict("1", "教育管理", 0.9, SOURCE_DICTIONARY)]

    verdicts, _ = run_chain(
        records,
        [(_stage("bge", threshold=0.75), bge), (_stage("dictionary"), dictionary)],
    )

    assert verdicts[0].category == "教育管理", "低置信应降级，不该采纳 bge 结果"


def test_new_cluster_is_treated_as_borderline():
    records = [{"id": "1"}]

    def bge(recs, spec):
        return [Verdict("1", "未知类", 0.95, SOURCE_BGE, borderline=True)]

    def dictionary(recs, spec):
        return [Verdict("1", "市场监管", 0.9, SOURCE_DICTIONARY)]

    verdicts, _ = run_chain(records, [(_stage("bge"), bge), (_stage("dictionary"), dictionary)])

    assert verdicts[0].category == "市场监管", "is_new_cluster 应视为边界并下移"


def test_unresolved_records_are_marked_for_human():
    records = [{"id": "1"}]

    def dictionary(recs, spec):
        return [Verdict("1", source=SOURCE_UNRESOLVED, reason="no_hit")]

    verdicts, _ = run_chain(records, [(_stage("dictionary"), dictionary)])

    assert verdicts[0].source == SOURCE_UNRESOLVED
    assert verdicts[0].category is None


def test_later_stage_never_overrides_earlier_decision():
    records = [{"id": "1"}]

    def dictionary(recs, spec):
        return [Verdict("1", "文化旅游", 0.9, SOURCE_DICTIONARY)]

    def llm(recs, spec):
        return [Verdict("1", "教育管理", 0.99, "llm")]   # 越界：不该覆盖

    verdicts, _ = run_chain(
        records, [(_stage("dictionary"), dictionary), (_stage("llm"), llm)]
    )

    assert verdicts[0].category == "文化旅游"
