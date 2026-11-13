# 提示词对照表

本目录是**基座默认提示词**（29 个）。客户包 `packages/<客户>/prompts/agent/` 里放同名文件即可覆盖。

查找顺序：**客户包 → 本目录 → 报错 `prompt_missing:<key>`**。每个 key 的实际来源可用 `core.prompts.registry.provenance()` 查。

约定：
- **阶段**指月报流水线的五步：`02 模板确认 → 03 数据处理 → 04 模板/数据·审核 → 05 报告撰写`（首页热点独立）
- **来源**：`基座` = 本目录；`客户包` = `packages/<客户>/prompts/agent/`
- 文本里出现的 `{region}` 之类不是占位符语法，是给人看的说明；真实变量由 `payload` 传入
- `AGENT_PROMPTS` 里部分 key 由**代码动态拼名**调用（如 `writer.slot.{kind}`、TOP10 分支），下表调用点标 `动态`

---

## 02 模板确认（5）

| 提示词 | 来源 | 做什么 | 调用点 |
|---|---|---|---|
| `template_analyst.template` | 基座 | 主指令：按制定规则 + 历史报告全文，产出报告骨架 `blocks`/`fields` 与占位符口径 | `template_review.py:42` |
| `template_analyst.batch` | 基座 | 分批输出指定 `target_blocks`，完整模板由程序汇总；逐项修复错误不改正确字段 | `template_execution.py:53` |
| `template_analyst.repair` | 基座 | 一轮研判失败后的整体修复；统计字段 owner 冲突时重判用途，不靠换标签掩盖 | `template_execution.py:59` |
| `template_analyst.charts` | 基座 | 图表规则：调性/平台饼图、分类纵向柱状、日趋势折线；样式可人工调整 | `template_review.py:42` |
| `template_analyst.advice` | 基座 | 确认后**只读审核**：只返回修改意见，不改模板与字段 | `template_advice.py:127` |

## 03 数据处理（1）

| 提示词 | 来源 | 做什么 | 调用点 |
|---|---|---|---|
| `data_processor.next_tool` | 基座 | 每轮**只选一个**工具：导入 → 筛选 → 属地 → 关键词候选 → 向量近邻 → 去重归并 → 分类 → 主题聚类 → 材料选择 | `workflow.py:226` |

> 这一步只有 1 个提示词，因为它是**工具循环**：模型反复被问“下一步调哪个工具”，具体算法在工具里。

## 04 模板/数据·审核（5）

| 提示词 | 来源 | 做什么 | 调用点 |
|---|---|---|---|
| `event_judge.pairs` | 基座 | 逐项比较两组代表记录的标题与梗概，判定是否**同一具体事件**；证据够就 `same`/`different`，不够才留待人工 | `event_analysis.py:155` |
| `event_judge.repair` | 基座 | 修正前次覆盖或分组错误，返回完整结果 | `event_analysis.py:191` |
| `event_judge.top10` | 基座 | 核对 TOP10 前 30 个候选，按同事件分组；必须覆盖 `allowed_ids` 每个 ID 且只出现一次 | 动态（TOP10 分支） |
| `event_classifier.classify` | 基座 | 对每个已去重事件按主体与事实分类；输出必须逐项覆盖输入并符合 JSON Schema | `event_analysis.py:250` |
| `event_summarizer.summary` | 基座 | 事件梗概 **15~35 字**，只写谁/哪里 + 发生什么 + 有依据的后果 | `event_analysis.py:301` |

## 05 报告撰写（13）

### 规划与骨架

| 提示词 | 来源 | 做什么 | 调用点 |
|---|---|---|---|
| `writer.data_planner` | 基座 | 把模板数据字段映射成**计算定义**（只给定义不给数值），缺期号/日期时选参数运算不猜填 | `structured_writer.py:123` |
| `writer.general` | 基座 | 按确认模板逐字段填写，只返回 `values`；可调只读工具补本月原文与统计，不得重判事件 | `structured_writer.py:201` |

### 长文段落

| 提示词 | 来源 | 做什么 | 调用点 |
|---|---|---|---|
| `writer.analysis` | 基座 | 第二部分（一）研判分析：**300~500 字**完整一段（建议 350~420），不是第一部分统计复述 | `structured_writer.py:222` |
| `writer.outlook` | 基座 | 第二部分（二）工作建议：面向**未来 1~2 个月**的风险预警与预防安排 | `structured_writer.py:222` |
| `writer.analysis_output` | 基座 | 分析段输出约束：`source_refs` 只能原样复制 `allowed_source_refs` 或本次只读查询返回的 ref | `structured_writer.py:223` |
| `writer.outlook_field` | 基座 | 选题目径：比较 5~8 类候选 → 目标 5 类合格选题 → 至少 4 类方可进入写作 | `structured_writer.py:230`、`reviewers.py:116` |

### 槽位填充

