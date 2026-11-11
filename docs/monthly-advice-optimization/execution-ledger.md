# 执行台账 — plan: 月度建议优化 + 双审核循环修复

- 开始：2026-11-09（承接 handover.md，日期 2026-11-09）
- 环境：Python 3.14.9 (D:\miniconda3\python.exe)、pytest 9.0.3、无 git
- 执行方式：原生实现；每完成一个功能模块交独立「代码 reviewer」子代理审查后修正，再进下一模块。
- 备份：`backups/monthly-advice-fix-20261109/`（app/ + tests/ 全量拷贝，无 git 的回退网）

## 模块清单
- A1 基线 + 单条退修 3 边界问题（structured_writer.py）
- A2 保留失败现场 + 三态 + 证据不足修正（structured_writer.py/schemas.py/report_validation.py/review_service.py）
- A3 固定回放 + 目标回归
- B1 双审核循环路由重构（workflow.py/reviewers.py）
- B2 图测试更新 + 全量回归
- B3 交接记录

## 进度
- A1 完成（基线 1/7 绿 → 修复退修 3 边界后 7/7）：边界1 新类别补入（`topic_categories` 允许非重试合格 topic）；边界2 `maxItems=4` 时确定性截前 4 条；边界3 兜底 candidate 合并锁定+最新失败（`outlook_locked`+`outlook_invalid` 按 (position, valid-first) 合并）。
- A2 完成：`writer_pending_sources` 工件含 valid_items/invalid_items/outlook_items/value + fact_ref/template_ref；三态 writer_source_pending/writer_validation_pending/writer_unfilled；schemas.py 移除 mark_missing 自动推断、save_draft 显式按 issue 设 missing_recommendation_evidence；report_validation.validate_draft 区分「研究依据不足」vs「写作/校验未完成转人工」。
- A3 完成：固定回放 2 项通过；目标套件 `test_section_two test_core` 35 passed；月度回归套件（6 文件）56 passed。
- Ruling: 合并排序键 = (position, valid-first)，invalid 条目 position 用 item_index（最新轮索引）而非 outlook_positions，以匹配固定回放中模型重排类别的真实顺序（ab56a 中安全生产/自然灾害对调）。
- 下一步：A 模块代码审查 → B1 双审核循环重构。
- B1 完成：格式循环→内容循环→最后一次格式校验→人工。`format_route` 设 `format_stage_completed`；`run_reviewer` 内容闸门加该标志；`begin_run` 重置瞬态路由标志；`review_route` 内容完成→`final_format`；`workflow.build_writing_graph` 增 `style_route`(按 repair_stage 路由)、`final_format_review` 节点、`after_revision` 内容收尾→`final_format`。
- B2 完成：更新 test_writing_graph 4 处断言（节点序列加 final_format_review；3 处 call 序列改「内容退修不再中途重查格式、末尾最终格式校验」）；test_format_must_pass... 更名 test_format_loop_then_content_loop_then_final_format_check。
- 全量回归：`python -m pytest -q` → 195 passed。
- 待办：A 模块 reviewer 反馈处理；B 模块 reviewer；B3 交接记录。
- A 模块 reviewer 结果：无 Critical；1 Important（#1 invalid 排序键）、3 Minor（#2 去重/#3 状态命名/#4 第5条审计）。
- Ruling（#1 驳回）：invalid 排序键保留 `item_index`（最新轮索引），不用 `outlook_positions`。理由：固定回放 `test_fixed_replay_preserves_partial_results_and_source_errors_for_human_review` 明确断言 `value[2]==安全生产`（ab56a 中安全生产在 index 2，模型确实重排了类别），即要求按最新轮顺序；改回 outlook_positions 会令该测试变红。代价若错：若未来产品要求「候选严格按首轮顺序展示」，需另加规则并同步改该测试。
- A #2 已修复：`invalid_entries` 按 category 去重（spec「category 不重复」）。
- A 延迟 minor：#3 工件 `status` 命名未对齐 `writer_*`（无消费方、纯命名）；#4 maxItems 截断的第5条无审计痕迹（规格授权确定性截断，第5条仍在内存 outlook_locked 中）。
- B 模块 reviewer 结果：Ready to merge（Yes），无 Critical/Important。采纳 #5 style_route 显式路由（未知值回落 format）+ content gate 注释 + 图结构断言测试 `test_final_format_review_never_loops_back_to_revision`。其余 Minor 为既有措辞/命名/遥测漂移，记录延迟。
- B3 完成：handover.md 更新（§10 完成记录），记录修改文件、固定回放结果、聚焦/完整测试精确输出、审查结论与遗留项。
- 最终：`python -m pytest -q` → 196 passed。全部任务完成。
- 收尾延迟项（二次续）：A#3 status 命名对齐 writer_*；A#4 截断第5条写入 second_section_plan.dropped_items；B#3 加 format_forward_reason + 事件更名 format_review_forwarded_to_content；B#4 重命名 format_stage_concluded；B#2/#6 移除 maximum_rounds + 注释；B#7 final_format_review 独立 phase（ACTIVE_PHASES + 前端 phases/writingBusy/graphNames）。全量仍 196 passed。
