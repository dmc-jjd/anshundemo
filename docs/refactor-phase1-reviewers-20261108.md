# 重构阶段一交接：format/content reviewer 接线（2026-11-08）

> 回滚点：`backups/pre-refactor-20261108/`（重构前的 app/tests/scripts/templates 完整快照）。
> 验证：全套 85 项既有测试通过；新增 `tests/test_reviewers.py` 2 项通过。

## 实现目标

此前 `format_reviewer` / `content_reviewer` 只在 agent.py 注册、零调用，终审只有本地 validate_draft。本阶段让两个 reviewer 在**每次生成草稿后真实参与审查**，并把审查结果接入既有终审批次。

## 改动文件

### 新增 app/reviewers.py
- `ReviewIssue {target_id, issue_type, message, severity, evidence_refs}`、`ReviewReport {issues[]}`：两个 reviewer 共用的结构化输出 Schema。
- `review_draft(deps, task_id)`：
  - 组装 `draft_text`（章节正文 + 槽位值，槽位带语义名；旧模板读 manifest，结构化模板读 confirmed template 的 display_name）。
  - `format_reviewer` 输入 draft_text + template_rules；`content_reviewer` 输入 draft_text + facts（metrics / confirmed_event_count / top10 标题梗概条数）。
  - 每条 issue 转为 `kind='writing_review'` 的 review_item，severity=blocking 时 `blocking=True`。
  - **reviewer 调用失败/不可用 → 生成 blocking 审查项，绝不静默通过**。
  - 每次审查先清除旧的 writing_review 项再写入（重审幂等，不会累积）。
  - 结果存 `metadata['review_report']`（含 draft_hash 和各 reviewer 状态），并置 `writing_review_required=True`；写 `writing_review` 事件。

### app/agent.py
- 新增提示词 `format_reviewer.review`（固定文字/占位符/编号单位标点/列表格式/残缺句）与 `content_reviewer.review`（数字、比例、排名、事件数与 facts 核对；TOP10 一致性；无法核实的表述标 warning 而非臆断错误）。

### app/workflow.py（make_preview_with_charts）
- 旧模板与结构化模板两个分支都在草稿生成后 `await review_draft(...)`，即"写作 → 双审查"成为标准路径。

### app/main.py
- `approve` 新增闸门：`writing_review_required` 为真但无 `review_report` → 409 `writing_review_required`。审查发现的 blocking 项由既有 `unresolved_blockers` 检查（L602 附近）自动拦截，人工通过既有 review decision 端点解决。
- 人工填写槽位 `fill_slot_values` 改为 async，保存后**自动重跑双审查**，避免审查报告与新草稿 hash 脱节。

### app/review_service.py（draft_view）
- `issues` 现在合并 writer_issues 与未解决的 writing_review 项（带 reviewer 名、target_id、blocking 标记），UI"查看报告与缺失项"可直接看到审查问题。

## 审查问题的处理方式（给人和其他 agent）

- blocking 审查项 → 终审 409 `unresolved_blockers`；解决方式：修改稿件后重跑写作（自动重审），或通过 review decision 人工 confirm/defer。
- reviewer 不可用（模型未配置/超时）→ blocking 项，提示重试或人工核查后解决。
- 终审阻断链完整顺序：preview_only → writing_review_required → 槽位缺失 → stale_draft → validate_draft → unresolved_blockers。

## 未包含（属于后续阶段）

- 审查不通过的图内修正回路（阶段三）。
- run_report 的图节点化（阶段二）；reviewer 目前仍由 workflow 函数顺序调用，尚未成为图节点。
