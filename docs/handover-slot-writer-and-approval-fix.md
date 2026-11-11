# 交接文档：槽位写作修复与旧模板终审通道打开

> 变更日期：2026-11-08。涉及旧 8 月模板（`anshun-monthly-colored`）链路的槽位写作（slot_writer）与终审（approve）流程。新结构化模板链路（structured_writer）未改动。
> 验证状态：57 个测试全部通过；另用真实任务数据库副本完成端到端验证（缺失阻断 → 人工填写 → 终审通过）。

## 1. 背景与问题

任务在"多 agent 数据填空"阶段出现两类问题：

1. **模型"证据不足"的合法拒答被当成报错**。slot_writer 的指令明确允许"证据不足则返回空 value 和空 source_refs"，但校验把空值一律 `raise ValueError('invalid_slot_answer')`，导致 B30_RED_02 / B30_RED_05 / B30_YELLOW_06 等槽位以 ValueError 进入 issues。
2. **证据类型与槽位语义错配**。所有槽位统一只给负面/媒体记录前 12 条的 `ref/title/source/category/published`，而三类槽位实际需要其他证据：
   - `computed_judgement`（同比判断）：需要去年同期数据，系统没有；manifest 本就规定"缺去年同期数据时不得生成下降/上升判断"。
   - `theme_cluster`（聚类主题名称）：需要已确认主题分组（`confirmed_theme_groups`）。
   - `narrative_from_sources`（问题概述）：需要已确认事件的标题+摘要+所属主题（`confirmed_event_groups`）。
3. **旧模板链路的终审被永久锁死**（与槽位无关的两道硬编码闸）：
   - `make_preview` 无条件 `preview_only=True`；
   - `approve` 写死 `template_ref=='anshun-monthly-colored' → 409 template_slots_not_fully_resolved`。

注意：旧代码的问题是"静默降级 + 永久阻断"并存，排查时务必看任务事件日志中 `slot_writer_preview` 的 issues 结构（新旧格式不同，见第 3 节）。

## 2. 改动清单

### app/slot_writer.py（重写 write_first_section_slots 主体）

- 新增 `_issue(slot, error_type, message)`：所有 issue 统一携带 `slot_id + semantic + error_type + message`。
- **空答案分流**：`value` 为空且 `source_refs` 为空 → 记 `insufficient_evidence` 缺失项，不再是 ValueError；非空但非法（slot_id 不符、refs 不在证据白名单、含 `{{`/`}}`、有值无 refs）才记校验错误。
- **按 slot_type 分流证据与指令**：
  - `computed_judgement`：直接跳过模型调用，记 `missing_prior_year_data`（省一次注定失败的调用）。
  - `theme_cluster`：证据改为已确认主题分组，每条 `{ref:'theme:'+主题名, theme, record_count, sample_titles(前3条)}`；`confirmed_theme_groups` 缺失时不调模型，记 `insufficient_evidence`。
  - `narrative_from_sources`：证据改为已确认事件（前 30 条），每条 `{ref:代表记录ID, event_id, theme, title, summary(截400字)}`；`confirmed_event_groups` 缺失时同上。
  - 其他类型（B17/B26 等 existing_field/source_text）：维持原媒体/负面记录证据逻辑。
- 新增 `theme_of` 映射（记录ID → 主题名），由 `confirmed_theme_groups` 的 member_ids 构建。

### app/workflow.py

- `make_preview_with_charts`：slot_writer 返回后，把 `writer_issues`、`missing_fields`（缺失 slot_id 列表）写入任务 metadata 再 `put_task`——旧模板链路的缺失信息由此可被 draft-view 读取。
- `make_preview`：`preview_only` 由无条件 True 改为按 `missing_fields` 计算；`missing_fields` 不存在（旧任务）时保持 True，避免旧草稿被意外放行。

### app/main.py

- 新增 `POST /api/tasks/{task_id}/slot-values`，请求体 `{'values': {slot_id: 文本}}`：
  - 仅限 `anshun-monthly-colored` 模板；slot_id 必须在 `WRITER_SLOT_IDS`；值非空且不含 `{{`/`}}`。
  - 写入 `draft['slot_values'][slot_id]={'value':…,'source_refs':['human_edit']}`（人工内容与模型内容可区分）。
  - 重算 `content_hash`，以 `human_filled_draft` 类型保存新版本；从 issues/missing 中移除已填槽位；全部填完则 `preview_only=False`；记录 `human_slot_values` 事件。
- `approve`：删除旧模板一刀切封禁，改为检查 9 个 `WRITER_SLOT_IDS` 在 draft.slot_values 中均有非空 value（模型或人工均可），缺失时 `409 writer_slots_unfilled:<id列表>`。其余校验（draft_hash、validate_draft、blocking 审阅项）不变。

### app/static/app.js（openDraft）

- 缺失项弹窗：issues 逐条显示"槽位 ID + 语义 + 原因"，替代原"详见日志"。
- 旧模板（无 definition）且存在缺失时：渲染"人工填写缺失槽位"表单（每槽位语义说明 + textarea + "保存人工填写"），保存调用 slot-values 接口后刷新任务并重新打开弹窗；缺失清零后出现"确认报告并终审"。

## 3. 数据契约变化（排查时以此判断新旧代码）

- 新版 issue：`{'slot_id','semantic','error_type','message'}`；旧版只有 `{'slot_id','error_type'}`。
- 新 error_type：`insufficient_evidence`、`missing_prior_year_data`、`template_paragraph_missing`；ValueError 仅表示"非空但非法"。
- 事件 `human_slot_values`：人工填写审计。
- 任务 metadata：`writer_issues` / `missing_fields` 现在在旧模板链路也有值。

## 4. 操作步骤（UI）

1. **重启服务**（必须；此前一次"重跑仍报错"就是因为服务未重启、仍跑旧代码）。
2. 任务详情点"重新生成报告"。
3. 点"查看报告与缺失项"，对模型填不上的槽位（如同比判断）在文本框人工补全 → "保存人工填写"。
4. 缺失清零后黄色横幅消失，点"确认报告并终审"。

## 5. 遗留事项 / 后续建议

- 主题槽位 value 直接引用已确认主题名，主题名本身润色仍走人工。
- `theme:` 前缀的 source_refs 是主题级引用，不是记录 ID；下游如需记录级溯源，需另做展开。
- 正式审查 agent（format_reviewer / content_reviewer）在 agent.py 中定义但仍未接线，终审目前仍只有 validate_draft 本地校验。
- 结构化模板链路（structured_writer）的缺失仍只能重跑，人工补全接口目前仅覆盖旧模板 9 个写作槽位。
- 测试环境注意：Windows 沙箱下 pytest 需项目内临时目录，使用
  `$env:TEMP='D:\分析报告demo\data\tmp'; $env:TMP=...; python -m pytest tests -q --basetemp=data\tmp\pytest`。