| 提示词 | 来源 | 做什么 | 调用点 |
|---|---|---|---|
| `writer.slot.base` | 基座 | 只填**一个**槽位，绝不重写整段；只输出 `slot_id`/`value`/`source_refs` | 动态（`slot_writer.py`） |
| `writer.slot.themes` | 基座 | 主题名称列表：顿号连接证据中语意相符的 theme，不得编造 | 动态（`slot_writer.py`） |
| `writer.slot.narrative` | 基座 | 问题概述：只写证据中与槽位语义相关的事件，不加证据外事实 | 动态（`slot_writer.py`） |
| `writer.slot.titles` | 基座 | 报道标题：来源原文引用，多个按模板标点连接，`source_refs` 1~3 个 | 动态（`slot_writer.py`） |

### 来源与引用

| 提示词 | 来源 | 做什么 | 调用点 |
|---|---|---|---|
| `writer.source_binding` | 基座 | 引用用**程序分配的正整数编号**；`source_refs`/`history_refs` 字段名不变，值只能是整数 | `slot_writer.py:88`、`reviewers.py:283` |
| `writer.reference_repair` | 基座 | 正文已生成，本次**只补选引用**，不重写正文 | `source_binding.py:161` |

### 退修

| 提示词 | 来源 | 做什么 | 调用点 |
|---|---|---|---|
| `writer.revise` | 基座 | 按两位审核员与本地校验的具体问题退修；只改 `editable_fields`，返回 `patches` | `reviewers.py:267` |

## 审校（3，贯穿撰写）

| 提示词 | 来源 | 做什么 | 调用点 |
|---|---|---|---|
| `content_reviewer.review` | 基座 | 审查事实、来源、判断强度与逻辑，并套用文风规则（lieflat-less-ai-tone） | `reviewers.py:42` |
| `format_reviewer.review` | 基座 | 审查机器稿与 `readonly_data`/`template_layout` 的格式一致性：残缺句、重复文 | `reviewers.py:42` |
| `style.application` | 基座 | 授权声明 + 文风规则注入（跨角色，被多个阶段复用） | `reviewers.py:134,270`、`structured_writer.py:51,209` |

## 历史调研（4，撰写前置）

| 提示词 | 来源 | 做什么 | 调用点 |
|---|---|---|---|
| `historical_researcher.plan` | 基座 | 规划：先用模型知识比较 5~8 类未来风险候选，再按需核实地方事实 | `historical_research.py:46` |
| `historical_researcher.research` | 基座 | 核对选题依据：目标 5 类，至少 4 类有依据才可进入写作 | `historical_research.py:55` |
| `historical_researcher.page_note` | 基座 | 单页阅读笔记：只展示与本地风险相关的**连续原文片段**，引用用 `excerpt_index` | `historical_research.py:29` |
| `historical_researcher.current_note` | 基座 | 本月分类仅作**当前信号**，不等于历史同期高发 | `historical_research.py:56` |

## 首页热点（1，独立于月报流水线）

| 提示词 | 来源 | 做什么 | 调用点 |
|---|---|---|---|
| `hotspot_collector.collect` | 基座 | 从检索结果里挑 **20 条**要闻：按影响力+热度排序、归入类别、每条带原文链接 | `hotspot.py:456` |

## 系统级（2，不属于业务阶段）

| 提示词 | 来源 | 做什么 | 调用点 |
|---|---|---|---|
| `model.json_output` | 基座 | 强制只输出一个符合给定 JSON Schema 的对象，不解释不加 Markdown | `model_client.py:74` |
| `model.tool_budget_exhausted` | 基座 | 工具调用预算用完：只依据已读资料总结，证据不足明确写缺口，不得编造或再调工具 | `model_client.py:91` |

---

## 汇总

| 阶段 | 数量 |
|---|---|
| 02 模板确认 | 5 |
| 03 数据处理 | 1 |
| 04 模板/数据·审核 | 5 |
| 05 报告撰写 | 13 |
| 审校（贯穿撰写） | 3 |
| 历史调研（撰写前置） | 4 |
| 首页热点 | 1 |
| 系统级 | 2 |
| **合计** | **34** |

**34 个全部由基座提供**，客户包 `prompts/agent/` 目录为空。

新客户接入时**一个提示词都不用写**——只需准备数据：`template.json`（词表/区县/列映射/去重参数）+ `manifest.yaml`（开关与图表清单）。

若某客户确实需要改口吻，在 `packages/<客户>/prompts/agent/` 放同名文件即可覆盖，`provenance()` 会显示为 `package`。

> **S10-F 泛化勘误**：最后 4 个曾判为「客户专属」的提示词，其客户内容全部是**举例**——`安顺` → `本地区`、`贵州` → `省域`、`黄果树` → `示例地名`、`交通管理` → `示例类目`。指令语义未变，基座因此彻底客户无关。反证：`writer.analysis` / `writer.general` 的指纹逐字符未变。

> 按角色看：`writer` 独占 13 个，因为报告里不同类型的字段（统计/分析/建议/标题/主题）走不同指令；`template_analyst` 5 个；`historical_researcher` 4 个；`event_judge` 3 个；其余角色各 1 个。
