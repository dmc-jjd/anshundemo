# 安顺月报工作台 Demo 构建与 Agent 交接计划

> **供执行 Agent 使用** 按任务逐项执行。可使用 `executing-plans` 技能。仅在用户选择多 Agent 执行后使用 `subagent-driven-development`。本文件授权范围为构建计划，执行者须先取得用户的实施指令。

**目标** 从零构建可点击、可执行、可追溯的安顺月报 Demo，以现有五色模板提交报告，同时展示本地比对多份历史报告、模型检查分析及模板确认。

**架构** LangGraph 管理业务阶段和恢复，数据处理 Agent 动态选择独立工具，执行器校验并运行工具。人工确认模板、业务疑难、正式事实及最终稿，公开保底方案处理规划失败。

**技术栈建议** Python 3.12、FastAPI、Pydantic 2、LangGraph、SQLite 检查点与业务存储、python-docx、openpyxl、Matplotlib、scikit-learn，前端采用同源 HTML/CSS/JavaScript。此项为计划作者提出的可替换默认方案，用户仅指定 Python 文件分工与 LangGraph。执行前核实兼容版本并锁定实际安装结果。

**配套设计** `D:\分析报告demo\2026-11-06-report-demo-design.md`。本计划与设计稿一起交接，当前用户要求优先于旧材料。用户尚未对整份设计稿作最终批准。

## 0. 执行入口与当前状态

- 工作目录为 `D:\分析报告demo`。该句原为实施前状态；现已创建产品代码与验收记录，实际进度以 `docs/验收记录.md` 为准。
- 旧项目为 `D:\KN分析报告multi-agent`，作为只读参考。当前目录经检查未初始化 Git，任务中的提交步骤仅在用户授权初始化或已有仓库时执行。
- 本计划包含建议接口与验收用例，函数、测试、命令均待构建，文中的预期通过结果不代表已验证。
- 执行者先阅读本计划、配套设计、工作目录约束和相关技能。按任务顺序实现，一个任务完成并验证后再进入下一任务。
- 本计划不要求执行者依赖当前聊天。范围变更须记录，遇到缺少真实文件、模型配置或业务口径时，保留明确缺失状态并完成其余独立任务。

## 1. 全局约束

1. 演示报告提交使用“安顺月报 · 五色逐项占位模板”。多报告新建候选单独保存与确认。
2. 多报告处理优先本地提取、结构对齐、文本匹配与差异识别，随后交模型检查分析。展示真实处理过程及来源。
3. `agent.py` 仅保存各角色定义、工作内容、职责边界、输出要求，不包含模型客户端、工具实现与流程路由。
4. `tool.py` 每个公开业务工具相对独立，调度由模型与执行器完成。模板保存数据目标及口径，常规路径的工具组合由模型决定。
5. `workflow.py` 独立保存 LangGraph 工作流。保底步骤放 `fallback_policy.py`，启用原因与实际执行过程在页面可见。
6. 原始记录与事件组分开，完整集合负责统计，抽样仅辅助解释。全量、负面、重点预警与指定媒体分别声明范围。
7. 业务疑难建议进入当前任务业务人员的研判队列。阻断问题未解决时禁止冻结相关正式事实。
8. 工作建议最多五条。依据不足可少写，零条时显示资料缺失并交人工，禁止为凑数编造依据。
9. 格式和内容审查各含首次最多两轮，失败调用另记。结论、终审和导出绑定当前稿件及事实版本。
10. 已冻结事实不可覆盖。修正产生新事实和新生成任务。正文、图表、表格和 Word 使用同一事实版本。
11. 输入资料视为数据。工具名、数据引用、输出路径、字段修改范围由代码校验。文件写入限定任务目录，密钥与日志分离。
12. 首版以本机单业务人员演示为运行边界，同时防止重复提交和过期确认覆盖。客户管理与生产权限体系留待后续明确。

## 2. 材料清单与迁移规则

最新用户提供正式模板源 `C:\Users\57676\Desktop\2026年8月安顺市网络舆情分析报告.docx`，优先于以下不可访问的旧项目路径。模板正文前必须有逐项占位符定义；源 Word 高亮语义依用户最新确认：红计算、绿正文峰值事件原文概要、黄事件聚类、粉紫现有字段、灰事件原文概述。TOP10 单元格未着色无需补色，但应成为可编辑动态表格。源 Word 的红色同比文字和问题概述属于误标，按文字型槽位处理。10 月全量表事件分类全空；817 行负面预警表仅用于核对，不得回填冒充全量表分类。

