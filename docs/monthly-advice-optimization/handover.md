# 月度工作建议优化交接记录

日期：2026-11-09

> ✅ **已全部完成（2026-11-09 续）**：剩余 3 项月度建议任务 + 第二阶段双审核循环修复均已实现并验证，全量测试 196 passed。详见文末「## 10. 完成记录」与 `execution-ledger.md`。以下 1–9 节为中断前的原始交接内容，仅作历史参考。

## 1. 当前结论

本任务尚未完成，当前代码不可作为最终验收版本。

- 任务 1（统一 4—5 条口径、分级研究补足）已完成，并曾通过聚焦回归。
- 任务 2 的主体功能已实现：程序继承 `basis_type`、单条校验、合格项锁定、失败类别定向退修。
- 任务 2 仍有 3 个 Important 边界问题未修复。
- 任务 3（部分结果工件、状态分类、证据不足误标）尚未实现。
- 任务 4 的固定回放测试代码已写入，但生产实现尚未配套完成。
- 最近一次实现过程被用户中断。中断后只核对了文件，没有继续修改业务代码，也没有运行新增测试或完整测试。
- 没有提交 Git；当前环境此前执行 `git status` 时找不到可用的 `git` 命令。

用户最新要求：后续如继续，应连续完成剩余三项，中间不要逐任务多轮审查，最后只做一次统一测试与审查。

## 2. 已批准规格

- `docs/monthly-advice-optimization/spec.md`
- `docs/monthly-advice-optimization/tasks.md`
- `docs/monthly-advice-optimization/checklist.md`

核心约束：

1. 候选比较 5—8 类，研究目标 5 类、至少 4 类合格，最终建议 4—5 条。
2. `basis_type` 由程序按研究选题继承，不信任模型抄写或 Schema 默认值。
3. 合格条目锁定，只退修失败类别；不得放宽交叉引用、数字、年份、高发、复现、季节事实校验。
4. Writer 后续工具新资料不得自动扩张原选题依据。
5. 自动流程不足 4 条时不得包装成最终完成；保留合格项和失败正文，转人工补全。
6. 不修改双审核图结构，不自动改写历史草稿。
7. 不得为让测试通过而放宽 `validate_values` 的来源白名单、字段所有权、嵌套标记及其他 Schema 约束。

## 3. 已完成并验证的主体改动

### 3.1 研究与提示词

涉及：

- `app/section_two.py`
- `app/historical_research.py`
- `app/agent.py`
- `app/template_review.py`
- `app/source_binding.py`
- `app/structured_writer.py`

已具备：

- 候选最少 5 类、研究至少 4 类、Writer 输出 4—5 条。
- 无本地历史网页时可使用明确模型季节机制补足，目标 5 类。
- 历史案例、官方季节资料、模型季节机制、已核实地方活动仍按原有分级和真实性规则处理。
- 提示词明确“模型只选择类别，依据性质由程序继承”。

### 3.2 单条校验和退修

`app/section_two.py` 已新增：

- `OutlookItemValidationError`
- `render_outlook_item(item, topics, window)`

`render_outlook()` 仍负责整组 4—5 条及重复类别等组级检查。

`app/structured_writer.py` 已具备：

- `StructuredOutlookRepairAnswers` 后续轮次允许 1—5 条。
- 按 `category` 找到研究 topic 后覆盖/补齐 `basis_type`。
- `outlook_locked`、`outlook_invalid`、`outlook_positions`、`outlook_repair`。
- 失败条目保留原始正文、序号、类别、错误码、错误信息和该类别允许引用。
- 纠错 payload 提供该类别允许的数字资料编号。

此前实际验证结果：

- 第一阶段新增回归在旧实现上为预期的 4 个失败，修复后通过。
- Writer/section_two 聚焦套件曾达到 70 项通过。
- `tests/test_seasonal_review_fallback.py` 曾达到 6 项通过。
- 后续统一口径及提示词回归累计记录为 100 项通过。

这些是通过时的历史结果，不代表当前新增测试已经通过。

## 4. 当前尚未修复的 3 个 Important

全部集中在 `app/structured_writer.py`。

