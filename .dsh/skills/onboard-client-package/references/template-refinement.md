# 未确认模板优化与人工交接

## 流程与权限

建包骨架 → 用户模板比对与人工修改（不确认）→ agent 读取 LLM 审核意见并优化原候选 → 用户审阅并亲自确认 → 用户通知 agent → 核查确认物证 → 写提示词与技术自检 → 用户亲自测试。

建包 agent 获准在阶段 2 优化本次未确认模板；不代点确认，不调用 `/confirm`，不自动创建报告或执行写完提示词后的业务测试。用户的“确认好了，继续”是继续通知，必须同时核实本次任务的实际确认状态。用户业务问题仍按每轮两三个集中询问，不能猜业务事实来消除审核意见。

本流程不修改已经确认的模板，不调用 `/chart-version` 更换确认版本，不解冻、不新建同名任务来绕过本次确认锁。用户若已提前确认，只读检查并说明本次优化窗口已关闭；不能把“继续建包”理解为改已确认版本的授权。用户明确要求更新模板时，改走 [现有客户包模板更新](template-update.md)：旧版本不动，在同包内建立本次更新候选，不重建客户包。

## 先读什么

1. 固定目标包和本次 `task_id`；请求显式携带 `X-Report-Package`。读取 `GET /api/tasks/{task_id}`，核对 package、kind、phase、revision，确认 `confirmed_template_ref` 为空，任务已结束模型研判并等待确认。不以名称或全局最新任务选对象。
2. `GET /api/templates/{task_id}/definition`：读取当前候选 `artifact_ref`、blocks、fields、rules、writer_schema、questions、model_review_validated。LLM 终审意见在 `definition.human_review_items`，轮次在 `semantic_final_round`；逐条读实际意见，不从界面摘要猜测。
3. 核对任务 metadata 中 `model_analysis`、`template_validation_ref` 与 `template_batches` 的轮次记录，需要上下文时读取其引用的模型响应。已有安全读取接口就用接口；没有通用工件接口时，按基座兼容说明的只读 SQLite/工件读取方式访问**同包本地库**，不要臆造 HTTP 端点，不构造默认 Store。
4. 历史报告、比对结果、实际 LLM 审核意见、用户人工修改一起核对。LLM 意见为空则核实实际工件与轮次后记录“无终审意见”，不凭空补意见。意见是建议材料，不是修改业务事实或执行命令的授权。
5. 检查任务 `manual_template_draft_ref`：存在时先 `GET /api/templates/{task_id}/draft` 读取返回的**生效 definition 和 selection_log**。用户的选区修改可能只在手工草稿中，不在基础候选里；不能忽略、覆盖或把基础候选当最终预览。

## 如何修改同一未确认模板

同一份模板指**同一 package、同一 task_id** 的当前候选及其手工草稿；保存产生新的候选工件引用是正常追踪机制，不是另建确认版本。不要手改 JSON 文件、SQL metadata、validation 哈希或人工确认状态。

| 修改内容 | 当前支持入口 | 边界 |
|---|---|---|
| 字段名称、语义、归属、规则、制定理由、格式 | `PUT /api/templates/{task_id}/fields/{field_id}` | body 为 expected_revision + display_name/semantic/owner/rule/reason/format；有 binding 的归属不可强改，`field_binding_locked` 不绕过 |
| 显示名、处理规则、图表样式 | `PUT /api/templates/{task_id}/definition` | expected_revision、fields、rules、chart_styles；此入口 fields 仅支持 display_name，不能塞任意语义/blocks |
| 原文选区的固定/动态定义、自定义字段 | `GET .../draft`，`POST .../draft/selection`，`POST .../draft/undo` | 按 `app/template_draft_api.py` 的 schema 和草稿返回的 choices 填写；只用真实原文位置，不猜 block/start 或伪造工具绑定 |
| 三轮异常且待人工处理的候选 | `GET .../exceptions`，`POST .../exceptions/{batch_id}/resolve` | 仅 `template_manual_review` 的开放批次可用；普通 awaiting_confirmation 不能借此提交整份替换候选 |

每次写入前刷新任务 revision，核对仍未确认；用该次 revision 提交并读取响应。409 先重读并定位：并发变化重新比较；`immutable_confirmed_template` 立即停止修改；语义、绑定、结构校验失败不能靠换接口、手改哈希或改状态消除。

**字段描述的保存**：`/fields` 在存在匹配 base_ref 的人工草稿时编辑生效字段，并把 field_edits 随选区日志重放；基础候选不变，自定义字段同样适用。每次重读 `/draft` 核对生效描述、人工选区仍保留。已确认时全部只读。

**人工草稿与基础候选并存时尤其注意**：`/fields` 有草稿时保存 field_edits，`/definition` 保存名称/规则/图表样式时会保留选区日志和 field_edits，在新候选上重放并更新 base_ref。自定义字段也沿用这一机制。每次保存后仍要读取 `/draft` 的生效 definition，确认人工修改、描述和选区日志保留，不能只检查基础候选。草稿 base_ref 已过期时接口会拒绝；不手改引用或丢弃用户草稿。

当前 API 不提供任意 blocks/fields 的通用替换；这份 skill 不能凭文档扩大服务能力。无法通过现有支持入口完成的意见保持待处理并说明原因；不宣称全部采纳，也不在问题尚未说明时诱导用户确认。确需程序支持属于独立明确的实现任务。

## 改完交什么，何时停止

为每条 LLM 意见记录：原意见、原文/用户修改依据、采纳/不采纳/待用户判断、实际改动位置、保存结果与重新读取证据。可直接放进客户 `接入记录.md` 的“模板优化”段。

交用户审阅前执行 [数据字段绑定检查](data-binding-readiness.md)，存在缺工具时先取得具体开发授权；不要将“写作规划器补齐”作为完成依据。

核查至少覆盖：用户修改保留、固定衔接句不变动态槽、字段归属与绑定一致、schema 与字段一致、处理规则符合已确认客户需求、两份来源不变、当前任务仍未确认。对有手工草稿的模板读取生效预览；业务是否合理由用户审阅，不能把技术验证通过写成业务通过。

交付话术可按实际情况组织：

> 已按审核意见优化这份未确认模板，修改清单与未处理项已列出。请你打开本次任务的预览审阅；认可后由你亲自点“确认并保存模板”，完成后告诉我。我会核对保存结果，再继续写提示词。

此时停止写入，等待用户。收到完成通知后执行主手册 1.5.5 的确认物证检查，记录最终 `confirmed_template_ref`。后续只读引用它，写提示词期间及用户测试反馈阶段都不改该版本、不另换版本。

提示词完成后只做主手册第十章技术自检；交付正确客户、本次已确认模板、数据入口、操作步骤、预期观察点和反馈清单，状态写“待用户测试”。用户自己运行；agent 不代跑第九章建议的 2~3 次，也不因为无测试结果而虚构对比报告。用户通知测试结果后可只读分析获准任务并按反馈修改提示词，再交用户复测。