| 已核实路径 | 用途与注意事项 |
|---|---|
| `D:\KN分析报告multi-agent\项目总结与从零重建基线-20261106.md` | 业务全景与基线，最新用户调整优先 |
| `D:\KN分析报告multi-agent\templates\anshun-monthly\colored-september-v1\report.template.json` | 五色内容、封面、槽位、原文证据来源，旧文件状态为候选 |
| 同目录 `report-values.schema.json`、`模板说明与正文.md` | 槽位约束、五色图例与口径，旧建议条数需要更新 |
| `D:\KN分析报告multi-agent\templates\anshun-monthly\layout.json` | Word 版式参考，旧文件声明版式尚未获客户正式确认 |
| `D:\KN分析报告multi-agent\demo\colored_template.py` | 旧接入参考，包含固定四条与内部固定组合，按本计划重新设计 |
| `D:\KN分析报告multi-agent\demo\locality_terms.py`、`locality_router.py` | 属地词典与规则参考，核实依赖后按需迁移 |
| `D:\KN分析报告multi-agent\reference_extract` | 可读历史提取资料的候选位置，执行者核实文件与原文关联 |

迁移时保存原件哈希及来源清单，在新目录建立标准化模板。保留固定原文、标点和槽位，修改内容为版本化差异。旧适配器中的 `prepare_colored_report_data` 等聚合工具须拆为独立工具。旧文件中的历史数字、事件、测试数、服务状态不作为本期默认值或当前验收证据。

实际全量 Excel 与多份历史 DOCX 的可读性尚未核实。测试可由代码生成最小人工样本，页面明确标注。真实样本及付费模型未验证项进入交付清单。

## 3. 目标文件结构

以下均相对新工作目录。

```text
app/
  main.py                 FastAPI 接口与本地工作台入口
  agent.py                角色定义与工作内容
  workflow.py             LangGraph 模板图与报告图
  schemas.py              统一数据契约
  model_client.py         可注入模型接口与供应商适配
  tool.py                 工具目录与独立入口
  tool_executor.py        校验、执行、幂等与调用日志
  fallback_policy.py      公开、版本化保底计划
  storage.py              SQLite 业务存储与文件引用
  template_compare.py     本地历史结构对齐算法
  report_validation.py    事实、稿件、引用和审查校验
  export.py               Word 与图表组装
  config.py               环境配置与预算
  static/index.html       本地工作台
  static/app.js           任务、研判与模板交互
  static/style.css        页面样式
templates/anshun-colored/  标准化五色模板、Schema 与版式
tests/                    仅覆盖本计划关键回归的自动测试
data/                     本机生成文件、数据库与日志，忽略 Git
pyproject.toml             依赖、测试与打包定义
requirements.lock         实际解析成功的精确依赖版本
.env.example              配置项名及说明，空密钥
README.md                 本机启动与演示操作
```

初期采用简单同源页面便于本机演示。后续替换前端时沿用 API 与数据契约。首版无需额外构建前端工程。

## 4. 统一接口与数据契约

### 4.1 契约对象

所有持久对象有 `id`、`schema_version`、`created_at`、`content_hash`，时间采用带时区的 ISO 8601，页面显示北京时间。确认操作同时提交预期修订号。

| 类型 | 关键字段 |
|---|---|
| SourceRef | file_id、file_hash、paragraph_index 或 sheet/row/cell、record_ids |
| TemplateVersion | template_id、version、status、sections、placeholders、data_requirements、output_schema、layout、source_refs |
| Placeholder | id、color、semantic、scope、statistical_unit、denominator、time_window、missing_policy、format、source_refs |
| ToolSpec | name、description、version、arguments_schema、result_schema、required_capabilities、produced_capabilities、allowed_phases、mutates_facts |
| ToolCall | call_id、tool_name、arguments、input_refs、reason、idempotency_key |
| ToolResult | status=ok/needs_review/error、data_ref、source_refs、method、warnings、unresolved、tool_version、elapsed_ms、error_code |
| ReviewItem | task_id、revision、kind、blocking、record_refs、field_ids、question、evidence_refs、suggestion、uncertainty、allowed_actions、status |
| HumanDecision | item_id、expected_revision、action、payload、reason、actor、timestamp |
| FactSnapshot | template_ref、input_hashes、scope_definitions、metrics、event_groups、topics、materials、decisions、tool_runs、version、hash |
| DraftVersion | fact_ref、template_ref、sections、recommendations、source_refs、parent_draft_id、hash |
| ReviewResult | draft_hash、reviewer、round、issues、passed |
| ReviewIssue | issue_id、field_id、related_fields、severity、description、evidence_refs、required_change、acceptance_criteria |
| TaskState | task_id、kind、phase、revision、template_ref、input_refs、result_refs、review_item_ids、fact_ref、draft_ref、budgets、review_counts、fallback、cancel_requested |

