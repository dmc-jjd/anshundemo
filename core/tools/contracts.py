"""工具契约模型（pydantic）：`SourceRef` / `ToolSpec` / `ToolResult`。

自 `app/schemas.py` **逐字**搬出（WP-S7-B）：字段序、默认值、`Literal` 一个字符未改——
`G-SPECS` 指纹靠字段序，`app/schemas.py` 只做 re-export（类身份不变）。
注意 `core.ports.ToolResult`（frozen dataclass）是另一个类型，两者本轮**不统一**（S7 §6 D2）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    file_id: str
    file_hash: str = ''
    location: str = ''
    record_ids: list[str] = Field(default_factory=list)


class ToolSpec(BaseModel):
    name: str
    description: str
    version: str = '1'
    required_capabilities: list[str] = Field(default_factory=list)
    produced_capabilities: list[str] = Field(default_factory=list)
    mutates_facts: bool = True
    arguments_schema: dict[str,Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    status: Literal['ok','needs_review','error']
    data_ref: str | None = None
    source_refs: list[SourceRef] = Field(default_factory=list)
    method: str = ''
    warnings: list[str] = Field(default_factory=list)
    unresolved: list[dict[str, Any]] = Field(default_factory=list)
    tool_version: str = '1'
    elapsed_ms: int = 0
    error_code: str | None = None
