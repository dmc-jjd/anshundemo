"""第二段「通用 schema」：`app/section_two.py` 里零客户数据的那部分模型。

为什么存在：
    `section_two` 是第二段的**客户规则**之家——县级地名表、报告地域名、
    客户字段 id、`anshun-*` 政策版本、以及 `validate_history` / `forecast_window` /
    `source_excerpts` / `seasonal_knowledge_usable` / `role` 这些把地名与字段 id
    写进正则与文案的校验函数。它们属于客户层，不进基座（`scripts/gate_core_clean.py`）。

    但同一模块里的四个 pydantic 模型是**客户无关**的：`Contract` / `BasisType` /
    `OutlookItem` / `RiskChain` / `AnalysisPlan` 只有字段与长度约束，没有客户字面量。
    基座侧消费者只要它们：`core/source_binding.py`（编号引用把 `source_refs` /
    `history_refs` 收成整数）与将来的 `structured_writer`。

判据（本文件不许出现的东西）：
    任何客户数据——县级地名、报告地域名、客户字段 id、政策版本串。这些都留在
    `app/section_two.py`；本文件一旦出现，`gate_core_clean.py` 立刻红。

搬法：
    同值搬家。五个定义与 `app/section_two.py` 原文逐字一致（只多出空行与缩进），
    `app/section_two.py` 把定义换成 `from core.section_schema import ...`，
    故 `from app.section_two import OutlookItem` 等既有公开面零变化。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

class Contract(BaseModel):model_config=ConfigDict(extra='forbid')
BasisType=Literal['historical','seasonal','local_activity']

class OutlookItem(Contract):
    basis_type:BasisType='historical'
    basis_label:str|None=Field(default=None,max_length=80)
    paragraph:str|None=Field(default=None,min_length=180,max_length=600)
    category:str=Field(min_length=2,max_length=30)
    historical_basis:str=Field(min_length=20,max_length=200)
    history_refs:list[str]=Field(min_length=1)
    trigger:str=Field(min_length=12,max_length=120)
    risk_path:str=Field(min_length=25,max_length=160)
    early_signals:list[str]=Field(min_length=1,max_length=5)
    owner:str=Field(min_length=2,max_length=100)
    action:str=Field(min_length=30,max_length=180)
    objective:str=Field(min_length=10,max_length=100)

class RiskChain(Contract):
    trigger:str=Field(min_length=15,max_length=120)
    escalation:str=Field(min_length=20,max_length=160)
    impact:str=Field(min_length=12,max_length=100)
    signal:str=Field(min_length=8,max_length=80)
    owner:str=Field(min_length=2,max_length=40)
    mitigation:str=Field(min_length=25,max_length=160)
    source_refs:list[str]=Field(min_length=1)

class AnalysisPlan(Contract):
    paragraph:str|None=Field(default=None,min_length=300,max_length=2000)
    overview:str=Field(min_length=25,max_length=120)
    chains:list[RiskChain]=Field(min_length=2,max_length=8)
