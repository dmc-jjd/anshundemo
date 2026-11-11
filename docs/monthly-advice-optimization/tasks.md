# 月度工作建议优化实施任务

状态：已批准，正在实施。

## - [x] 任务 1：统一 4—5 条口径和分级研究补足

- 修改 `app/section_two.py`：候选最少 5 类、合格选题最少 4 类、成稿 4—5 条。
- 修改 `app/historical_research.py`：研究成功门槛改为 4 类，季节兜底目标为 5 类。
- 修改 `app/structured_writer.py`、`app/source_binding.py`：两个 Writer Schema 改为 4—5 条。
- 修改 `app/agent.py`、`app/template_review.py`：提示词、模板策略、字段说明同步。
- 保留 A/B/C 分级依据和禁止编造规则。

验收：4/5 条边界测试通过；无历史网页时能补足至少 4 类且无虚构事实。

## 任务 2：修复确定性元数据和单条退修

- 在 `app/section_two.py` 抽取单条校验/渲染 helper。
- 在 `app/structured_writer.py` 按 `category` 从研究主题继承 `basis_type`。
- 每轮分区保存合格与失败条目，合格项锁定，失败项带允许引用单独纠错。
- 禁止 Writer 将后续全局工具资料自动作为原选题依据。

验收：本次第 2 轮可直接通过；第 1、3 轮不再因一条错误丢弃整组。

## 任务 3：保留部分结果并修正错误分类

- 在 `app/structured_writer.py` 保存各轮候选正文、合格项和逐项错误。
- 区分 `writer_source_pending`、`writer_validation_pending`、`writer_unfilled`。
- 修改 `app/schemas.py`、`app/report_validation.py`：只有真实研究不足才设置证据不足。
- 自动不足 4 条时转人工补全，不得静默完成。

验收：最终失败仍能看到已合格项、失败项正文和具体原因；页面不误报证据不足。

## 任务 4：回归与本次任务回放

- 更新 `tests/test_section_two.py`、`tests/test_seasonal_review_fallback.py` 和现有结构化 Writer 测试。
- 固定回放 `f99ce0c4d4c33f87688b`、`5c31307cb95b9732fd35`、`ab56a2481bdb93453bd8` 三份交换工件。
- 运行目标测试、路径回归测试和完整 pytest。
- 记录改动前后结果，不用新联网结果替代固定回放证据。

完成标准：所有测试通过；本次三轮失败被正确定位和处理；无交叉引用或事实真实性校验放宽。