### 4.1 后续轮次不允许新合格 topic 类别补入

当前约第 264—270 行：

- `retry_categories` 只包含原失败类别。
- `accepted` 和循环跳过条件要求后续条目必须属于 `retry_categories`。
- 因此首轮 3 条合格、1 条失败后，下一轮即使返回第 5 个合格 topic，也会被跳过，无法补足 4 条。

目标：

- 后续既允许失败类别修复，也允许尚未锁定、且属于合格 topic 的新类别补入。
- 已锁定类别不得被改写。
- 非 topic 类别仍必须拒绝。

### 4.2 5 条合格遇旧模板 `maxItems=4` 会空转

当前约第 288—313 行：

- 5 条全部锁定后直接提交 5 条。
- `validate_values` 因旧模板 `maxItems=4` 拒绝。
- 后续轮次所有类别又已锁定，无法恢复。

目标：

- 若 5 条均合格而模板上限为 4，可按稳定位置确定性选择前 4 条提交。
- 不得改写正文，不得删除或篡改锁定项来规避校验。
- 不得放宽 `app/structured_template.py` 中 `validate_values` 的其他约束。

### 4.3 人工兜底 candidate 未合并锁定项和最新失败项

当前约第 229、262、315—334 行：

- 普通成功解析但语义校验失败的响应没有统一保存为最新 `candidate`。
- `candidate` 主要只在 `SourceBindingError` 时赋值。
- 最终预览只读取当前 candidate 的 `outlook_items`，没有合并 `outlook_locked`。
- 少于 4 条的合并候选还会被现有长度检查丢弃。

目标：

- 候选合并保留锁定项与最新失败项正文。
- 按稳定 position 排序，`category` 不重复。
- 工件同时保存 `valid_items`、`invalid_items`、合并后的 `outlook_items` 和可人工核对的 `value`。

## 5. 中断前已经写入、但尚未验证的新测试

主要位于 `tests/test_section_two.py`：

1. `test_writer_allows_new_topic_category_while_locking_valid_items`
2. `test_writer_deterministically_submits_four_of_five_for_legacy_template`
3. `test_writer_pending_candidate_merges_locked_and_latest_invalid_item`
4. `test_save_draft_marks_only_actual_research_insufficiency`
5. `test_fixed_replay_inherits_basis_and_locks_first_round_valid_item`
6. `test_fixed_replay_preserves_partial_results_and_source_errors_for_human_review`

辅助工厂也已扩展：

- `outlook_writer_fixture(..., topic_count=4, max_items=5, history_packet=None)`
- `fixed_exchange(short)`
- `fixed_outlook_history()`
- `replay_fixed_exchanges(monkeypatch)`

`tests/test_core.py::test_five_recommendation_limit` 也已改为期望：

- 空 recommendations 不再自动设置 `missing_recommendation_evidence=true`。
- 显式传入 true 时仍保留 true。

重要：这些新测试是在中断前写入的，未实际运行确认 RED/GREEN。继续时先运行它们，区分测试夹具问题和生产问题；不能直接声称它们已经通过。

## 6. 任务 3 尚需实现

### 6.1 保存每轮候选和部分结果

在 `app/structured_writer.py`：

- 每次成功解析 `outlook_items` 后保存候选，不限于 `SourceBindingError`。
- 三轮后仍不足 4 条时，保存合格项、失败项原始正文、审计字段和逐项错误。
- `writer_pending_sources` 工件需与当前 `fact_ref`、`template_ref` 匹配，供 `app/review_service.py::draft_view` 展示。
- 部分结果不得进入 `slot_values` 冒充已完成字段。

### 6.2 区分真实状态

- 纯引用绑定问题且有正文：`writer_source_pending`。
- 其他正文/语义校验问题且有正文：`writer_validation_pending`。
- 完全没有可用正文：`writer_unfilled`。
- 研究确实不足：`historical_evidence_insufficient`。

### 6.3 修正证据不足误标

当前 `app/schemas.py::DraftVersion.mark_missing` 仍在 `recommendations=[]` 时自动设置 `missing_recommendation_evidence=true`，需要移除该推断。

