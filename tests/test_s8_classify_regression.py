"""独立复验（w-verifier-2）发现的缺陷回归测试。

每条对应它给的证据，防止修完又退化：
- B1：bge 解析段裸奔 → 三种畸形响应会抛异常
- W1：词典 stage 漏 summary[:300] 截断（且原测试复刻了同一错口径）
- W3：非 str id 静默丢结论 + 重复调用下一级
- W7：stats 以 kind 为键，同 kind 两级互相覆盖
- W2：features 无消费者（装配器缺失）
"""

from __future__ import annotations

import pytest

from core.classify import SOURCE_DICTIONARY, SOURCE_UNRESOLVED, StageSpec, Verdict, run_chain
from core.classify.assemble import build_classification_chain, classify_records_with_features
from core.classify.bge import BgeStage
from core.classify.dictionary import DictionaryStage


# ------------------------------------------------------------------ B1 解析防护


class _FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_urlopen(monkeypatch, body: bytes):
    import core.classify.bge as mod

    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *a, **k: _FakeResp(body))


@pytest.mark.parametrize("body,label", [
    (b'[{"id":"1","category":"x","confidence":0.9}]', "顶层数组"),
    (b'{"results":[{"id":"1","category":"x","confidence":"high"}]}', "confidence 非数值"),
    (b'{"results":["not-an-object"]}', "results 元素非对象"),
    (b'{"results":"not-a-list"}', "results 非列表"),
    (b'{"results":[{"id":"1","category":123}]}', "category 非字符串"),
    (b'not json at all', "非法 JSON"),
])
def test_bge_never_raises_on_malformed_response(monkeypatch, body, label):
    """契约底线：任何畸形响应都必须退化成「整批边界」，不许抛异常打断报告链路。"""
    _patch_urlopen(monkeypatch, body)
    stage = BgeStage(base_url="http://fake", api_key="k", timeout=1)

    verdicts = stage.classify([{"id": "1", "title": "t", "summary": "s"}], StageSpec(kind="bge"))

    assert len(verdicts) == 1, f"{label}: 必须按条数补齐"
    assert verdicts[0].borderline is True, f"{label}: 应标边界"
    assert verdicts[0].source == SOURCE_UNRESOLVED


def test_bge_missing_base_url_degrades_without_network():
    stage = BgeStage(base_url="", api_key="", timeout=1)
    verdicts = stage.classify([{"id": "1"}, {"id": "2"}], StageSpec(kind="bge"))

    assert [v.borderline for v in verdicts] == [True, True]
    assert all(v.reason == "bge_not_configured" for v in verdicts)


# --------------------------------------------------- W1 词典截断（verifier 的反例）


def test_dictionary_truncates_summary_to_300_like_current_implementation():
    """现状 `cluster_event_themes` 只取摘要前 300 字符。

    verifier 构造的反例：触发词只出现在第 450 字符。截断后必须判「无类别」，
    与现状一致；不截断就会误判成「交通管理」。
    """
    from core.tools import vocabulary

    filler = "无关内容" * 112          # 约 448 字符
    record = {"id": "1", "title": "标题", "summary": filler + "交通"}
    assert len(record["summary"]) > 300

    verdict = DictionaryStage().classify([record], StageSpec(kind="dictionary"))[0]

    terms = vocabulary.cluster_terms()
    legacy_text = record["title"] + " " + record["summary"][:300]
    legacy_hit = any(legacy_text.count(w) for words in terms.values() for w in words)

    assert legacy_hit is False, "反例前提：前 300 字符里不该有命中词"
    assert verdict.category is None
    assert verdict.source == SOURCE_UNRESOLVED


# ------------------------------------------------------------ W3 id 类型归一