模型决策为可校验联合类型 `ToolDecision`，其 action 为 `call_tool`、`request_human` 或 `finish_processing`。结束处理需由程序核查模板目标覆盖和未解决项。模型输出不能直接确认模板、事实或终稿。

### 4.2 模块公开接口

下列类型统一在 `schemas.py` 定义，`RunContext` 保存任务级存储、预算及取消句柄，`Dependencies` 保存执行器、模型与存储依赖。

```python
# agent.py
AGENT_DEFINITIONS: dict[str, AgentDefinition]
# tool.py
def get_tool_specs() -> list[ToolSpec]: ...
def get_tool_handler(name: str) -> ToolHandler: ...
# ToolHandler 为 (arguments: dict, context: RunContext) -> ToolResult
# tool_executor.py
async def execute_tool(call: ToolCall, context: RunContext) -> ToolResult: ...
# model_client.py
async def invoke_agent(role_id: str, payload: dict,
                       response_model: type[BaseModel],
                       context: RunContext) -> BaseModel: ...
# template_compare.py
def compare_reports(documents: list[ParsedDocument]) -> TemplateComparison: ...
# storage.py
class Store:
    def put_artifact(self, task_id: str, kind: str, payload: dict) -> ArtifactRef: ...
    def get_artifact(self, ref: ArtifactRef) -> dict: ...
    def apply_decision(self, decision: HumanDecision) -> DecisionResult: ...
    def append_event(self, task_id: str, event: TaskEvent) -> None: ...
# workflow.py
def build_template_graph(dependencies: Dependencies) -> CompiledStateGraph: ...
def build_report_graph(dependencies: Dependencies) -> CompiledStateGraph: ...
# fallback_policy.py
def build_fallback_plan(state: TaskState, reason: str) -> FallbackPlan: ...
# report_validation.py
def validate_draft(draft: DraftVersion, facts: FactSnapshot,
                   template: TemplateVersion) -> list[ReviewIssue]: ...
# export.py
def export_docx(draft: DraftVersion, facts: FactSnapshot,
                template: TemplateVersion, context: RunContext,
                mode: Literal['draft', 'final']) -> ExportArtifact: ...
```

执行者可按实际库接口调整类型导入，跨任务接口变更须同步调用方与契约测试。

## 5. LangGraph 节点与运行规则

模板图采用 `extract_local → compare_local → analyze_with_model → validate_candidate → human_confirm → save_version`。局部提取失败形成明确失败项，人工可选择移除不可读文件后重新比对，至少保留两份可读报告。

报告图采用 `validate_input → plan_next → execute_tool → assess_progress` 循环。`assess_progress` 可回规划、进入 `fallback`、进入 `human_review` 或进入 `confirm_facts`。人工确认后进入 `freeze_facts → write → format_review → content_review → render → final_review → export`。修订返回写作，证据或事实错误交人工。

业务阶段门槛由代码约束。常规 `plan_next` 根据已有结果选择工具，新增同能力工具可进入目录，模型无需修改图边即可选择。保底分支使用显式计划，经过同一执行器。

检查点使用稳定 `thread_id=task_id`。人工暂停用 LangGraph 中断及恢复机制，浏览器刷新或进程重启后读取持久检查点。运行通过后台 worker 执行，API 立即返回任务 ID。单进程 Demo 中每任务串行执行，SQLite 乐观版本校验防止并发提交覆盖。

### 建议预算默认值

这些数值为实施默认建议，集中配置并显示在任务详情，尚无性能评估依据。

| 项目 | 默认值与行为 |
|---|---|
| 数据处理规划调用 | 最多 12 次，耗尽可进入保底 |
| 全任务工具调用 | 最多 40 次，含失败与保底，耗尽暂停 |
| 同签名失败重试 | 最多额外 1 次，仅重试明确可重试错误 |
| 无进展阈值 | 连续 3 次决策没有新增有效产物或解决问题，进入保底 |
| 模型调用超时 | 120 秒，失败单独记账 |
| 普通本地工具超时 | 60 秒，可按工具覆盖 |
| 格式/内容审查 | 各最多 2 轮，沿用确认基线 |
| 费用上限 | 可配置，币种显式，价格未知时显示未知用量成本 |

有费用硬上限且缺少可计算价格时，暂停付费调用并要求补配置。任务总时限计算有效执行时间，人工等待不消耗该时限。耗尽硬上限须暂停，恢复前由人工显式调整预算并留痕。

## 6. 保底计划的具体边界

2026-11-06 最新确认优先：第一部分（四）的事件池为全量明细中负面 **或** 已预警的行并集，同一记录只计一次。保底保留全量与正面、中性、负面、预警各自的筛选引用，并为第一部分（四）显式建立并集工件，再将此工件交两轮事件候选、属地和独立聚类。第一部分（一）的“负面单一重点预警”不套用该并集，另列待审。模型动态路径必须读取模板 99 个逐项占位符目标和已确认范围，自主选择独立工具，执行器验证输入、范围、前提和预算；没有真实模型时仅声称保底已验证。