当前 `app/structured_writer.py::save_draft` 创建 `DraftVersion` 时没有根据 issue 显式设置该字段，需要改为只有实际 `historical_evidence_insufficient` 才设置 true。

当前 `app/report_validation.py::validate_draft` 对空建议只显示“缺少有依据的工作建议，保持零条并交人工”，需要按实际 draft 状态区分：

- 研究依据不足。
- 建议写作/校验未完成，转人工。

页面应展示真实 `writer_issues`，不得把 Writer 失败统一显示成研究证据不足。

## 7. 固定回放要求

固定输入位于 `data/artifacts/`：

- `model_exchange-f99ce0c4d4c33f87688b.json`
- `model_exchange-5c31307cb95b9732fd35.json`
- `model_exchange-ab56a2481bdb93453bd8.json`

不得用新联网结果替代。

应验证：

1. 第 2 轮缺少 `basis_type` 时，程序继承 `seasonal` 并可通过。
2. 第 1、3 轮只有安全生产等错误类别进入退修，其他合格项保留。
3. 若最终仍不足 4 条，保留合格项、失败正文及具体错误，不误设 `missing_recommendation_evidence=true`。
4. 交叉类别引用、编造数字、虚构高发、重复类别仍被拒绝。
5. 自动不足 4 条不得进入最终完成状态。

## 8. 建议继续顺序

按用户要求，一次连续完成，不做逐任务多轮审查：

1. 先运行新增聚焦测试，记录真实失败。
2. 修复后续新类别补入和旧模板 `maxItems=4`。
3. 实现候选合并、部分结果工件和三种 Writer 状态。
4. 修正 `DraftVersion`、`save_draft`、`report_validation` 的证据不足分类。
5. 让固定回放测试通过，检查真实性拒绝规则未放宽。
6. 全部完成后只做一次统一测试与审查。

建议命令：

```powershell
python -m pytest tests/test_section_two.py tests/test_core.py -q
python -m pytest tests/test_section_two.py tests/test_seasonal_review_fallback.py tests/test_frozen_writer.py tests/test_source_binding.py tests/test_structured_template.py tests/test_agent_prompts.py -q
python -m pytest tests/test_pause_and_polling.py -q
python -m pytest -q
```

只有实际运行并得到结果后，才能报告通过数量。不要重复无意义地运行完整套件。

## 9. 交接注意事项

- 当前工作区包含未提交改动，不要回滚无关文件。
- 不要根据旧备份目录判断当前实现；以 `app/` 和 `tests/` 当前文件为准。
- 不要创建新的最终状态或额外审核图分支。
- 不要自动重新生成或覆盖历史报告。
- 最终报告应列明修改文件、固定回放结果、聚焦测试和完整测试的精确输出，以及任何遗留问题。

## 10. 完成记录（2026-11-09 续）

### 10.1 完成内容

**A. 月度建议剩余 3 项**

1. 单条退修 3 个边界问题（`app/structured_writer.py`）：
   - 边界1 新合格类别补入：`topic_categories` 允许后续轮补入尚未锁定且属于合格 topic 的新类别，非 topic 类别仍拒绝。
   - 边界2 旧模板 `maxItems=4`：5 条全合格时按稳定 position 确定性截前 4 条，不改正文/不删锁定项。
   - 边界3 兜底 candidate：合并 `outlook_locked` + 最新 `outlook_invalid`，按 (position, valid-first) 排序，category 去重。
2. 保留失败现场 + 三态（`app/structured_writer.py`）：`writer_pending_sources` 工件含 `valid_items`/`invalid_items`/`outlook_items`/`value` + `fact_ref`/`template_ref`；三态 `writer_source_pending`/`writer_validation_pending`/`writer_unfilled`；不足 4 条转人工，不静默完成。
3. 证据不足修正：`app/schemas.py` 移除 `DraftVersion.mark_missing` 自动推断；`save_draft` 仅对 `historical_evidence_insufficient` 显式设 `missing_recommendation_evidence`；`app/report_validation.py::validate_draft` 区分「研究依据不足」vs「写作/校验未完成转人工」。

