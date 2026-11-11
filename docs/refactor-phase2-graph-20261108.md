# 重构阶段二交接：写作/处理流程拆为真实 LangGraph 节点（2026-11-08）

> 前置：阶段一 `docs/refactor-phase1-reviewers-20261108.md`。回滚点 `backups/pre-refactor-20261108/`。
> 验证：全套 87 项测试通过（含阶段一新增的 reviewer 专项）。

## 实现目标

此前 LangGraph 只是壳：`validate_input → process` 两节点，process 内部是单体 run_report。本阶段把处理、事件分析、写作、双审查全部变成图节点，图结构真实反映业务流程。

## 改动文件（全部在 app/workflow.py + app/reviewers.py）

### 报告处理图 build_report_graph（重写）
节点与边：
```
START → validate_input
validate_input --(route_entry)--> data_processing 或 END
  # route_entry：human_review_final / 已有 fact_ref / phase 不在可处理集合 → 直接 END（保持原早退语义）
data_processing --(route_after_processing)--> event_analysis 或 finalize
  # route_after_processing：ANALYSIS_PREREQS={calculate_metrics, group_events, cluster_event_themes}
  # 齐备且未取消 → event_analysis，否则 finalize（failed/cancelled 由 finalize 判定）
event_analysis → finalize → END
```
- 原 run_report 拆为三个可复用节点函数：`_data_processing`（动态规划循环 + 公开保底工具步骤）、`_event_analysis`（analyse_events，pending_model → analysis_pending）、`_finalize_report`（cancel/failed/awaiting_review + data_review 审阅项）。
- `run_report` 保留为**兼容包装**：按同一路由顺序调用这三个函数，行为与图一致；旧调用方不受影响。
- GraphState 仍只有 task_id/phase；SQLite 是唯一事实源，节点只读写在库任务状态。

### 写作图 build_writing_graph（新增）
```
START → validate_input（必须为 report 且已冻结事实）
      → write_draft（旧模板 slot_writer+图表 / 结构化 structured_writer）
      → format_review → content_review → END
```
- `run_writing_graph` 为执行入口；`make_preview_with_charts` 变成写作图的对外包装，main.py 等调用点**无需修改**。
- 原 make_preview_with_charts 的写作部分改名 `_write_draft`，不再内部调用 reviewer。
- 两个 reviewer 是独立图节点，通过 `review_draft(..., roles=('format_reviewer',))` / `roles=('content_reviewer',)` 分别执行。

### app/reviewers.py
- `review_draft` 增加 `roles` 参数：只审查指定角色；清理旧 writing_review 项时按 reviewer 过滤（单角色重审不会清掉另一角色的结论）；`review_report.reviewers` 按角色合并，draft_hash 始终取当前草稿。

## 行为保持不变的部分

- 模板图 build_template_graph 未动。
- 人工节点仍采用"phase + API 轮询"（未接 LangGraph checkpointer/interrupt，属后续可选增强）。
- 终审闸口链不变：preview_only → writing_review_required → 槽位缺失 → stale_draft → validate_draft → unresolved_blockers。

## 排查提示

- 图节点执行顺序问题看 `phase` 事件与 `writing_review` 事件；报告图 early-return 现在由 route_entry 决定，任务不处理时图直接 END，不写任何状态。
