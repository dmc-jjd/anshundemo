"""域工具共享小件：分词与工件记录展开。自 `app/tool.py` 原样搬出，逻辑未改。

`words()` 的实现已移交 `core.text.tokenize`（唯一分词入口，第二批归一化第 1 项）：
函数名保留，39 个调用点不动——这样"分词规则"只有一处可改，而没有 39 处要跟。
"""

from __future__ import annotations

from core.text import tokenize


def words(text:str)->set[str]:
    """token 集合（去重）。具体切法与过滤规则见 `core.text.tokenize`。"""
    return set(tokenize(text))


def records_of(ctx,ref):
    obj=ctx.store.get_artifact(ref)
    return obj['records'] if isinstance(obj,dict) and 'records' in obj else obj