**B. 第二阶段双审核循环修复**（`app/workflow.py` + `app/reviewers.py`）

- 目标流转：格式循环（≤5 轮或无意见）→ 内容循环（≤上限或无意见）→ 最后一次格式校验 → 人工审核。
- 根因修复：内容退修成功后经 `style_route` 重入 `content_review`，不再重进 `format_review`。
- 新增 `final_format_review` 节点（单次格式校验，无条件边 → `await_final_review`，无回边到 `revise_draft`）。
- `format_route` 设 `format_stage_completed`；`run_reviewer` 内容闸门加该标志；`begin_run` 重置瞬态路由标志（重跑不误路由）。

### 10.2 修改文件

- `app/structured_writer.py`、`app/schemas.py`、`app/report_validation.py`
- `app/workflow.py`、`app/reviewers.py`
- `tests/test_writing_graph.py`（4 处断言更新 + 新增 `test_final_format_review_never_loops_back_to_revision`）
- `app/static/writing-review.js`、`app/static/app.js`（延迟项收尾：`final_format_review` 阶段标签/状态列表）

### 10.3 测试结果（精确输出）

- 目标测试：`python -m pytest tests/test_section_two.py tests/test_core.py -q` → **35 passed**。
- 月度回归：6 文件套件 → **56 passed**。
- 写作图 + 季节回退：`tests/test_writing_graph.py tests/test_seasonal_review_fallback.py` → **20 passed**。
- 全量：`python -m pytest -q` → **196 passed**（1 warning，LangGraph deprecation，非本项目）。
- 固定回放（不联网）：`test_fixed_replay_inherits_basis_and_locks_first_round_valid_item`、`test_fixed_replay_preserves_partial_results_and_source_errors_for_human_review` 均通过。

### 10.4 代码审查结论

- **A 模块 reviewer**：无 Critical。1 Important（#1 建议 invalid 排序键改 `outlook_positions`）已**驳回**——固定回放明确要求按最新轮顺序（`value[2]==安全生产`，ab56a 中安全生产在 index 2）；改回会让该测试变红。3 Minor：#2（invalid 按 category 去重）已修；#3（工件 status 命名未对齐 `writer_*`，无消费方）、#4（截断第5条无审计痕迹）记录为延迟。
- **B 模块 reviewer**：Ready to merge（Yes），无 Critical/Important。采纳 #5（`style_route` 显式路由、未知值安全回落 format）+ 内容闸门注释 + 图结构断言测试；其余 Minor 为既有措辞/命名/遥测漂移，记录为延迟。

### 10.5 遗留 / 延迟项（已收尾，2026-11-09 二次续）

原记录的延迟项已全部处理：

- ✅ 工件 `status` 字段已对齐 `writer_source_pending`/`writer_validation_pending`（与 issue 的 `writer_*` 一致）。
- ✅ `maxItems=4` 截断被丢弃的第 5 条现写入 `second_section_plan` 工件的 `dropped_items` 字段（含 category/text/position），供追溯。
- ✅ `format_forward_reason`（`limit`/`declined`/`error`）写入 run 元数据与事件；事件类型由 `format_review_limit_forwarded` 更名 `format_review_forwarded_to_content` 并附 `reason`，不再把 writer-declined 混称「上限」。
- ✅ `format_stage_completed` 更名 `format_stage_concluded`（更准确涵盖通过/上限/错误/拒绝四种收尾）。
- ✅ 未用的 `maximum_rounds:5` 已移除，并补注释说明每阶段预算为「5 次退修尝试」。
- ✅ `final_format_review` 节点使用独立 phase `final_format_review`（已加入 `ACTIVE_PHASES` 与前端 `phases`/`writingBusy`/`graphNames`），遥测可区分首轮格式与最终格式校验。

以上改动后全量测试仍为 **196 passed**（前端 JS 为静态文件、随刷新生效，无 pytest 覆盖，改动为纯标签/列表追加，风险低）。

### 10.6 备注

- 无 git，已备份原始 `app/` + `tests/` 至 `backups/monthly-advice-fix-20261109/`。
- 未新建审核图分支、未改写历史草稿、未放宽任何 Schema/真实性校验约束。