范围门槛：全量调性/峰值与平台先用全量记录；负面、预警分别筛选并保留引用。两轮事件候选工具的 `records_ref` 必须由针对具体报告槽位的已确认范围决定提供；缺此决定时跳过两轮并进入人工范围选择。不得默认采用“负面且已预警”交集。第一部分（一）的重点预警事件与第一部分（四）的敏感及负面事件是否同集合是待核对业务口径。

当全量表事件分类为空时，保底方案显式调用独立 `cluster_event_themes`，以原文生成分类/主题候选，保存成员、方法、来源、参数和人工待核验状态。不能把 817 行测试表中的分类直接移植到全量记录。

仅对已适配的五色模板启用 `anshun-colored-fallback-v1`。按未满足目标生成待执行步骤，复用已校验有效结果。

1. 校验字段映射和报告月份，规范化全量记录。
2. 计算全量调性、平台、每日分布与峰值。
3. 按已确认条件筛选负面及重点预警范围。
4. 调用属地候选、第一轮关键词同事件候选、第二轮向量近邻跨组与跨日跟进候选、分类与主题工具，疑难进入人工队列。第二轮必须消费第一轮候选组及未解决记录；两工具各自独立，由 workflow.py 和执行器显式衔接，不能在工具内部相互调度。两轮只产候选，不能自动确认事件数。
5. 人工确认后统计事件类别、区县及有明确规则的 TOP10，筛选各范围代表材料。
6. 校验模板数据目标，准备事实确认。

此顺序仅属于公开保底方案。媒体筛选、代表材料与主题等可独立目标由方案依据缺口补入。缺少预警字段或排序规则时提出问题，等待人工确认，禁止自动将全部负面当作重点预警。保底中模型仍不可用时，主题命名等语义结果交人工确认。

## 7. 任务与验收

每项先建立列出的关键回归测试，确认失败原因，再实现最小完整功能并运行验证。测试代码可使用测试构造器简化输入，但测试所断言的业务值须保留。每个任务完成后记录改动、实际命令和结果，有仓库时提交该任务改动。

### 任务 1　工程基础、契约和存储

**文件** 创建 `pyproject.toml`、`requirements.lock`、`.env.example`、`app/schemas.py`、`app/storage.py`、`app/config.py`、`tests/test_contracts_storage.py`。

**输入与输出** 实现第 4 节对象、`Store` 和配置，供后续任务调用。采用 SQLite 事务保存决定与版本，工件先写临时文件再原子落盘，校验哈希后登记引用。

- [ ] 编写 `test_recommendations_reject_six_items`，断言五条通过、六条验证失败，零条可保存但带缺失状态。
- [ ] 编写 `test_stale_decision_is_rejected`，断言过期修订号产生冲突，已确认内容保持原哈希。
- [ ] 编写 `test_interrupted_artifact_is_not_visible`，模拟落盘或数据库提交失败，断言无成功工件引用。
- [ ] 运行 `python -m pytest tests/test_contracts_storage.py -q`，记录初始失败。
- [ ] 实现契约、存储和配置，锁定经实际解析成功的依赖，忽略数据与密钥文件。
- [ ] 重跑同一命令，预期全部通过，记录安装和验证命令。

### 任务 2　迁移并标准化现有五色模板

**文件** 创建 `templates/anshun-colored/` 下模板、Schema、版式与 `migration-manifest.json`，创建 `tests/test_baseline_template.py`。

**接口** 产生可由 `TemplateVersion` 验证的基准版本，通过 `Store.put_artifact` 登记。稳定模板 ID 建议为 `anshun-monthly-colored`，显示名称使用用户指定名称。

- [ ] 编写 `test_fixed_text_and_all_placeholders_preserved`，断言前四节去除槽位后的固定文本、标点和顺序与旧五色源一致，封面及重复单项槽位有定义。
- [ ] 编写 `test_history_values_are_evidence_only`，断言历史数字与标题仅存在于证据区域，运行槽位无历史默认值。
- [ ] 编写 `test_baseline_is_distinct_from_learned_candidate`，断言新候选版本创建不会替换演示所选基准引用。
- [ ] 运行 `python -m pytest tests/test_baseline_template.py -q`，记录初始失败。
- [ ] 迁移模板，将工作建议上限统一为五条，保留源哈希和差异。用户指定模板可用作演示基准，未确认口径仍保留阻断项。
- [ ] 重跑该文件测试，预期全部通过。

### 任务 3　本地多报告提取、对齐与差异候选

