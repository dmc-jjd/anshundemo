"""编排基座的核心接口契约（端口）。

设计原则（计划书 §3 / §8）：
- 基座只依赖本文件里的接口；客户包只实现接口并注册自己；二者互不 import。
- 本文件不 import `app/` 下任何模块，保证基座可独立测试。
- 与 `app/schemas.py` 的同名类型**结构兼容**，迁移期由 `app/schemas.py` 反向 re-export，
  这样调用方零改动（计划书 §9 P2 的「保留薄壳」策略）。

为什么要有这一层：
现 `app/tool.py:276-300` 用三个可变全局字典（HANDLERS / READ_ONLY / ARGUMENTS）
拼出工具注册表，且 `get_tool_specs()` 在调用时 import 别的模块以"就地扩表"——
这是隐式耦合：谁 import 谁、什么时候生效，都不在类型里。本文件把这件事变成显式契约。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Mapping, Protocol, runtime_checkable

# --------------------------------------------------------------------------- #
# 数据契约
# --------------------------------------------------------------------------- #

ToolStatus = Literal["ok", "needs_review", "error"]
NodeKind = Literal["agent", "tool", "gate", "loop"]
ReviewerKind = Literal["format", "content"]


@dataclass(frozen=True, slots=True)
class SourceRef:
    """一条数据的来源指针。基座只搬运，不解释。"""

    file_id: str = ""
    file_hash: str = ""
    location: str = ""
    record_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """工具声明。执行器只认这个，不认工具内部实现。"""

    name: str
    description: str
    version: str = "1"
    #: 真实 JSON Schema（不是现在那种 {"required": [...], "properties": {...str...}} 的伪 schema）
    arguments_schema: Mapping[str, Any] = field(default_factory=dict)
    required_capabilities: tuple[str, ...] = ()
    produced_capabilities: tuple[str, ...] = ()
    #: True 表示会改事实数据，冻结后禁止调用
    mutates_facts: bool = True
    #: 声明式幂等，执行器据此决定能否重试
    idempotent: bool = False
    timeout_s: float | None = None


@dataclass(frozen=True, slots=True)
class ToolResult:
    """工具返回。status 是语义，不是 HTTP 码。"""

    status: ToolStatus
    data_ref: str | None = None
    source_refs: tuple[SourceRef, ...] = ()
    method: str = ""
    warnings: tuple[str, ...] = ()
    unresolved: tuple[Mapping[str, Any], ...] = ()
    tool_version: str = "1"
    elapsed_ms: int = 0
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    tool_name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    input_refs: tuple[str, ...] = ()
    reason: str = ""
    idempotency_key: str = ""


# --------------------------------------------------------------------------- #
# 工具策略（计划书 §3：把执行器里的业务硬编码换成声明）
# --------------------------------------------------------------------------- #

#: 拒绝码，必须可审计（计划书 §3.1）
REJECT_TOOL_NOT_ALLOWED = "tool_not_allowed"
REJECT_PHASE_NOT_ALLOWED = "tool_phase_not_allowed"
REJECT_BUDGET_EXCEEDED = "tool_budget_exceeded"
REJECT_FROZEN_FACTS = "frozen_facts"
REJECT_SCHEMA_INVALID = "arguments_schema_invalid"


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    """客户包在 manifest 里声明的工具白名单。

    现 `app/tool_executor.py` 把客户规则写死在 if/else 里（计划书 §3 表格 5 处），
    迁移后执行器只读这个对象。
    """

    #: 全局允许调用的工具
    allow: frozenset[str] = frozenset()
    #: 阶段 -> 该阶段额外允许的工具（与 allow 取并集）
    phases: Mapping[str, frozenset[str]] = field(default_factory=dict)
    #: 阶段 -> 调用预算；default 为兜底
    budgets: Mapping[str, int] = field(default_factory=lambda: {"default": 40})

    def permits(self, tool: str, phase: str) -> str | None:
        """返回 None 表示放行，否则返回拒绝码。"""
        allowed = set(self.allow) | set(self.phases.get(phase, frozenset()))
        if tool not in allowed:
            return REJECT_TOOL_NOT_ALLOWED if not self.phases else REJECT_PHASE_NOT_ALLOWED
        return None

    def budget(self, phase: str) -> int:
        return self.budgets.get(phase, self.budgets.get("default", 40))


# --------------------------------------------------------------------------- #
# 依赖协议（只声明调用方需要什么，不规定实现）
# --------------------------------------------------------------------------- #


@runtime_checkable
class ArtifactStore(Protocol):
    """内容寻址工件存储。现由 `app/storage.py` 实现。"""

    def put_artifact(self, task_id: str, kind: str, payload: Any) -> str: ...

    def get_artifact(self, ref: str) -> Any: ...


@runtime_checkable
class EventSink(Protocol):
    """执行事件落盘。拒绝、降级、耗时都走这里。"""

    def emit(self, kind: str, payload: Mapping[str, Any]) -> None: ...


@runtime_checkable
class ToolContext(Protocol):
    """工具执行上下文。

    现 `app/tool.py` 的每个 handler 签名都是 `(args, ctx)`，`ctx` 上用到
    `ctx.store` 与 `ctx.task_id`；本协议把它显式化，并补上 phase 与事件出口。
    """

    task_id: str
    store: ArtifactStore
    phase: str
    events: EventSink


@runtime_checkable
class Tool(Protocol):
    spec: ToolSpec

    def __call__(self, arguments: Mapping[str, Any], ctx: ToolContext) -> ToolResult: ...


@runtime_checkable
class ToolRegistry(Protocol):
    """只读注册表。不允许 `get_tool_specs()` 那种调用时就地扩表的副作用。"""

    def get(self, name: str) -> Tool: ...

    def specs(self) -> tuple[ToolSpec, ...]: ...

    def names(self) -> tuple[str, ...]: ...


# --------------------------------------------------------------------------- #
# 其余端口（计划书 §7 的 Ports 表）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class AgentRole:
    """角色 + 提示词 + 输出 Schema → 一次模型调用。"""

    role_id: str
    description: str
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    prompt_ref: str = ""
    #: 提示词指纹，用于「外置后文本不变」的门禁（计划书 §9 P5）
    prompt_fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class ReviewerSpec:
    kind: ReviewerKind
    role_id: str
    #: 路由：哪些字段问题交给这个审核员
    routes: tuple[str, ...] = ()
    max_rounds: int = 2


@dataclass(frozen=True, slots=True)
class GraphNode:
    id: str
    kind: NodeKind
    ref: str = ""  #: agent role_id / tool name / gate id
    next: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GraphSpec:
    """图规格。引擎读它组图，不认识任何具体报告业务。"""

    id: str
    nodes: tuple[GraphNode, ...]
    entry: str = ""

    def node(self, node_id: str) -> GraphNode:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(f"unknown_node:{node_id}")

    def validate(self) -> list[str]:
        problems: list[str] = []
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            problems.append("duplicate_node_id")
        known = set(ids)
        if self.entry and self.entry not in known:
            problems.append(f"entry_not_found:{self.entry}")
        for n in self.nodes:
            for nxt in n.next:
                if nxt not in known:
                    problems.append(f"dangling_edge:{n.id}->{nxt}")
        if not self.entry and ids:
            problems.append("entry_missing")
        return problems


# --------------------------------------------------------------------------- #
# 客户包清单（manifest）
# --------------------------------------------------------------------------- #

REQUIRED_MANIFEST_KEYS = ("package", "report_type", "version", "template", "prompts")


@dataclass(frozen=True, slots=True)
class ChartRef:
    id: str
    title: str = ""
    family: str = ""
    style: str = ""
    binding: Mapping[str, Any] = field(default_factory=dict)
    unit: str = ""
    scope: str = ""


@dataclass(frozen=True, slots=True)
class Manifest:
    """客户包唯一入口。加载时即校验，缺字段直接启动失败。"""

    package: str
    report_type: str
    version: str
    template: str
    prompts: str
    policy: ToolPolicy = field(default_factory=ToolPolicy)
    chart_pack: str = ""
    chart_use: tuple[str, ...] = ()
    skill_pack: str = ""
    skill_use: tuple[str, ...] = ()
    charts: tuple[ChartRef, ...] = ()

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Manifest":
        missing = [k for k in REQUIRED_MANIFEST_KEYS if not data.get(k)]
        if missing:
            raise ValueError(f"manifest_missing_keys:{','.join(missing)}")

        tools = data.get("tools") or {}
        policy = ToolPolicy(
            allow=frozenset(tools.get("allow") or ()),
            phases={k: frozenset(v or ()) for k, v in (tools.get("phases") or {}).items()},
            budgets=dict(tools.get("budgets") or {"default": 40}),
        )
        charts_cfg = data.get("charts") or {}
        skills_cfg = data.get("skills") or {}
        return cls(
            package=str(data["package"]),
            report_type=str(data["report_type"]),
            version=str(data["version"]),
            template=str(data["template"]),
            prompts=str(data["prompts"]),
            policy=policy,
            chart_pack=str(charts_cfg.get("pack", "")),
            chart_use=tuple(charts_cfg.get("use") or ()),
            skill_pack=str(skills_cfg.get("pack", "")),
            skill_use=tuple(skills_cfg.get("use") or ()),
        )


# --------------------------------------------------------------------------- #
# 解耦门禁：基座代码不许出现客户业务词（计划书 §10）
# --------------------------------------------------------------------------- #
#
# 为什么禁词表不写在这里：
# 门禁会扫描 `core/**/*.py`。若禁词以字面量定义在 core 内，扫描必然命中定义本身，
# 形成自指、永远 5 条命中（S2-A 实测如此）。因此禁词表移到 `scripts/forbidden_terms.json`，
# 本文件只保留算法。这也让禁词表成为可替换的数据，而不是程序的一部分。


def load_forbidden_terms(path: "str | Path") -> tuple[str, ...]:
    """从 JSON 数组文件读禁词表。缺文件即抛错，不静默降级。"""
    import json
    from pathlib import Path as _Path

    data = json.loads(_Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, list) or not all(isinstance(x, str) and x for x in data):
        raise ValueError("forbidden_terms_must_be_non_empty_string_list")
    return tuple(data)


def scan_forbidden_terms(
    texts: Iterable[tuple[str, str]],
    terms: Iterable[str],
) -> list[str]:
    """texts 为 (文件名, 文本) 二元组流；返回 `文件:词` 形式的问题列表。

    `terms` 必须显式传入（见 `load_forbidden_terms`），不设默认值——
    任何默认值都会把禁词字面量带回 core 内，重新造成自指。
    """
    banned = tuple(terms)
    problems: list[str] = []
    for name, text in texts:
        for term in banned:
            if term in text:
                problems.append(f"{name}:{term}")
    return problems