def test_int_ids_are_not_silently_dropped():
    """Excel 行号当 id 是自然误用；早期实现会丢结论并重复调下一级。"""
    records = [{"id": 7}, {"id": 8}]
    calls = {"second": []}

    def first(recs, spec):
        return [Verdict("7", "文化旅游", 0.9, "bge")]

    def second(recs, spec):
        calls["second"] = [str(r["id"]) for r in recs]
        return [Verdict("8", "交通管理", 0.9, SOURCE_DICTIONARY)]

    verdicts, _ = run_chain(records, [(StageSpec(kind="bge"), first), (StageSpec(kind="dictionary"), second)])

    by_id = {v.record_id: v.category for v in verdicts}
    assert by_id == {"7": "文化旅游", "8": "交通管理"}, "int id 的判定不许丢"
    assert calls["second"] == ["8"], "已判出的 7 不许再进下一级"


def test_records_without_id_are_kept_not_silently_dropped():
    """verifier 实证过：早期实现里无 id 记录从输出静默消失（输入 3 条 → 输出 2 条）。

    现在的契约是「不许静默丢」：给合成键 `__row_<idx>` 并标 `missing_id`，
    由调用方按前缀识别后转人工。
    """
    records = [{"title": "no id"}]
    verdicts, _ = run_chain(records, [(StageSpec(kind="dictionary"), DictionaryStage().classify)])

    assert len(verdicts) == 1, "条数必须保住，不许静默消失"
    assert verdicts[0].record_id == "__row_0"
    assert verdicts[0].reason == "missing_id"


def test_duplicate_ids_are_counted_not_silently_swallowed():
    """两条同 id 记录、上级给出两个不同判定时，第二条会被第一条挡掉。

    行为上可接受（同 id 视为同一实体），但必须让调用方知道有几条重叠。
    """
    records = [{"id": "7"}, {"id": "7"}]

    def first(recs, spec):
        return [Verdict("7", "甲", 0.9, SOURCE_DICTIONARY)]

    verdicts, stats = run_chain(records, [(StageSpec(kind="dictionary"), first)])

    assert stats.get("__duplicate_ids") == 1, f"重复 id 必须上报：{stats}"


# --------------------------------------------------------- W7 stats 不互相覆盖


def test_stats_distinguishes_two_stages_of_same_kind():
    records = [{"id": "1"}, {"id": "2"}]

    def a(recs, spec):
        return [Verdict("1", "甲", 0.9, SOURCE_DICTIONARY)]

    def b(recs, spec):
        return [Verdict("2", "乙", 0.9, SOURCE_DICTIONARY)]

    _, stats = run_chain(records, [(StageSpec(kind="dictionary"), a), (StageSpec(kind="dictionary"), b)])

    assert stats == {"0:dictionary": 1, "1:dictionary": 1}, f"同 kind 两级不许互相覆盖：{stats}"


# ------------------------------------------------------- W2 features 真有消费者


def test_assemble_builds_chain_from_manifest_features():
    features = {"event_classification": {"enabled": True, "stages": [
        {"kind": "bge", "enabled": False, "confidence_threshold": 0.75},
        {"kind": "dictionary", "enabled": True, "confidence_threshold": 0.0},
        {"kind": "llm", "enabled": False},
    ]}}

    plan = build_classification_chain(features)

    kinds = [spec.kind for spec, _ in plan.stages]
    assert kinds == ["bge", "dictionary"], "只装配已实现的 kind"
    assert plan.skipped == ("llm",), "未实现的 llm 必须报告，不许假装生效"
    assert plan.notes.get("llm") == "not_implemented"


def test_assemble_end_to_end_classifies_with_dictionary_only():
    from app.config import PACKAGE_DIR
    from core.manifest import load_manifest

    features = load_manifest(PACKAGE_DIR).features
    records = [{"id": "1", "title": "公交车司机争执", "summary": "道路交通"},
               {"id": "2", "title": "完全无关", "summary": "zzz"}]

    verdicts, stats, plan = classify_records_with_features(records, features)

    by_id = {v.record_id: v for v in verdicts}
    assert by_id["1"].category == "交通管理"
    assert by_id["2"].source == SOURCE_UNRESOLVED
    assert plan.skipped == ("llm",), "A 包声明了 llm 但未实现，必须出现在 skipped"
