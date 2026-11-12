"""BGE 微调模型的远程调用 stage。

服务端契约见 `docs/team/02-分类服务契约.md`。客户端只做三件事：
1. 批量 POST /classify
2. 把响应映射成 Verdict
3. 任何失败（超时/5xx/未就绪）→ **整批标边界**，交给下一级，绝不抛异常打断报告

`enabled: false` 时本模块不会被调用（manifest 控制），所以现在没有微调模型也不影响主链路。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Mapping, Sequence

from core.classify import SOURCE_BGE, SOURCE_UNRESOLVED, StageSpec, Verdict


class BgeStage:
    kind = "bge"

    def __init__(self, *, base_url: str = "", api_key: str = "", timeout: float = 30.0) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def classify(self, records: Sequence[Mapping[str, Any]], spec: StageSpec) -> list[Verdict]:
        if not self.base_url:
            # 没配地址 = 这级等于没开；全标边界交给下一级
            return [Verdict(record_id=str(r.get("id")), source=SOURCE_UNRESOLVED,
                            reason="bge_not_configured", borderline=True) for r in records]

        options = spec.options or {}
        batch_size = int(options.get("batch_size", 100))
        top_k = int(options.get("top_k", 1))
        out: list[Verdict] = []

        for start in range(0, len(records), batch_size):
            chunk = records[start:start + batch_size]
            out.extend(self._classify_batch(chunk, top_k))
        return out

    def _classify_batch(self, chunk: Sequence[Mapping[str, Any]], top_k: int) -> list[Verdict]:
        payload = {
            "items": [
                {"id": str(r.get("id")), "title": r.get("title") or "",
                 "summary": r.get("summary") or "",
                 "text": (str(r.get("title") or "") + "\n" + str(r.get("summary") or "")).strip()}
                for r in chunk
            ],
            "options": {"top_k": top_k},
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = urllib.request.Request(
            f"{self.base_url}/classify",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                body = resp.read()
        except Exception:
            # 读取阶段也必须吞掉全部异常：反代半包（IncompleteRead）、
            # BadStatusLine 属 http.client.HTTPException，既不是 OSError 也不是
            # ValueError，早先会穿出 classify() 打断报告链路（verifier 实证）。
            return [Verdict(record_id=str(r.get("id")), source=SOURCE_UNRESOLVED,
                            reason="bge_unavailable", borderline=True) for r in chunk]

        try:
            data = json.loads(body.decode("utf-8", "replace"))
        except Exception:
            return [Verdict(record_id=str(r.get("id")), source=SOURCE_UNRESOLVED,
                            reason="bge_bad_response", borderline=True) for r in chunk]

        # 解析段同样设防：顶层数组 / confidence 写成字符串 / results 元素非对象，
        # 都会让异常抛进报告链路。契约是"任何失败都退化成边界"。
        try:
            by_id = self._parse_results(data)
        except Exception:
            return [Verdict(record_id=str(r.get("id")), source=SOURCE_UNRESOLVED,
                            reason="bge_bad_response", borderline=True) for r in chunk]

        out: list[Verdict] = []
        for record in chunk:
            rid = str(record.get("id"))
            out.append(by_id.get(rid, Verdict(record_id=rid, source=SOURCE_UNRESOLVED,
                                              reason="bge_missing_result", borderline=True)))
        return out

    @staticmethod
    def _parse_results(data: Any) -> dict[str, Verdict]:
        """把服务响应映射成 Verdict。结构不符即抛——由调用方统一降级成边界。"""
        if not isinstance(data, dict):
            raise ValueError("bge_response_not_object")
        results = data.get("results")
        if not isinstance(results, list):
            raise ValueError("bge_results_not_list")

        by_id: dict[str, Verdict] = {}
        for item in results:
            if not isinstance(item, dict):
                raise ValueError("bge_result_not_object")
            # 注意：不能用 `item.get("id") or ""`——id=0 是合法主键，会被 falsy 吞掉，
            # 导致该条永远回填不上（verifier 实证 reason=bge_missing_result）。
            raw_id = item.get("id")
            if raw_id is None:
                continue
            rid = str(raw_id).strip()
            if not rid:
                continue
            category = item.get("category")
            if category is not None and not isinstance(category, str):
                raise ValueError("bge_category_not_string")
            try:
                confidence = float(item.get("confidence") or 0.0)
            except (TypeError, ValueError):
                raise ValueError("bge_confidence_not_numeric") from None
            is_new = bool(item.get("is_new_cluster"))
            decided = bool(category) and not is_new
            by_id[rid] = Verdict(
                record_id=rid,
                category=category,
                confidence=confidence,
                source=SOURCE_BGE if decided else SOURCE_UNRESOLVED,
                borderline=is_new,
                # 审计要能区分"模型明确给了空类别"与"判为新簇"
                reason="" if decided else ("new_cluster" if is_new else "no_category_returned"),
            )
        return by_id