**文件** 创建 `app/template_compare.py`，在 `app/tool.py` 中提供 `parse_report_document`、`compare_report_structures` 工具，创建 `tests/test_template_compare.py`。

**接口** `parse_report_document` 产出 `ParsedDocument` 工件，`compare_reports(documents)` 产出 `TemplateComparison`，其中保存对齐段、相同片段、变化片段、未对齐项、各文件定位与匹配方法。

- [ ] 编写 `test_inserted_paragraph_does_not_shift_every_slot`，断言一份报告多一段时后续同节仍正确对齐，插入段保留条件候选。
- [ ] 编写 `test_same_number_has_independent_occurrences`，断言同一数值出现在不同位置时有独立 occurrence ID，语义待模型检查。
- [ ] 编写 `test_unreadable_docx_is_explicit_error`，断言伪 DOCX、受保护或损坏文件返回 `unreadable_document`，保留原文件，禁止空内容成功。
- [ ] 运行 `python -m pytest tests/test_template_compare.py -q`，记录初始失败。
- [ ] 用 python-docx 提取可读取段落、表格、run 属性和版式，以标题层级和相邻文本锚点对齐，再对节内文本做序列差异。数字和日期检测只形成候选，来源保留原字符偏移。DOC/PDF 暂显示明确格式限制。
- [ ] 重跑测试，预期全部通过，并输出两份人工测试报告的差异工件供检查。

### 任务 4　Agent 定义与可注入模型客户端

**文件** 创建 `app/agent.py`、`app/model_client.py`、`tests/test_model_agents.py`。

**接口** 实现第 4 节 `AGENT_DEFINITIONS` 和 `invoke_agent`，支持模板分析、数据处理、Writer、格式 Reviewer、内容 Reviewer 五个 role ID。

- [ ] 编写 `test_agent_module_contains_declarations_only`，通过 AST 检查无网络、工具运行及工作流导入调用。
- [ ] 编写 `test_model_failure_is_not_success`，模拟超时及非法结构，断言错误、耗时、用量未知状态留痕。
- [ ] 编写 `test_template_analysis_uses_comparison_evidence`，断言请求包含本地匹配和对应原文，响应中的来源必须属于输入材料。
- [ ] 运行 `python -m pytest tests/test_model_agents.py -q`，记录初始失败。
- [ ] 实现可配置的 OpenAI 兼容连接适配，配置 base URL、模型与环境变量密钥。供应商严格输出可用时开启，本地 Pydantic 校验始终执行。提供仅供自动测试的 FakeModel 注入。
- [ ] 重跑测试，预期全部通过。真实模型验证单独记录，不把 FakeModel 结果展示为实际模型分析。

### 任务 5　工具执行器与独立数据工具

最新补充：公开工具目录包含 `cluster_event_themes`，独立于分类字段读取、关键词事件候选与向量近邻工具。新增回归应断言全量表分类为空时不伪造已有分类，聚类候选保留每条记录及来源，并可用 817 行测试表对照评估但不自动确认。

**文件** 完善 `app/tool.py`，创建 `app/tool_executor.py`、`tests/test_tool_executor.py`、`tests/test_data_tools.py`。必要算法可放职责明确的底层模块。

**接口** 实现 `get_tool_specs`、`get_tool_handler`、`execute_tool`。独立工具至少包括 `import_records`、`filter_records`、`resolve_locality`、`propose_keyword_event_candidates`、`propose_vector_event_neighbors`、`classify_records`、`discover_topics`、`calculate_metrics`、`select_materials`、`read_evidence`、`render_chart`、`build_table`。工具参数通过工件引用传递输入，输出均为 `ToolResult`。第一轮形成关键词候选组与未解决记录；第二轮以两者为输入做有界向量近邻检索，补充跨组及隔日跟进报道候选，不能对约 28000 条记录全量两两穷举。

- [ ] 编写 `test_tool_does_not_dispatch_another_business_tool`，以替身 registry 检查工具运行不会隐式调度其他公开业务工具。
- [ ] 编写 `test_counts_preserve_records_and_event_members`，输入 6 条全量记录、其中 3 条负面、负面确认形成 2 个事件，断言三种数量分别为 6、3、2，来源仍有 6 条。
- [ ] 编写 `test_no_warning_rule_requests_review`、`test_unknown_media_level_is_not_invented`，断言缺口进入待确认项。
- [ ] 编写 `test_zero_denominator_is_missing_not_zero_percent`，断言分母为零时有明确缺值语义。
- [ ] 编写 `test_timeout_stops_worker_and_retry_is_idempotent`，断言超时后执行进程停止、无成功结果，重试不重复生成副作用。对可卡住的同步工具使用可终止子进程，网络调用使用客户端超时及取消。
- [ ] 编写 `test_frozen_phase_rejects_fact_mutation`，断言冻结后只读及渲染工具可用，改变事实工具被拒绝。
- [ ] 分别运行 `python -m pytest tests/test_tool_executor.py tests/test_data_tools.py -q`，记录初始失败，再实现并重跑，预期全部通过。

