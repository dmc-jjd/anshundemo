"""Contracts for template stages. Runtime snapshots are artifacts, not Python files."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, RootModel


class RawTemplateResult(RootModel[dict]):
    pass


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')

class ReviewContract(BaseModel):
    """审核/退修回复模型：对模型多出的字段宽容（extra='ignore'），避免 label_note 之类多余字段频繁触发结构化校验失败。"""
    model_config = ConfigDict(extra='ignore')

class WritingFinding(ReviewContract):
    field_id: str
    kind: Literal['format','fact','logic','ai_tone','meta_text']
    severity: Literal['blocking','warning']='warning'
    quote: str = Field(default='',max_length=800)
    quote_id: str | None = None
    description: str = Field(min_length=4,max_length=600)
    suggestion: str = Field(min_length=4,max_length=600)
    action: Literal['revise','report_only']='revise'
    evidence_refs: list[str] = Field(default_factory=list)

class StyleJudgment(ReviewContract):
    candidate_id: str
    label: str
    confidence: Literal['high','medium','low']
    reason: str = Field(min_length=4,max_length=300)

class WritingReviewReply(ReviewContract):
    summary: str = Field(min_length=1,max_length=600)
    issues: list[WritingFinding] = Field(default_factory=list,max_length=30)
    semantic_judgments: list[StyleJudgment] = Field(default_factory=list,max_length=160)

class WritingPatch(ReviewContract):
    field_id: str
    before: str | list[str]
    after: str | list[str]
    issue_ids: list[str] = Field(min_length=1)
    source_refs: list[str] = Field(default_factory=list)

class WritingRevisionReply(ReviewContract):
    patches: list[WritingPatch] = Field(default_factory=list,max_length=12)


class BlockSource(Contract):
    report_id: str
    block: int


class FieldSource(BlockSource):
    text: str = Field(min_length=1)


class DataBinding(Contract):
    tool: Literal['calculate_metrics', 'top10_events']
    path: list[str]


class TemplateField(Contract):
    id: str = Field(pattern=r'^[a-z][a-z0-9_]*$')
    display_name: str = Field(min_length=1)
    owner: Literal['data', 'writer']
    kind: Literal['number', 'text', 'list', 'analysis', 'metadata', 'table_rows']
    source_type: Literal['statistics', 'materials', 'analysis', 'task_metadata']
    semantic: str = Field(min_length=1)
    rule: str = Field(min_length=1)
    format: str = Field(min_length=1)
    missing_policy: Literal['block', 'omit_with_review']
    reason: str = Field(min_length=1)
    binding: DataBinding | None = None
    sources: list[FieldSource] = Field(min_length=1)


class TemplatePart(Contract):
    text: str | None = None
    field: str | None = None


class TemplateBlock(Contract):
    index: int
    kind: Literal['paragraph', 'table']
    purpose: str = Field(min_length=1)
    parts: list[TemplatePart] = Field(min_length=1)
    sources: list[BlockSource] = Field(min_length=1)


class TemplateQuestion(Contract):
    question: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    sources: list[BlockSource] = Field(min_length=1)


class TemplateReviewResult(Contract):
    summary: str = Field(min_length=1)
    blocks: list[TemplateBlock] = Field(min_length=1)
    fields: list[TemplateField]
    unresolved_items: list[TemplateQuestion]


class TemplateModelInput(Contract):
    policy: dict
    source_reports: list[dict] = Field(min_length=2)
    local_comparison: dict
    local_hypothesis: dict
    available_bindings: list[dict]
    instruction: str


class TemplateCandidateState(Contract):
    policy_version: str
    input_ref: str
    input_hash: str
    review_refs: list[str]
    candidate_ref: str
    candidate_hash: str
    validation: Literal['passed']
