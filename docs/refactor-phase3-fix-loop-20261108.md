# 重构阶段三交接：审查修正回路 + 图结构测试（2026-11-08）

> 前置：阶段一 reviewer 接线、阶段二图节点化。回滚点 `backups/pre-refactor-20261108/`。
> 验证：全套 **90 项测试通过**（新增 test_graphs.py 3 项；test_frozen_writer.py 1 处断言按新行为更新）。

## 实现目标

审查不通过不再只是"有 blocking 项"，而是有明确的状态回路：
```
write_draft → format_review → content_review
   ├─ 有未解决 blocking 审查项 → awaiting_writing_fix（待修正审查问题）
   │     ├─ 人工修改稿件（slot-values / edit_structured）→ 自动重新双审查 → 重新判定
   │     └─ 人工解决审查项（decisions 端点 confirm/defer）→ 重新判定
   └─ 无 blocking → awaiting_final_review（可终审）
```

## 改动文件

### app/workflow.py
- 新增 `refresh_review_phase(store, task_id)`：draft 存在且非 approved/processing/analyzing 时，有未解决 blocking writing_review 项 → `awaiting_writing_fix`，否则 `awaiting_final_review`；phase 变化写事件。approved 任务不会被回退。
- `make_preview_with_charts`（写作图入口）在图执行后调用 refresh，即"写作+双审查"完成时立即进入正确状态。

### app/main.py
- `decisions` 端点：人工解决审查项后调用 refresh_review_phase（全部解决 → 回到 awaiting_final_review）。
- `fill_slot_values` 结构化分支：人工编辑后**自动重跑双审查** + refresh（旧版编辑后审查报告与草稿 hash 脱节的问题消除）；旧模板分支同样补 refresh。

### app/writing_review.py
- `edit_structured` 可编辑 phase 集合加入 `awaiting_writing_fix`（否则进入修正状态后反而无法人工改稿）。

### app/static/app.js
- 阶段标签新增 `awaiting_writing_fix: '待修正审查问题'`。

### tests/test_graphs.py（新增 3 项）
- 报告图结构断言：validate_input / data_processing / event_analysis / finalize 节点存在。
- 写作图结构断言：validate_input / write_draft / format_review / content_review 节点存在。
- 写作图端到端（合成模型 + monkeypatch 写作节点）：验证 format_reviewer→content_reviewer 顺序调用、blocking 发现 → awaiting_writing_fix、人工解决 → awaiting_final_review。

### tests/test_frozen_writer.py（断言更新）
- 人工最终修正现在会触发 format+content 重审，旧断言"模型调用数不变"更新为"新增两次 reviewer 调用"，adapter 对 reviewer 角色返回空 issues。**这是本重构唯一一处既有测试语义变化，属预期行为变更。**

## 终审与 UI 表现

- `can_approve` 要求 phase=='awaiting_final_review'，所以 awaiting_writing_fix 下终审按钮不出现；approve 端点还有 unresolved_blockers 硬闸，双保险。
- 审查问题在"查看报告与缺失项"中可见（阶段一已接入 draft_view.issues）。

## 三阶段总览

1. 阶段一：reviewers.py + 提示词 + 审查闸口（85+2 测试）。
2. 阶段二：报告图/写作图真实节点化，reviewer 成为图节点（87 测试）。
3. 阶段三：awaiting_writing_fix 修正回路 + 图结构测试（90 测试）。

## 遗留（未做，供后续决策）

- LangGraph checkpointer/interrupt 原生中断恢复：仍采用 phase+API 轮询的人工节点策略。
- format/content reviewer 只看 draft_text + facts 摘要，不做全文证据逐字核对；更严的核对需要证据抽取工具。
- data_processor 动态规划循环保留在 _data_processing 节点内部，未进一步拆成图节点。