属地结果保留依据与疑难。事件去重按跨平台同事件形成候选，人工可合并、拆分、独立、排除。分类与主题输出完整成员 ID，聚类参数和方法可查。TOP10 缺少排名规则时先交人工。外部检索仅在配置获准来源后启用，缺配置时明确不可用并交人工，不编造天气与活动。

新增回归：`test_follow_up_days_later_is_candidate`、`test_vector_requires_keyword_candidates`、`test_event_tools_do_not_dispatch_each_other`、`test_all_records_members_and_sources_survive_both_rounds`、`test_similarity_does_not_confirm_events`、`test_vector_search_is_bounded_not_all_pairs`。阈值和时间窗口从真实标注样本校准，未校准时仅作为可调演示参数，不宣称准确率或性能收益。

### 任务 6　LangGraph 动态工具循环与可见保底

**文件** 创建 `app/workflow.py`、`app/fallback_policy.py`、`tests/test_dynamic_workflow.py`。

**接口** 实现 `build_report_graph`、`build_fallback_plan`，消费 `ToolDecision`、执行器和持久检查点。

- [ ] 编写 `test_model_can_choose_different_valid_tool_orders`，两套 FakeModel 使用不同但有效的工具顺序，断言均完成目标，流程未强制同一工具链。
- [ ] 编写 `test_finish_requires_goal_coverage`，断言模型宣布完成但缺区县等必需结果时，代码拒绝进入事实确认。
- [ ] 编写 `test_fallback_reason_and_steps_are_events`，模拟连续无进展 3 次，断言模式切换、原因、方案版本与每步结果可查询。
- [ ] 编写 `test_hard_limit_pauses_including_fallback`，工具调用累计 40 次后断言保底也不能继续调用。
- [ ] 运行 `python -m pytest tests/test_dynamic_workflow.py -q`，记录初始失败。
- [ ] 实现第 5 节报告图处理阶段及第 6 节保底，`plan_next` 输出通过联合 Schema 验证。幂等复用与人工等待不计为有效新增进展。
- [ ] 重跑测试，预期全部通过，检查日志能展示两条不同模型工具路径。

### 任务 7　人工研判、恢复与事实冻结

**文件** 完善 `app/workflow.py`、`app/storage.py`，创建 `tests/test_human_resume_facts.py`。

**接口** `Store.apply_decision` 应用人工决定，检查点恢复读取已确认修订。事实确认事务生成不可变 `FactSnapshot`。

- [ ] 编写 `test_business_question_routes_to_human`，断言 Agent 建议不能自动标记人工已确认。
- [ ] 编写 `test_restart_resumes_without_repeating_completed_tools`，重建进程依赖后恢复同一 task ID，断言已完成工具调用与决定未重复。
- [ ] 编写 `test_unresolved_blocker_prevents_freeze`，断言暂缓属地疑难禁止冻结；排除时保存原因后可继续。
- [ ] 编写 `test_fact_correction_creates_new_generation`，断言旧事实、旧稿关联保持可读，新事实产生新任务。
- [ ] 运行 `python -m pytest tests/test_human_resume_facts.py -q`，记录初始失败，再实现并重跑，预期全部通过。

### 任务 8　模板学习图与人工确认

**文件** 完善 `app/workflow.py`，创建 `tests/test_template_workflow.py`。

**接口** 实现 `build_template_graph`，输入多份文档引用，消费任务 3 的匹配工件和任务 4 的模型检查，输出候选 `TemplateVersion`。

- [ ] 编写 `test_local_comparison_precedes_model_analysis`，断言模型收到已有匹配工件，执行顺序事件可查。
- [ ] 编写 `test_unaligned_content_remains_reviewable`，断言模型未处理或无法解释的差异保留待定项。
- [ ] 编写 `test_human_confirmation_creates_version`，断言未确认模板不可用于正式生成，已指定五色基准可独立使用。
- [ ] 运行 `python -m pytest tests/test_template_workflow.py -q`，记录初始失败，再实现并重跑，预期全部通过。

### 任务 9　写作、双审查与定向修订

**文件** 创建 `app/report_validation.py`，完善 `app/workflow.py`，创建 `tests/test_writing_review.py`。

**接口** 实现 `validate_draft`，Writer 返回有来源正文与最多五条建议，修订返回允许字段补丁，Reviewer 输出 `ReviewResult`。

