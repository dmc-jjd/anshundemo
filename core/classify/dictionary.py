"""词典级判定：把现有 `cluster_event_themes` 的关键词打分包装成一条 stage。

口径必须与 `core/tools/events.py:cluster_event_themes` **逐字一致**：
    score = Σ text.count(词)，argmax；全 0 → 未判出；同分取词典键序靠前。
否则 `G-GOLDEN` 会变——那是不允许的。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from core.classify import SOURCE_DICTIONARY, SOURCE_UNRESOLVED, StageSpec, Verdict
from core.tools import vocabulary

#: 置信度的定义：命中词数 / 该条文本里出现的所有词典词数（0..1）。
#: 不是为了精确，是为了让"边界"有可比数值：只命中 1 个词、而文本里散落多个类的词 → 低置信。
def _confidence(scores: Mapping[str, int]) -> float:
    total = sum(scores.values())
    if total <= 0:
        return 0.0
    return max(scores.values()) / total


class DictionaryStage:
    kind = "dictionary"

    def classify(self, records: Sequence[Mapping[str, Any]], spec: StageSpec) -> list[Verdict]:
        terms = vocabulary.cluster_terms()
        order = list(terms)
        out: list[Verdict] = []

        for record in records:
            # 口径必须与 `core/tools/events.py:cluster_event_themes` 逐字一致：
            # 现状只取摘要前 300 字符（截断存在的意义是避免长摘要被尾部噪声带偏）。
            # 早先漏了这个截断——靠"全表 summary 都不超 200"侥幸没暴露，
            # 换一份摘要更长的客户数据就会分叉（verifier 已给可达反例）。
            text = str(record.get("title") or "") + " " + str(record.get("summary") or "")[:300]
            scores = {label: sum(text.count(word) for word in words) for label, words in terms.items()}
            best = max(scores.values()) if scores else 0
            if best <= 0:
                out.append(Verdict(record_id=str(record.get("id")), source=SOURCE_UNRESOLVED,
                                   reason="dictionary_no_hit"))
                continue
            # 同分取词典键序靠前的（与 cluster_event_themes 的 argmax 行为一致）
            winner = next(label for label in order if scores[label] == best)
            out.append(Verdict(
                record_id=str(record.get("id")),
                category=winner,
                confidence=_confidence(scores),
                source=SOURCE_DICTIONARY,
            ))
        return out
