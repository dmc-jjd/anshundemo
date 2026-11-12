from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator
from core.tools.contracts import SourceRef, ToolSpec, ToolResult

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

class Placeholder(BaseModel):
    id: str
    color: Literal['red','green','purple','yellow','cyan']
    semantic: str
    scope: str = 'all'
    statistical_unit: str = 'record'
    denominator: str | None = None
    missing_policy: str = 'review'
    source_refs: list[SourceRef] = Field(default_factory=list)

class TemplateVersion(BaseModel):
    id: str
    template_id: str
    version: int
    name: str
    status: Literal['confirmed','candidate','source_missing']
    sections: list[dict[str, Any]] = Field(default_factory=list)
    placeholders: list[Placeholder] = Field(default_factory=list)
    data_requirements: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    created_at: str = Field(default_factory=now)
    content_hash: str = ''

class ToolCall(BaseModel):
    call_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    input_refs: list[str] = Field(default_factory=list)
    reason: str = ''
    idempotency_key: str = ''

class ToolDecision(BaseModel):
    action: Literal['call_tool','request_human','finish_processing']
    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = ''

    @model_validator(mode='after')
    def check_call(self):
        if self.action=='call_tool' and not self.tool_name: raise ValueError('tool_name_required')
        return self

class HumanDecision(BaseModel):
    item_id: str
    expected_revision: int
    action: Literal['confirm','modify','merge','split','independent','exclude','defer']
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str
    actor: str = 'local-operator'
    timestamp: str = Field(default_factory=now)

class DraftVersion(BaseModel):
    id: str
    fact_ref: str
    template_ref: str
    sections: list[dict[str, Any]] = Field(default_factory=list)
    slot_values: dict[str, dict[str, Any]] = Field(default_factory=dict)
    structured_template_ref: str | None = None
    chart_refs: dict[str,str] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list, max_length=5)
    source_refs: list[str] = Field(default_factory=list)
    missing_recommendation_evidence: bool = False
    content_hash: str = ''

class ReviewIssue(BaseModel):
    field_id: str
    severity: Literal['blocking','warning']
    description: str
    evidence_refs: list[str] = Field(default_factory=list)

class ReviewResult(BaseModel):
    draft_hash: str
    reviewer: str
    round: int
    issues: list[ReviewIssue] = Field(default_factory=list)
    passed: bool

class FactSnapshot(BaseModel):
    id: str
    template_ref: str
    input_refs: list[str]
    result_refs: dict[str,str]
    report_month: str | None = None
    metrics: dict[str,Any]
    confirmed_event_count: int
    top10: list[dict[str,Any]] = Field(default_factory=list)
    decisions: list[dict[str,Any]]
    version: int = 1
    created_at: str = Field(default_factory=now)
    content_hash: str = ''

class TaskState(BaseModel):
    id: str
    kind: Literal['template','report']
    phase: str
    revision: int = 0
    template_ref: str | None = None
    input_refs: list[str] = Field(default_factory=list)
    result_refs: dict[str, str] = Field(default_factory=dict)
    review_items: list[dict[str, Any]] = Field(default_factory=list)
    fact_ref: str | None = None
    draft_ref: str | None = None
    tool_calls: int = 0
    planning_calls: int = 0
    review_counts: dict[str,int] = Field(default_factory=lambda:{'format':0,'content':0})
    fallback: dict[str,Any] | None = None
    cancel_requested: bool = False
    metadata: dict[str,Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now)