- [ ] 编写 `test_writer_cannot_change_locked_count`，断言修改固定原文或正式数值的补丁被拒绝。
- [ ] 编写 `test_invalid_source_is_blocking`，断言不存在的来源引用阻止审查通过及终稿。
- [ ] 编写 `test_two_review_rounds_survive_restart`，断言含首次最多两轮，重启不清零，失败调用另记。
- [ ] 编写 `test_revision_invalidates_affected_approval`，断言新稿重跑本地验证，内容结论绑定新哈希，格式回归使用剩余额度。
- [ ] 运行 `python -m pytest tests/test_writing_review.py -q`，记录初始失败。
- [ ] 实现模板填充与受限写作、格式和内容审查路由，发现事实错误转人工，超限携字段问题清单交人工。风险分析依据第一部分，建议结合未来窗口与有来源补充材料。
- [ ] 重跑测试，预期全部通过。

### 任务 10　图表、可编辑表格与 Word 导出

以用户新提供的 8 月标色 Word 为源生成带占位符定义的模板 DOCX，并在导出草稿时保留源固定文字、原版式与可编辑 TOP10 表格；旧图表仅作位置参考，不作为 10 月图表。未填槽位与未确认图表必须清楚留在草稿，禁止宣称正式月报完成。

**文件** 创建 `app/export.py`，完成渲染工具，创建 `tests/test_export.py`。

**接口** 实现 `export_docx`，图表工件保存事实哈希、指标路径、样式版本。页面与 Word 复用同一图表产物。

- [ ] 编写 `test_chart_and_docx_share_fact_hash`，断言五类图表、正文、TOP10 引用同一事实版本。
- [ ] 编写 `test_top_table_is_editable_word_table`，读取 DOCX 结构断言存在表格单元格与事件文本，表格未被整体转为图片。
- [ ] 编写 `test_final_export_requires_current_approval`，断言无终审、终审哈希过期、有阻断项时拒绝终稿导出，草稿可携问题清单导出。
- [ ] 运行 `python -m pytest tests/test_export.py -q`，记录初始失败，再实现并重跑，预期全部通过。
- [ ] 产出测试 Word，检查中文字体、图题、分页、图像清晰度和表格可编辑性，记录实际检查方式。当前为报告 Demo，视觉检查范围按执行环境和相关文档技能进行，缺失检查须披露。

### 任务 11　本机 API 与可点击工作台

**文件** 创建 `app/main.py`、`app/static/index.html`、`app/static/app.js`、`app/static/style.css`、`tests/test_api.py`。

**接口** 提供以下 API，写操作以版本校验和幂等 key 防重，长任务返回 task ID。

| 方法与路径 | 行为 |
|---|---|
| POST /api/files | 上传文件，返回 file ID、哈希、可读性 |
| GET /api/templates | 列出五色基准与候选版本 |
| POST /api/template-tasks | file IDs 创建模板学习任务 |
| POST /api/templates/{id}/confirm | 确认候选及版本 |
| POST /api/report-tasks | 模板引用、全量文件引用、报告元信息创建任务 |
| GET /api/tasks/{id} | 阶段、预算、问题、结果、版本、实际模式 |
| GET /api/tasks/{id}/events | 按游标增量获取日志 |
| POST /api/tasks/{id}/decisions | 人工研判决定 |
| POST /api/tasks/{id}/confirm-facts | 确认当前事实候选 |
| POST /api/tasks/{id}/resume | 依据检查点恢复任务 |
| POST /api/tasks/{id}/cancel | 设置取消，终止可取消执行 |
| POST /api/tasks/{id}/approve | 当前稿件终审 |
| POST /api/tasks/{id}/exports | 指定 draft 或 final 导出 |
| GET /api/artifacts/{id} | 受控下载或读取工件 |

- [ ] 编写 `test_duplicate_submission_is_idempotent`，断言双击同请求只产生一次任务和决定。
- [ ] 编写 `test_cannot_approve_stale_draft`，断言页面旧哈希提交产生 409 冲突。
- [ ] 编写 `test_uploaded_filename_cannot_escape_task_directory`，断言路径穿越及文件名冲突不能覆盖任务外文件。
- [ ] 运行 `python -m pytest tests/test_api.py -q`，记录初始失败。
- [ ] 实现后台 worker、API 和页面，页面轮询增量事件。启动固定绑定 `127.0.0.1`。
- [ ] 页面包括模板中心、比对详情、报告提交、运行详情、人工研判、事实预览、稿件审查与导出。以任务 ID 支持刷新恢复，运行详情明确显示动态模式或保底模式及原因。
- [ ] 重跑测试，预期全部通过。手动点击上传、比对、候选确认、现有模板提交、研判、事实确认、终审、下载，记录结果及尚未接通项。

