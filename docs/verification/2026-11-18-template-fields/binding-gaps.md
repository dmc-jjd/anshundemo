# 龙川县月报 V3 数据字段检查

目标：`longchuan_yuebao`，任务 `46851d8fe1544bd985a9bad9f9a49f18`，模板“龙川县舆情月报V3”。已确认工件未修改。以下缺口表保留初次审计基准：35 个 data 字段，23 个存在绑定配置，12 个缺少有效绑定；23 个已配置字段尚未做本期业务取值验收。原始清单见 binding-audit.json。

当前状态（2026-11-18）：用户已授权开发并确认媒体口径及呈发固定内容；6 项通用计算及 12 项包绑定已实现，35 个 data 字段均有有效绑定配置。新增 12 项已通过实际 V3 字段 schema 的合成数据校验。业务取值验收仍由用户执行。当前物证见 [计算验收记录](../2026-11-18-calculation-tools/README.md)。

## 12 个缺口及拟补能力（原始基准，现已实现）

| 块 | 字段 | 拟补通用能力 | 需要明确的口径 |
|---|---|---|---|
| 8 | b8_peak_count 峰值条数 | peak_count：冻结日统计最大值，返回整数文本 | 与 b8_peak_date 使用相同范围；并列高峰按现有日期选择规则 |
| 16 | b16_source_stats 具体信源统计句 | source_statistics：按 source 分组条数降序，返回来源和条数字符串 | 是否全量、展示全部还是前 N、并列排序、未知信源如何显示 |
| 21 | b21_top_gov_count 重点政务传播条数 | selected_material_count：按明确政务选题/事件成员计算传播条数 | 必须和 b21_top_gov_title 指向同一选题；不能用全量、平台数或相似标题猜数 |
| 22 | b22_media_outlets / b22_media_articles | filtered_record_count / distinct_source_count：按媒体属性和级别筛选，分别计算记录数和媒体去重数 | 媒体范围如何认定、家数用 source 还是 source_id 去重、缺值如何处理 |
| 22 | b22_central_outlets / b22_central_articles | 同上，央级筛选 | 源数据级别枚举与央级映射需核实，不猜别名 |
| 22 | b22_provincial_outlets / b22_provincial_articles | 同上，省级筛选 | 同上 |
| 22 | b22_local_outlets / b22_local_articles | 同上，地市级筛选 | 同上 |
| 48 | b48_table_rows 呈发印发表格行 | parameterized_table：固定行结构 + 本次成文日期，返回二维数组 | 呈送/发放对象和编印机构由客户明确配置；历史人名、机构不可默认沿用 |

现有目录的 count 只能按全量记录/确认事件计数，不能任意筛选媒体属性/级别或 distinct source；platform_statistics 与 source_statistics 不是同一统计维度；record_table 是逐条明细表，不能输出上述三行印发表；constant 只有字符串，既不能输出二维表也不能让印发日期动态变化。

原始判断：写作规划器最多尝试 3 轮从 Calculation 目录映射；工具与 schema 不存在时无法靠提示词补出来。因此当时不能保证这 12 项全部完成，状态为“待工具开发授权及统计口径确认”。该缺口现已通过通用运算和包内绑定解决，不再依赖规划器兜底。

获准后先核对真实输入列和级别枚举、同一政务选题选择机制及客户呈发配置；业务含义不明仍须用户确认。实现应为基座通用计算能力，客户筛选、展示规则与字段 id 放在包内；配置将影响同包模板后续生成，需核查旧版同名字段。技术验证用合成冻结数据，不创建真实报告，不调用付费模型。已确认 V3 保持原样，完成后通过包内 calculations.yaml 配置。

## 实施口径与交回

- 媒体：全国/省级/市级分别对应央级/省级/地市级，总数为并集；家数按 source_id 去重，缺失时用 source + author 组合。用户已采用该口径。
- 印发表：用户确认固定内容沿用 V3，仅更新本次 publication_date；呈送行来自确认模板表头，计算仅返回后两行，不重复呈送名单。
- 政务选题：当前实现约定为 media_attribute=政务的候选，按去首尾空白后完全相同标题统计同范围全体记录中的传播数，取最高，同数按标题排序；不做语义合并。Writer 及人工改写均校验选题与计数一致。此为已告知用户的实现口径，仍需业务验收。
- 信源：source 精确分组，最多前 20 项，条数降序、同数按名称排序，空来源列“未知”。
- 缺失必要日期、筛选列或媒体身份时明确报缺输入；不沿用历史日期、不猜数。无可用政务候选时提示补充输入。
- 实现：core/frozen_report.py、core/calculation_extensions.py；客户参数及字段映射在 packages/longchuan_yuebao/calculations.yaml；标题约束配置在 template.json 的 calculation_contexts。
- 回接：建包 agent 读取实际配置与测试物证，再完成绑定及用户测试交付；确认工件不变。专门工具 agent 的交接格式见 skill 的 references/tool-extension-handoff.md。