### 任务 12　端到端验收与交接

**文件** 创建 `tests/test_end_to_end.py`、`README.md`、`docs/验收记录.md`，必要时创建本机启动脚本。

**接口** 通过任务 11 的正常 API 走完整链路，使用测试内生成的文档及数据，另设真实模型验收记录。

- [ ] 编写 `test_report_flow_through_public_api`，验证 6 条记录样本、人工疑难、正式事实、最多五条建议、图表及终稿下载。
- [ ] 编写 `test_compare_flow_does_not_replace_demo_template`，验证本地比对到模型检查、人工确认，并保持演示提交使用五色基准版本。
- [ ] 编写 `test_fallback_pause_resume_export`，验证规划失败、可见保底、缺规则交人工、重启恢复、终稿门槛。
- [ ] 运行 `python -m pytest -q`，修复失败并保存实际结果。同步核查独立工具、角色声明和工作流文件分工。
- [ ] 执行 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8765`，在本机完成页面演示与刷新恢复验证。
- [ ] 配置真实模型后单独执行一次模板检查及一次完整报告生成，记录模型、输入、耗时、实际用量、费用已知程度、人工改动及失败。无配置时标为未验证。
- [ ] README 写明安装、启动、配置、演示顺序、停止恢复、数据目录和已知限制。交付源代码、锁文件、模板、启动方式和验收记录，不打包密钥、个人历史任务与模型私密日志。

## 8. 五类重点回归与归属

| 条件 | 预期行为 | 任务 |
|---|---|---|
| 历史报告插入段落、重复数值、损坏 DOCX | 保留错位疑难、独立出现位置、明确可读性错误 | 3 |
| 不可终止工具、重复调用、预算耗尽 | 真正停止执行、幂等、不越过硬上限 | 5、6 |
| 人工确认期间重启或旧页面提交 | 恢复同版本，拒绝过期覆盖 | 1、7、11 |
| 缺预警字段、零分母、未知媒体级别 | 缺失可见并交人工，保持口径 | 5 |
| 同一事件隔日跟进、跨关键词组近邻、约 28000 条规模 | 两轮独立工具显式衔接；保留全部成员与来源；有界近邻；人工确认前不计正式事件 | 5、6、7 |
| 修订后沿用旧审查或终审 | 哈希失配失效，当前版重新确认 | 9、10、11 |

## 9. 演示验收脚本

1. 打开模板中心，展示五色图例、固定文字、槽位语义和输入要求。
2. 上传至少两份可读历史报告，展示本地提取、结构匹配、差异及来源，再展示模型检查意见和候选确认。
3. 回到报告提交，选择现有五色基准，上传当期全量数据，填写月份、发布日期、未来预测窗口与必要统计口径。
4. 展示模型选择工具及调用理由，查看每项结果的范围、方法、来源和耗时。
5. 展示属地或去重疑难及 Agent 建议，由业务人员确认后恢复任务。
6. 核对全量与事件两种口径，确认事实版本，生成正文及最多五条建议。
7. 展示字段级审查与定向修订，核对图表、表格及正文事实引用。
8. 人工终审并导出可编辑 Word，检查五类图表及 TOP10 表格。
9. 用单独测试任务触发规划失败，展示公开保底原因及步骤。恢复中断任务，确认已完成工具未重复。

## 10. 执行交接说明

可将以下文本交给负责构建的 Agent。

> 请在 `D:\分析报告demo` 构建安顺月报工作台 Demo。先阅读本计划及配套架构设计，按任务顺序实现并逐项验证。旧项目只读参考，演示提交使用现有五色模板，多报告创建采用本地代码先匹配、模型后检查。保持 agent.py、tool.py、workflow.py 的职责边界，动态工具选择、可见保底、人工交接、事实冻结和最多五条建议必须通过正常页面入口工作。技术默认方案可做小范围合理调整，记录理由。真实材料或模型不可用时完成可独立验证部分，披露未验证能力。请先给出实施前的材料与环境检查结果，再开始已授权的构建。

计划作者自检已覆盖模板学习、动态工具、保底、人工交接、版本一致性、审查计数、图表 Word、页面和验收。本文尚无代码执行结果，实施者以实际命令及产物补齐验收证据。



## 2026-11-07 用户确认的模板方向

主链路采用“两份不同历史报告比对 → 结构化模板定义与 JSON Schema 候选 → 审阅确认版本 → 数据工具/Writer 按字段所有权填写 → Word 渲染”。模板比对是结构化模板的前置步骤。旧五色模板仅保留为显式选择的历史预览。候选字段含两份来源位置，确认前不能进入结构化写作；未绑定数据字段、未审对齐和图表均显式保留缺失。实现与当前限制见 docs/结构化模板与Schema.md。
