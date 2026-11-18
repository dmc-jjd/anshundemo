---
name: onboard-client-package
description: "接一个新客户时的完整操作流程：建包骨架 → 人工确认模板 → 写提示词。当用户要求接入新客户、新建客户包、建模板、写客户提示词、或问『怎么加一个客户』时使用。"
---

# 接入新客户（agent 操作手册）

> 读者是 **agent**，不是人。读完这一份就能在 `packages/<新包>/` 建出整套文件，判断 34 条提示词里哪些要改写、哪些沿用基座，并跑出一份能让人签字的对比报告。

## 〇、这份文档怎么用

这份文档分两部分，**都要读**：

| 部分 | 章节 | 管什么 | 跳过会怎样 |
|---|---|---|---|
| 机制与落点 | 二、七、八、十、十二、十三 | 输入怎么读、`agents:` 怎么声明、每个答案落到哪个文件哪个字段、建完怎么自检、报错怎么修、图表与工具只该读哪几个文件 | 包跑不起来，或建出来的包缺机制；或为了查图表/工具通读整个仓库 |
| 流程与协议 | 一、三、四、五、六、九、十一 | 怎么和人对话、需求集怎么推、34 条怎么逐条判、什么该问什么不该问、正文怎么写、怎么测、怎么交接 | 提示词写错：该改的没改、写了客户事实、或该写的没写 |

读法：先读第一章定交互方式；按 二 → 三 → 四 → 五 → 六 → 七 → 八 做题；九、十一 在写完提示词之后；十、十二、十三 随时查。

产出物固定为六样：

1. `packages/<新包>/manifest.yaml`
2. `packages/<新包>/template.json`
3. `packages/<新包>/prompts/index.yaml`
4. `packages/<新包>/prompts/roles.yaml`
5. `packages/<新包>/接入记录.md`（输入 / 缺口表 / 问答记录 / 提示词清单 / 自检证据 / 遗留，六段格式见 5.6）
6. `packages/<新包>/对比报告-<期号>-<日期>.md`（每次测试运行一份，格式见 9.2）

三条纪律，违反任一条产出不接受：

- **不许猜**：材料能读出来的自己读；读不出来才提问，且按 5.1 先分事实类 / 判断类。
- **成批提问**：一次最多 4 问，每问必须四段——问题 / 证据 / 有哪些选择 / 不同的选择会有什么影响，缺一段不许发（1.2）。
- **每条断言有命令**：写进文件的每个结论，都必须能用一条命令重跑复现；写「应该没问题」等于没做。

**默认策略（旧默认已作废）**：新客户的提示词不是「不写覆盖、全部继承基座」。正确默认是——**先推导需求集（底线 30 条必写），再对每条判「改写 / 沿用基座」**；该写的写，该沿用的登记依据；只有 4 条旁路/条件键可省，且必须登记（3.3、3.4）。理由：基座兜底会静默生效、不会报错，客户体例错在报告里，没有任何门禁拦得住。**特别注意模板三键 `template_analyst.batch / .repair / .advice` 一条都不能省**：研判固定三轮（3.3），缺键时 `check_package` 与 `import app` 都不报错（提示词已改懒加载），第一次建模板跑到对应轮次才炸（6.4）。

## 一、交互协议（硬要求）

本章四条（自查优先 / 四段提问 / 一次最多 4 问 / 答完才动文件）适用于每个阶段的内部。这四条的优先级高于本文件其它所有内容，与用户的每一次交互都按这四条走。

另有三条「写给人看」的规矩（1.2 内三小节：不许抛内部标识符 / 阻断问题单独走三段 / 证据只给能决策的事实）。用户是产品经理，看不懂字段名与异常名——**看不懂就等于没说**。

### 1.1 只提问不输出思考

- 不写「我先分析一下」「我理解你的意思是」「接下来我将」；不解释结论怎么来的，只给结论 + 证据。
- 不写思维链、不写方案草稿、不写「我准备改哪几条」的预告。
- 一条回复只做一件事：提问，或交付。

### 1.2 自查优先、一次最多 4 问、每问必须四段

- 判断类问题成批问，**一批最多 4 个**；按决策分组，不按 34 个 key 逐条刷问。
- 每问四段齐全：**问题 / 证据 / 有哪些选择 / 不同的选择会有什么影响**（硬要求见下）。缺一段就是不合格的问题。
- 可直接改写的范例见 5.4（Q1~Q7，Q3 是标准四段范例）。材料缺口（2.6）不属于判断类，单独报告，不混进提问批次。

#### 让用户做事之前，先问：这件事我能不能自己查？

**能自己查的，绝不让用户做。** 用户的时间只花在他独有的判断上。

| 这类事 | 自己查 |
|---|---|
| 读文件、看目录、读 JSON/YAML/manifest | 用仓库工具读 |
| 调接口看返回值（`GET /api/...`） | 自己用命令调，把结果写进证据 |
| 跑校验脚本 | 自己跑 `scripts/check_package.py` |
| 某个字段/常量在哪定义 | 自己读代码（只读第十三章列出的文件） |
| 某个包能不能被系统识别 | 自己调 `GET /api/packages` 看结果 |

**只有这三类才让用户做：**
1. **客户业务事实** —— 辖区清单、类目体系、报告类型、客户明确不要哪些能力。只有客户知道。
2. **界面操作** —— 上传历史报告、点「确认并保存模板」。需要人在浏览器里做。
3. **物理环境** —— 客户文件在工作区哪个位置、内网/DLP 策略、某台机器能不能访问外网。

#### 让用户做的每一件事，必须写清四样

| 要素 | 写什么 |
|---|---|
| **去哪** | 完整可粘贴的路径。接口给完整 URL（`http://127.0.0.1:8765/api/packages`）；界面给「第几页 → 哪个区域 → 哪个按钮」 |
| **看什么** | 期望看到的**真实内容样例**，贴一段真实输出/截图文字，不要只给字段名 |
| **算成功** | 看到什么就说明这件事已经成立，可以进下一步 |
| **不对劲** | 看到什么说明哪里没做好，先去做什么（指向具体动作或具体文件） |

**反例（本次清扫前的 1.5.3 原话，已全部清掉）：**
```
让用户去 /api/packages 查新包在不在、usable 为 true——查的是 agent 自己能查的东西，
而且没写清看到什么算对、不对先去做什么。
```

**正例：**
```
在浏览器打开 http://127.0.0.1:8765/api/packages
会看到一段 JSON 数组，例如：
  [{"package":"longchuan_yuebao","name":"龙川月报","report_type":"舆情月报",
    "version":"1","usable":true,"status":"ok","error":null}]
找到 "package" 是 longchuan_yuebao 的那一条：
· "usable": true   → 包已建好，可以继续下一步
· "usable": false  → 看 "error" 字段：提到 manifest_missing_keys 就补 manifest.yaml 缺的键；
                      提到 template_unreadable 就修 template.json 的 JSON 语法
· 数组里没有你那条 → 目录名或 manifest.package 不一致，先在仓库根跑
                      & $py scripts/check_package.py --package <包名> 看它报什么
```

**但注意**：上面这个例子本身是「agent 自己该查的事」。
只有当用户需要**自己判断**（例如「包不可用的原因是缺你提供的信息」）时，才把查询结论**翻译成功能描述**讲给他听，
而不是让用户自己打开页面看，也不是把这段 JSON 原样贴给他。

#### 给用户看的话，不许直接抛内部标识符

用户是产品经理，不是程序员。字段名、函数名、常量名、异常名、内部状态值——
这些是你读代码时看到的东西，不是用来跟人沟通的语言。

**必须翻译成「这个功能是什么」，而不是「它叫什么」：**

| ❌ 不许这么写 | ✅ 这么写 |
|---|---|
| `rules.features = {classification:false, dedup:false, ...}` | 这个模板把「自动分类」「事件去重」「重点预警」「TOP10 榜单」四项都关掉了 |
| `kind=paragraph_list` / `minItems 4 / maxItems 6` | 这两组条目按「列表」处理，允许 4~6 条 |
| `owner=writer` / `writer_schema` 齐 | 27 个字段里有 14 个由模型撰写，其余来自数据 |
| `zipfile.ZipFile 抛 BadZipFile` | 这份报告是老版 Word 格式，写作阶段读不到里面的图表位置 |
| `status=confirmed_by_human` | 模板已经人工确认过 |
| `TaskState.package` / `X-Report-Package` | 这个任务属于哪个客户 |

**例外**：只在「用户必须自己去操作/核对某个具体文件或界面」时，才给精确的信息
（例如「打开 `packages/longchuan_yuebao/manifest.yaml` 看 `name:` 这一行」）——
因为那是他的手要落的地方。**其它场合一律翻译成功能描述。**

**自检方法**：写完一段，问自己「一个不懂代码的产品经理读到这句，
知道该做什么决定吗」。答不上就重写。

#### 每个问题必须四段，缺一段不许发

**问题：** 一句话说清在问什么。构建者不需要任何前置上下文就能读懂。

**证据：** 从报告 / 数据里读到的**事实**，每条都要能追溯：哪份报告第几段、哪次实测输出。**必须包含「客户的做法与基座现有能力的差异」**——例如「客户报告有 3 张图（情绪、平台、区县），其中『信源分布』还要判断能不能复用已有的平台分布口径，还是要单独出图」。**翻译成功能描述、最多 5 行**，不许出现函数名 / 字段名（见下面「『证据』是给决策用的，不是代码考古」）。

**有哪些选择：** 有几个写几个，**最多 3 个**。选项不要求互斥——可以同时做、可以叠加，也可以只做其中一个。每个一句话说清「做什么」。

**不同的选择会有什么影响：** 每个选项用 **30~40 字**概括选了它会怎样。只说清后果即可，不限定必须覆盖哪些方面。

禁止：
- ❌ 把建议写进「问题」里（「我的建议是…」不是问题，是选项之一）
- ❌ 用内部术语当标题（「机制缺口」「代码契约」「钉住」这类词，构建者不知道指什么）
- ❌ 只给结论不给证据（「需要你定」之前必须有可核查的事实）
- ❌ 五六段散文式背景交代（背景归「证据」，一段内说完）
- ❌ 把「影响」写成固定四栏对照表（报告少什么 / 多什么 / 改哪个文件 / 能否回退）：**只写每个选项的后果，30~40 字一句**，不为凑维度把话写长

**信息顺序固定为 问题 → 证据 → 选择 → 影响**：不要写成「背景 → 我的建议 → 为什么问你」。构建者读完第一段就该知道要决定什么，读完证据就能自己判断选项，不需要回读前面的铺垫。

#### 阻断问题单独走三段，不许混进四段提问

**阻断问题** = 不解决它，后面全部工作都跑不通（例如数据落在错的客户、模板读不出来）。
这类问题**不进提问批次**，单独一段，固定三段：

```
问题：一句话说清是什么坏了
后果：不修会怎样 —— 用户能观察到的现象（报告出不来 / 找不到模板 / 数据落错地方）
怎么办：最多 3 个选项，每个 30~40 字说清代价
```

**禁止**：在「后果」里讲机制（哪个函数抛了什么异常、哪个字段是什么类型）。

**也不许**把阻断项和普通决策问题放在同一批里连着发 ——
先报阻断项，等它被解决，再发决策问题。否则用户在一片混乱里无法判断优先级。

#### 「证据」是给决策用的，不是代码考古

证据段允许写的：
- 客户报告里的实际数据（条数、字数、数量级）
- 基座能力与客户做法的**差异**（能用什么、不能用什么）
- 可追溯的出处（哪份报告第几段 / 哪次实测输出）

证据段**不许**出现的：
- 函数名、常量名、类名、异常名（翻译成功能描述）
- 文件行号
- 参数类型、schema 字段名
- 「我读了哪个文件发现」这类过程叙述

**判据**：用户读完证据，能不能自己判断哪个选项更合适？
不能，就说明证据给错了——给的是实现细节，不是决策依据。

**长度上限**：一个问题的证据段最多 5 行。超过就是在堆细节。

### 1.3 用户没答完前不许动文件

- 提问批次发出后等待回答；**这一轮不创建、不修改任何产出文件**，也不跑会写盘的任务。
- 用户只答了一部分：把已答的落盘（5.6），未答的重新成批问，仍不动产出文件。

### 1.4 全部答完后一次性全量创建

- 判断类问题全部有答案后，**一次性**建出四个配置文件 + 需要的提示词覆盖 + `接入记录.md`；不要边答边建、不要建半成品包。
- 创建顺序固定：`manifest.yaml` → `template.json` → `prompts/roles.yaml` → `prompts/index.yaml` → 提示词覆盖文件（若有）→ `接入记录.md`。顺序理由见 3.5。

### 1.5 创建完只报三样

1. **建了什么**：四个文件 + 提示词总数（改写 N / 沿用基座 N / 仅说明 N / 可省 N）。
2. **自检结论**：第十章六条命令的原始结果。
3. **遗留**：本次没解决的项 + 需要维护者后续决定的项。

没有第四样：不写过程、不逐条解释、不留待办承诺。

跨阶段时，另有两条交接约束（1.6、1.7）：

### 1.6 阶段 1 做完必须停下来交接

见一·五 交接点 A。阶段 1（建包骨架 + `check_package` 七段自检）一达成，**停止执行**，把 1.5.3 的固定话术原样发出并等待；不许连续执行到模板对比，更不许直接开写提示词。

### 1.7 阶段 3 开始前必须验证已确认模板存在

见一·五 交接点 B。检测不到 `status == 'confirmed_by_human'` 的模板（且 `source_reports` ≥ 2）就不许开始写提示词，继续等；不许拿「候选模板」（`candidate_requires_review`）当已确认模板。

## 一·五、三阶段全链路（骨架 → 人工确认 → 提示词）

> **当前只有多包架构（单包架构已不存在）。** `GET /api/packages` 恒返回客户包列表
> （`[{package,name,report_type,version,usable,status,error}]`），每个任务创建时绑定
> `package`，包配置按需加载（键 = 包 + 指纹）。**不存在「服务当前是哪个包」**：
> 接客户不切环境变量、不重启服务，只在建任务时选客户（见 1.5.4 ① 与 1.5.7）。

这一节把一次客户接入切成三段，**段与段之间默认停下来**。第二到第十一章讲的是「每段内部怎么做」，这一节只讲「段和段怎么交接」。

### 1.5.1 三阶段总览

```
阶段 1（agent 自动执行）    建包骨架
        ↓ 交接点 A：agent 停下来提示用户（固定话术，见 1.5.3）
阶段 2（人工执行）          模板对比 + 确认
        ↓ 交接点 B：agent 检测到「已确认模板」（检测法，见 1.5.5）
阶段 3（agent 自动执行）    提示词需求推导 + 逐条撰写 + 测试
```

**关键约束（是流程的一部分，不是建议）**：

- 阶段 1 与阶段 3 之间**必须**有人工确认这一步。agent 不许跳过，也不许代做。
- 阶段 1 结束时，agent 的合法动作只有一个：发出 1.5.3 的固定话术，然后等。
- 阶段 3 开始前必须先过 1.5.5 的检测；检测不到就继续等，不许改道。

### 1.5.2 阶段 1：建包骨架（五步，可执行）

#### ① 问用户四个事实

这四项材料里读不出来，必须问；按 1.2 一次问齐（正好 4 问，不超限）：

| # | 事实 | 落点 | 为什么必须问 |
|---|---|---|---|
| 1 | 客户包目录名（英文/拼音，如 `anshun_monthly` 这种下划线格式） | 目录名 = `manifest.package` = `template.json.package`（三处必须同值） | 客户名/报告名都是中文，包名要人定 |
| 2 | 报告类型（月报 / 周报 / 专项） | `manifest.report_type` | 决定 `report_type` 字符串，材料里读不出客户要哪种口径 |
| 3 | 辖区清单（或「不按辖区拆分」） | `template.json.vocabulary.localities` | 5.3.1：一律必须问，没有默认值 |
| 4 | 类目体系（`cluster_terms` 的 label 列表，写入口径即枚举序） | `template.json.vocabulary.cluster_terms` | 5.3.2：一律必须问，没有默认值 |

这四问同样是「判断类」，**按 1.2 的四段写**（问题 / 证据 / 选择 / 影响）。填空要点：

| # | 问题（一句话） | 证据（为什么材料里读不出客户的答案） | 选择 + 影响（各一行，选项最多 3 个） |
|---|---|---|---|
| 1 | 客户包目录名用哪个？ | 材料里只有中文客户名与报告标题（如「龙川月报」），目录名要英文/拼音下划线格式 | 拼音全称 / 拼音缩写 / 客户自定，如 `longchuan_monthly`；三处必须同值，改一处漏两处不报错但审计行对不上 |
| 2 | 报告类型是月报、周报还是专项？ | 报告标题能读出，但读不出客户要按哪种口径算报告类型 | 舆情月报 / 周报 / 专项；只落报告类型一行，改一行即回退 |
| 3 | 辖区范围是哪些行政区？每个区在数据里怎么写？ | 名单外的写法认不出来；一段文字认出 0 个或 2 个以上都算没定，属地表空且**不报错**（5.3.1 有实测候选与噪声清单） | 见 5.3.1 的 A / B / C；决定属地表与属地图有没有数据 |
| 4 | 分类体系用哪一套、几个类目？ | 本机实测数据源「事件分类」列可以整列为空（5.3.2），客户的类目口径推不出来 | 见 5.3.2 的 A / B / C；决定主题分布段与分类图有没有 |

三条配套纪律：

- 四个事实没答完前**不许建任何文件**（1.3）。
- `agents:`（要做哪些步骤）**不在这 4 问里**，按 5.3.3 单独问。骨架阶段可以先不写 `agents:` —— 不写 = 全部 9 个角色参与（见 ③），等 5.3.3 问清后再补。
- 用户答「不按辖区拆分」时，**不能**把 `localities` 写成空映射：`check_package` 的 TEMPLATE 段判「`vocabulary.localities` 必须是非空映射」。做法是落一条客户报告里真实存在的整体称谓做兜底映射，同时把 `features.locality.enabled` 设成 `false`（属地表与属地图不生成，但词表仍在，包能过自检）。

#### ② 创建目录骨架

目标结构（四个文件 + 一个空目录）：

```
packages/<新包>/
├ manifest.yaml
├ template.json
└ prompts/
   ├ index.yaml
   ├ roles.yaml
   └ agent/          ← 空目录：本包要改写的提示词才往里放，0 覆盖时保持空
```

```powershell
cd D:\智能分析报告重构版V5
New-Item -ItemType Directory -Path packages\<新包>\prompts\agent -Force
```

`prompts/agent/` 空目录 = 0 条覆盖（anshun_monthly 实测 `34 keys: 34 base + 0 overrides`；demo_b 是 10 条全覆盖的反例）。`prompts/index.yaml` 与 `roles.yaml` 的骨架先照抄现有包再改——抄的时候别把客户词带错：

```powershell
Copy-Item packages\anshun_monthly\prompts\index.yaml packages\<新包>\prompts\index.yaml
Copy-Item packages\anshun_monthly\prompts\roles.yaml  packages\<新包>\prompts\roles.yaml
```

`index.yaml` 保持 34 个 `agent_prompts` 键（缺文件时 PROMPTS 段回落基座，不会判错）；`roles.yaml` 至少要覆盖 `manifest.agents` 里声明的角色 id，否则 AGENTS 段 FAIL、启动报 `manifest_unknown_agent:<id>`。若 `agents:` 留空（= 9 个角色全启用），`roles.yaml` 就要把 9 个角色的 `responsibility / boundary / output` 三段写齐。

#### ③ `manifest.yaml` 填什么（11 个键）

```yaml
package: <新包>            # 必须等于目录名，否则 MANIFEST 段报「package 值与目录名不一致」
report_type: 舆情月报
version: 1.0.0
template: template.json
prompts: prompts/

agents:                    # 9 个角色；**不写这段 = 全部角色参与**（老包兼容）
  - template_analyst
  - data_processor
  - event_judge
  - event_classifier
  - event_summarizer
  - writer
  - historical_researcher
  - format_reviewer
  - content_reviewer

tools:
  allow: [import_records, filter_records, resolve_locality, group_events,
          propose_keyword_event_candidates, propose_vector_event_neighbors,
          calculate_metrics, classify_records, cluster_event_themes, discover_topics,
          select_materials, read_evidence, render_chart, build_table,
          parse_report_document, compare_report_structures]
  phases:                  # 阶段专属工具，与 allow 取并集（不是覆盖）
    writing: [frozen_statistics, query_frozen_materials, plot_frozen_chart,
              search_historical_web, fetch_historical_page]
  budgets: {default: 40, writing: 80}

charts:
  pack: chart-core
  use: [sentiment, daily, platform, theme, locality]   # 必须与 template.json 的 charts[].id 同集合；不必限于这 5 个

skills:
  pack: skill-core
  use: [lieflat-less-ai-tone, source-binding]

capabilities:
  require: [records, metrics, locality, charts, events, documents]

features:
  locality:             {enabled: true}
  event_classification: {enabled: true}
  dedup:                {enabled: true}
  first_warning:        {enabled: true}
  top10:                {enabled: true}
```

逐键要点（判据都来自 `scripts/check_package.py` 的 MANIFEST 段，常量从基座源码 ast 读）：

- **必需 5 键**：`package / report_type / version / template / prompts`（`core/ports.py` 的 `REQUIRED_MANIFEST_KEYS`），且 `package` 值必须等于目录名。
- **`agents` 的两种写法**：写列表 = 只有列出的角色参与（未列出的流程步骤整段裁掉，见 3.6.2）；**不写 = 全部角色参与**（`core/agent_steps.py` 的 `enabled_agents`）。写进列表的 id 必须存在于 `roles.yaml`。
- **`tools`**：`allow` 是白名单，`phases.<阶段>` 与 `allow` **取并集**，`budgets` 按阶段给工具调用预算（缺省 `default: 40`）。
- **`charts`**：`pack` 固定 `chart-core`；`use` 必须与 `template.json` 的 `charts[].id` **同集合**。id 可以是基座内建的 `sentiment / daily / platform / theme / locality`，也可以是客户包自行声明的 id。`scripts/check_package.py` 的 MANIFEST 段：模板已声明 id 时以声明为允许清单，未声明时才回退到基座 `ChartStyles` 的 5 个字段名；模板有但 `use` 未列也会报错。运行期出图读的是模板（及已确认模板）里的 `charts` 实例，不是 `ChartStyles` 的字段表。
- **`skills`**：`pack` 固定 `skill-core`；`use` 用已注册技能（当前 `lieflat-less-ai-tone`、`source-binding`）；提示词里提到的技能必须在这里声明（`tests/test_s7_package_contract.py` 校验）。
- **`capabilities.require`**：已注册 6 项 `records / metrics / locality / charts / events / documents`；不写 = 不剪枝，写全 = 行为与剪枝前一致。
- **`features` 5 个键**：`locality / event_classification / dedup / first_warning / top10`，值形态是 `{enabled: true}`（注意是 `enabled`，写成 `enable` 会被专门报错 `features.X.enable 不是合法键（少一个 d，应为 enabled）`）；`event_classification` 可带 `stages` 有序降级链，每个 stage 必须有 `kind`。
- **与 3.1 的口径对齐**：3.1 讲的是这两个键**没有专属工具白名单**（`FEATURE_TOOLS` 里 `first_warning` 映射为空、`top10` 只映射 `select_materials`），不是「没有包级开关」。这两个键本身可以且应该声明，它们是客户级硬开关，与模板级 `rules.features` **相与**成生效值（`app/workflow.py` 的 `_template_features`；建任务时由 `task_feature_snapshot` 落盘成不可变快照）。anshun_monthly 实测 5 个 feature 全声明。

#### ④ `template.json` 填什么

```json
{
  "package": "<新包>",
  "version": "1.0.0",
  "writer_slots": [],
  "data_contract": {
    "sheet_index": 3,
    "required_columns": ["标题", "舆情调性"],
    "summary_columns": ["摘要", "原文内容"],
    "column_map": {
      "标题": "title", "发布时间": "published", "来源信息": "source",
      "事件分类": "category", "媒体环节": "platform", "媒体级别": "media_level",
      "舆情调性": "sentiment", "是否预警": "warning"
    },
    "dedup": {"threshold": 0.65, "candidate_floor_ratio": 0.6,
              "merge_rounds": 2, "merge_threshold": 0.5}
  },
  "vocabulary": {
    "localities": {"<辖区 A>": ["<辖区 A>", "<数据的别名写法>"]},
    "cluster_terms": {"<类目 1>": ["<数据里真实出现的说法>"]}
  },
  "charts": [
    {"id": "sentiment", "drawing_index": 1, "title": "舆情调性分布",
     "family": "sentiment", "style": "pie",
     "binding": {"source": "metrics.sentiment"}, "unit": "条",
     "scope": "all_records", "axis_label": "调性"}
  ]
}
```

判据：

- **顶层 5 键必备**：`package / version / data_contract / vocabulary / charts`；`writer_slots` **可选**（`scripts/check_package.py` 的 `TEMPLATE_TOP_KEYS`）。
- **`data_contract` 四键必备**：`sheet_index / required_columns / summary_columns / column_map`；`column_map` 必须含 `required_columns` 的每一列，否则报 `column_map 缺必需列映射`；`column_map` 的**键序就是 records 的字段序**（5.2 第 3 项）。`dedup` 四数不在价签上（TEMPLATE 段不校验），但运行期去重要用，骨架就按 5.2 第 8 项写全。
- **`vocabulary.localities` / `cluster_terms` 必须非空**；`cluster_terms` 的 label 不得重复（重复键单独报 `cluster_terms label 重复`）；label 顺序 = 模型枚举序。
- **`charts` 必须非空数组**；`charts[].id` 集合与 `manifest.charts.use` 同集合（TEMPLATE 段只要求数组非空，集合对齐在 MANIFEST 段检查）。id 不限于基座那 5 个。每条实例写清标题、`style`、`unit`、`scope`、`binding`，并用 `drawing_index`（从 1 起）对齐版式图位。`family` 建议写图族名（与内建 5 族之一相同，便于同一图族多实例共享样式和默认取数口）；历史包把样式名写在 `family` 里的写法运行期也能识别。`scope` 须是冻结事实已支持的口径（当前为 `all_records` / `confirmed_events` / `warning_events` / `negative_warning_events`）。
- **`writer_slots` 骨架阶段写 `[]`**：模板确认后才拿得到 `writer_schema` 里的真实槽位，阶段 3 再补齐（见 1.5.6）。包内没有 `templates/<新包>/` 时，check_package 对 `writer_slots` 只提示「未机械核对」，不判错。

#### ⑤ 建完自检

```powershell
& $py scripts\check_package.py --package <新包>
```

判据：退出码 `0`、末行 `PKG-OK <新包>`；七段里 `FILES / MANIFEST / TEMPLATE / PROMPTS / ROLES / LOAD` 必须是 `ok`，`AGENTS` 在未声明 `agents:` 时是 `skip`——**`skip` 不是失败**。两个典型包的原样输出（`longchuan_yuebao` 与 anshun 同为 34 键全继承、无 `agents:` 段）：

```
PKG-CHECK demo_b
  FILES        4/4 ok
  MANIFEST     ok  (features: -)
  TEMPLATE     ok  (9 columns, 2 localities, 2 categories, 3 charts)
  PROMPTS      ok  (10 keys: 0 base + 10 overrides)
  ROLES        ok  (3 roles)
  AGENTS       skip  (未声明 agents:（全部角色参与）)
  LOAD         ok  (import app in subprocess)
PKG-OK demo_b
```

```
PKG-CHECK anshun_monthly（摘录）
  MANIFEST     ok  (features: locality,event_classification,dedup,first_warning,top10)
  TEMPLATE     ok  (12 columns, 8 localities, 12 categories, 5 charts)
  PROMPTS      ok  (34 keys: 34 base + 0 overrides)
  AGENTS       ok  (9 declared, all in roles.yaml)
```

任一 `FAIL` 项下会逐条列判据与定位句子，照句改包即可（第十章第 2 条给了三种常见报错样例）。骨架阶段不需要跑第十章其余五条——那是写完提示词之后的定稿自检。

### 1.5.3 交接点 A：agent 必须停下来说什么

`check_package` 末行拿到 `PKG-OK` 之后，**先自己跑 10.2 第 1 条**（新包有没有被系统识别——调一次 `GET /api/packages` 就能查，别让用户替你确认）。查完再**立即停止执行**，把下面这段发出（只允许替换 `<新包>`，其余一个字都不改）：

> 包骨架已建好，并且通过了自检：`packages/<新包>/`
> 我也自己查过了——系统已经认得这个包，能正常加载、没有报错，这一步不用你确认。
>
> 接下来需要你亲手做的只有三件（我在这里等）：
>
> ① 在浏览器打开 http://127.0.0.1:8765/ ，点顶部「02 模板确认」→「新建比对任务」面板。
>    「客户」下拉里认准末尾是「· `<新包>`」的那一项（每项形如「客户名称 · 包代号」，不同客户可能同名，包代号唯一）；在「历史报告 Word」里选 2 份以上历史报告，**优先选 `.docx`**——只有 `.doc` 老格式也行：文字能读、模板能建，但原文图片的位置取不到、图表只能由系统按数据重画，确认能接受再传（第一份当排版基准）；填一个模板名称，点「上传并比对」。
>    · 下拉里找不到末尾是「· `<新包>`」的项 → 先别继续，回来告诉我，我重跑 10.2 给你原因。
>    · 报「请选择至少两份不同的报告」→ 补到 2 份再点一次。
>    · 报「所选报告存在重复内容，请移除重复文件」→ 其中两份内容相同，换一份内容不同的报告。
> ② 等任务卡出现「预览并确认模板」按钮。模型研判现在**固定先跑两轮**：第一轮出初稿，第二轮逐条核对第一轮意见并按固定清单自审；第二轮判定不完美会自动加跑第三轮终审。任务卡事件区会显示「模板第 N / 3 轮研判已开始/通过」，通常 **4~8 分钟**（报告越长越久）。
>    超过 10 分钟事件区没有任何轮次进展 → 告诉我卡住了，我自己查任务状态。
> ③ 点「预览并确认模板」，核对字段与占位符，需要改的先改，最后点「确认并保存模板」。
>    按钮是灰的/看不到 → 还没跑完模型研判，等 ② 的按钮出现再点。
>    报「请填写上方尚未明确的业务问题」→ 把弹窗里列的问题逐条答完，再点一次。
>
> 三件都做完告诉我，我会自己读已确认模板的物证继续写提示词（不用你报状态，也别去翻接口）。

**三条硬约束（红线）**：

- ❌ 不许 agent 自己继续往下走：不发完话术顺手写提示词、不顺手改 `template.json` 的槽位、不顺手跑第九章测试。
- ❌ 不许绕过模板确认直接写提示词：没有已确认模板就拿不到 `blocks` / `fields` / `rules` / `writer_schema`，写出来的是猜的，而且会静默回退基座、不报错。
- ✅ 必须明确说「我在这里等」，并且真的停：发完话术的同一个回合内不再有任何写盘动作。

### 1.5.4 阶段 2：人工做什么（agent 只等，不代办）

#### ① 新建任务时选客户（不需要切包、不需要重启）

**用户在界面上做的事（四样齐）：**

- **去哪**：「02 模板确认」页 →「新建比对任务」→「客户」下拉（`#templatePackage`）；「03 数据处理」页 →「客户」下拉（`#reportPackage`）（`app/static/app.js` 的 `loadPackages`）。
- **看什么**：下拉每项形如「客户名称 · 包代号」（如「舆情月报 · anshun_monthly」），认准末尾的 `· <新包>`——不同客户可能同名（在册两个包的名称都叫「舆情月报」），**包代号唯一**，只看中文名会选错。下拉只列在册且 `usable:true` 的包（`app/static/app.js` 的 `loadPackages` 对 `GET /api/packages` 的返回过滤 `usable`）；只有一个可用包时它已默认选中并 `disabled`。在册但不可用的包不会出现在下拉里。
- **算成功**：下拉显示 `<新包>`，后续上传与建任务都按这个包走。
- **不对劲**：下拉里没有 `<新包>` → 不要挑别的包凑合，回来告诉 agent；agent 按 10.2 第 1 条查原因，不要把「你自己去接口看一下」丢给用户。

**agent 自己做的事（不要让用户代查）：**

- 用户建完任务后，agent 调 `GET /api/tasks/{task_id}` 核 `TaskState.package` 是否等于 `<新包>`（10.2 第 2 条）。
- 上传与建任务请求都带 **`X-Report-Package: <包名>`** 头：`POST /api/files`、`POST /api/template-tasks`、`POST /api/report-tasks`（`app/static/app.js` 的 `packageHeaders`）。
- 服务端解析在 `app/packages_api.py` 的 `resolve_package`：包名未登记 → **404 `package_not_found:<包>`**；登记了但不可用 → **422 `package_unavailable:<包>:<原因>`**；**空 = 部署默认包**（`REPORT_PACKAGE`）。
- **没带这个头不会报错**：请求落到部署默认包，文件与任务一起落错客户——这是最常见的静默错误，比 404 难查（见 10.2 第 4 条）。
- 模板确认时会把**这个包的** features 快照进 `template_version`（`app/workflow.py` 的 `_template_features` / `task_feature_snapshot`）。选错客户 = 快照的是别的客户的开关，而报告里不会报错——所以上面那条 `TaskState.package` 自核是必须做的，不是可选。

#### ② 上传至少 2 份历史报告（优先 `.docx`；`.doc` 能做但有取舍）

- **去哪**：「02 模板确认」页 →「新建比对任务」→「历史报告 Word」文件选择框（`accept=".doc,.docx"`，可多选）。选择框下方有常驻红字「请优先上传 .docx。.doc 能读文字，但写作阶段无法取图表位置，会出不了稿。」选中 `.doc` 还会弹逐条警告。
- **看什么**：选完框里列出文件名，形如 `安顺市10月网络舆情分析报告.docx`；少于 2 个文件名就是还没选够。
- **算成功**：至少 2 个**内容不同**的报告文件名，点「上传并比对」后页面不报错、任务卡开始出现进度。
- **不对劲**：报「请选择至少两份不同的报告」→ 补到 2 份再点；报「所选报告存在重复内容，请移除重复文件」→ 其中两份内容相同，换一份；`.pdf` / `.txt` 压根没进选择框 → 只收 `.doc`/`.docx`，换原件。

**`.doc` 老格式的取舍要主动讲给客户，不能一句「都行」带过**：`.doc` 的文字与表格能解析、模板能建（龙川月报就是 `.doc` 客户，已建正式包 `longchuan_yuebao`），但原文图片位置取不到——上传区红字说的「出不了稿」指的是依赖原图位置的取图路径；图形数恒为 0，图只能由系统按数据程序重画（机制见 13.1.2）。客户确认能接受再传；能拿到 `.docx` 原件就优先 `.docx`。

**少于 2 份不能确认**：确认后的读模板门（`core/structured_template.py` 的 `load_confirmed_template`）要求 `source_reports` ≥ 2。页面与接口都接受 `.doc`/`.docx`（`app/main.py` 的模板任务校验 `('.doc','.docx')`；422 的报错名仍叫 `docx_reports_required`，是历史命名，不代表只收 `.docx`）。

#### ③ 等模型研判（三轮语义研判）

- **看什么**：任务卡阶段文字依次变为「正在读取全部历史报告」→「本地模板已就绪」→「模型正在按语义制定模板」；进入模型相位后，事件区显示轮次文案——「模板第 N / 3 轮研判已开始」「模板第 N / 3 轮通过，用时 …」（事件 `template_round_started` / `template_round_passed`），结构校验未过时还有「第 N / 3 轮模板校验：X 项待修正」。
- **轮次怎么跑**（`app/template_execution.py` 的三轮状态机）：**第 1 轮必跑**（`template_analyst.batch`），出整份模板初稿 v1 与第一轮意见；**第 2 轮必跑**（`template_analyst.repair`），逐条回执第一轮意见是否改到位 + 按 6 条固定清单自审，输出整份模板 v2；只有「结构错误 0 且 重要=0 且 建议<3 且一轮意见全部改到位」才结束，否则**自动加跑第 3 轮**（`template_analyst.advice`），输出整份终审模板 v3，意见全部 advisory 交人工。模型调用固定 2 次、必要时 3 次，不是失败重跑。
- **算成功**：阶段变成「等待模板确认」，任务卡上出现「预览并确认模板」按钮。
- **不对劲**：事件区超过 10 分钟没有任何轮次进展（不是「停在第三轮」——第三轮是正常轮次）→ 用户只说「卡住了」，agent 自己调 `GET /api/tasks/{task_id}` 读 `phase` 与 `metadata.template_error`、读事件流定位，不要把任务 ID 和接口甩给用户。

耗时预期 **4~8 分钟**：每一轮都是整份模板全量输出，2026-11-17 三个模板任务实测单轮模型耗时 109.5 / 134.4 / 143 秒——第 2 轮完美约 4~5 分钟，进第 3 轮约 5.5~8 分钟，且随报告篇幅增长。别再用旧的单轮数字（约 268 秒）回答用户「还要多久」。

#### ④ 在「预览并确认模板」里确认

- **去哪**：任务卡上点「预览并确认模板」→ 弹出标题为「预览并确认模板」的对话框；上半部分是带占位符的报告预览，下半部分「每月沿用的处理规则」区（事件去重 / 自动分类 / 第一部分重点预警 / TOP10 榜单 四个勾选框 + 事件相似度阈值 + 重点预警统计范围），最后点底部「确认并保存模板」。
- **看什么**：预览里动态位置显示占位符 id（`B5_COVER` 这类），固定文字是正常段落；字段逐项核对三样——**归属**（谁来填：程序算 / 模型写）、**这条要写什么**（字段语义）、**归到哪一章**；规则区四个勾选框与客户实际能力一致。特别核对这些段落：多份历史报告里反复出现的衔接句式（如「正面报道主要有：」「中性报道主要有：」「负面网民言论有：」）必须是固定文字，不能整段收成一个写作槽。比对结果里的 `intra_paragraph_frames` 就是这些句式；若预览把它们吞进了动态字段，必须在确认前改回，或重新做模型研判。已确认模板不会自动拆开旧的整段槽。
- **算成功**：点「确认并保存模板」后对话框关闭、页面提示「模板已确认，可在报告处理页选择该版本。」，模板库那一行的状态变成「可用于成稿」。
- **不对劲**：按钮是灰的/看不到 → 还停在模型研判，回 ③ 等按钮出现；报「请填写上方尚未明确的业务问题」→ 把弹窗上半部分列的问题逐条答完再点；报「此模板尚未完成模型语义研判」→ 关掉弹窗，任务上点「重新进行模型语义研判」，等它跑完再回来。
- 需要改的字段**可以编辑**（显示名称 / 字段语义 / 归属）：点字段旁的「编辑」改完点「保存字段设置」，**必须在确认前改**——模板一旦确认就定稿，再点编辑会被拒绝（页面提示已确认，改不动）。
- **预设分类装不下的内容可以自定义字段**：字段分类里有一项「自定义：我自己定义这个字段」（`app/template_draft.py` 的 `custom_text`），用于预设类型覆盖不到的定性措辞（如「较稳定」「波浪型」）。在卡片内展开的小表单里填字段名（20 字内）、含义（200 字内），并指定由模型写（writer）还是程序算（data），点「生成自定义字段」——不跳页，在原卡片内完成。生成后的字段同样在确认前可编辑三件套。自定义字段的 id 是独立命名空间 `custom_field_N`（全表递增，与预设的 `block_<块>_field_<序号>` 各用一套计数器），阶段 3 读已确认模板时遇到 `custom_field_N` 是正常字段，不是异常。
- 确认并保存后落盘两样物证（agent 自查，不要让用户去翻）：`template_version` 工件 `status=confirmed_by_human`，任务 `metadata.confirmed_template_ref` 非空。

#### ⑤ 模板任务删错了怎么办（硬删除 + 同名重建）

模板建错了（选错报告、名字要重来）**不用改名凑合，也不许自己改数据目录**：模板库每行有「删除」入口，这是**硬删除**（`DELETE /api/template-tasks/{id}`，逻辑在 `app/api_views/template_library.py` 的 `delete_template`）：

- 模板任务从任务表永久删除，事件和审核草稿一并清掉；**未被报告引用的模板工件（含已确认 `template_version`）也会从库和磁盘删除**。删完该任务不再出现在 `GET /api/templates`、新建报告的模板下拉，也**不会再被方式二的 `store.list_tasks()` 读盘扫描命中**。**删除不占用模板名——同名可以重新建模板并确认**。这是删错模板的正式逃生口，删除后无法从任务表恢复。
- 研判正在跑（排队 / 读取报告 / 本地就绪 / 模型研判中）删不掉：接口返回 409 `template_still_running`，前端对这种任务也不给删除入口；等研判结束（或确认后）再删。
- 已确认模板**已被报告任务引用**时默认删不掉：409 `template_in_use` 并带引用数；界面会二次确认，用户明确确认后才带 `?force=true` 强删。强删会移除模板任务，但已建报告的 `template_ref` 原样保留，并留下那份已确认 `template_version` 以便回看报告；任务本身已不在 `list_tasks()` 里，二次建包 / 更新提示词时不要再把它当可用模板。
- 不要直接遍历 `artifacts/template_version-*.json` 判断「当前可用模板」——强制删除后磁盘上可能仍留着被报告引用的旧文件。只认仍存在的模板任务，或 `GET /api/templates` 里 `status=confirmed_by_human` 且带 `task_id` 的行。

**agent 的纪律**：agent 只用只读 `GET` 或读盘核查任务状态、引用数与删除结果；**删除动作由用户在模板库界面点「删除」并读完确认文案后自己做**，agent 不替用户发 DELETE。

### 1.5.5 交接点 B：agent 怎么判断「可以开始了」

这一步**全部由 agent 自己查**。必须确认本次客户、本次模板任务及实际工件；同名、全局最新、仅有 confirmed 状态都不算证据。

**方式一：HTTP（服务在跑，优先）**

先从本次创建任务响应或页面任务地址取得 `$taskId`，不要从全局列表挑最新。下面占位值须替换为本次真实值。

```powershell
$baseUrl = 'http://127.0.0.1:8765'
$pkg = '<新包>'
$taskId = '<本次模板任务ID>'
$headers = @{ 'X-Report-Package' = $pkg }
$task = Invoke-RestMethod "$baseUrl/api/tasks/$taskId" -Headers $headers
if ($task.package -ne $pkg -or $task.kind -ne 'template' -or $task.metadata.simulation -or $task.metadata.template_deleted_at) { throw '模板任务归属、类型或状态错误' }
$items = Invoke-RestMethod "$baseUrl/api/templates" -Headers $headers
$hits = @($items | Where-Object {
    $_.task_id -eq $taskId -and $_.status -eq 'confirmed_by_human' -and $_.artifact_status -eq 'available'
})
if ($hits.Count -ne 1) { throw '本次模板未确认，或工件缺失/不可读' }
$payload = Invoke-RestMethod "$baseUrl/api/templates/$taskId/definition" -Headers $headers
$tpl = $payload.definition
if ($payload.artifact_ref -ne $hits[0].id -or $tpl.status -ne 'confirmed_by_human' -or
    @($tpl.source_reports).Count -lt 2 -or -not $tpl.comparison_ref -or -not $tpl.writer_schema) {
    throw '已确认模板证据不完整'
}
$hits | Select-Object id,task_id,name,status,artifact_status
```

**算成功**：目标客户的本次模板任务归属正确、工件可读，且两份来源、comparison_ref、writer_schema 与人工确认状态完整。阶段 3 的四类输入仍按 2.2 读取。

`GET /api/templates` 是管理列表，内置候选、待确认候选以及缺失/不可读工件的记录都可能保留。只认带本次 `task_id` 的 confirmed + available 项。**不能用 `usable_for_final` 当工件健康或选择门槛**：健康的已确认模板也可能是 False（字段尚待绑定），仍可进入选择流程；是否能正式生成由服务端重新验证。missing/unreadable 不可预览或生成，直接访问定义接口返回 409 `template_artifact_missing` / `template_artifact_unreadable`，不可当作「没确认」而无限等待；记录具体缺口，检查工件或重新上传确认，不能自行改状态。

**方式二：离线只读检查**

服务未起时，执行 [基座兼容说明](references/base-compatibility.md) 中的只读脚本，显式传目标包、本次 task_id 和服务实际数据基根。它用 SQLite `mode=ro` 及应用的 `load_confirmed_template`，不创建 Store、不创建空库。数据库不存在与模板损坏都应明确报错，不能回退默认包。两种方式均不可只看模板名称或扫描遗留 artifacts 文件。

**`GET /api/tasks` 不够用**：它的 `metadata` 是白名单，只回 `{'simulation': ...}`（`app/main.py` 的 `tasks()`），**拿不到 `confirmed_template_ref`**；要按任务查就打 `GET /api/tasks/{task_id}`（整份 state）。

**检测不到就继续等**：不进阶段 3、不写任何提示词文件、不「先写两条试试」。等待期间只允许读输入（第二章），不产出。向用户报进度时**只报你查到的具体缺口**，用他的话讲（例：「模板还没确认——你上传的两份报告还没点『确认并保存模板』」），不附命令、不说「你自己去模板库页面看一眼」——那是你自己该查的。

### 1.5.6 阶段 3：提示词撰写（本阶段只做触发与衔接）

阶段 3 的完整流程见「三、能力开关与需求集推导」+「四、34 条逐条差异分析」+「六、撰写规范」，本阶段只做三件事：

1. 用 2.2 的四类输入读已确认模板（`blocks` / `fields` / `rules` / `writer_schema`），先跑 2.6 输入自检；不通过就停在材料缺口，不猜。
2. 按 3.3 → 3.5 的顺序推需求集（30 条必写 + 最多 4 条可省），再按第四章逐条判、第六章写。
3. 按第九章测试对比、第十章六条自检、第十一章交接定稿。

写之前先把 `template.json` 的 `writer_slots` 按已确认模板的 `writer_schema` 补齐（骨架阶段留的是 `[]`），并把 2.7 的三条命令输出贴进 `接入记录.md` 的「输入」段。

### 1.5.7 客户包目录 ↔ 数据根（建包前先认清落点）

代码与数据分两棵树，**别把产物写到代码树里**：

```text
代码：packages/<包>/            （manifest.yaml / template.json / prompts/ / templates/）
数据：data/packages/<包>/       （demo.sqlite3 / artifacts/ / uploads/ / hotspot/）
共享：data/shared/              （token-pricing.json 价目表，部署级，不按包）
```

- 三个出口都在 `core/paths.py`：`package_dir(<包>)` → `packages/<包>/`；`data_root(<包>)` → `<数据基根>/packages/<包>/`；`shared_data_root()` → `<数据基根>/shared/`。数据基根由 `configure_data_root()` 注入（来自 `REPORT_DEMO_DATA`，缺省 `<repo>/data`）。
- **隔离口径**：每个客户的任务、产物、上传、热点索引全部落在各自的包根下（`app/packages_api.py` 的 `uploads_for` / `files_for` / `root_for` / `connect_for` 都按任务的包解析）；非默认包**永远不回落**到别的包根。
- **旧单根布局只回落一次**：`<基根>/packages/<默认包>/` 里没有非空 `demo.sqlite3`、而 `<基根>/demo.sqlite3` 还在时，默认包按旧根解析并打一次 `legacy_data_root_in_use` warning（`core/paths.py` 的 `resolve_data_root`）。判据是「包里有没有非空 db」，不是「包目录在不在」——迁移失败残留的空目录不算已迁移（按目录判会把「迁移失败」误判成「已迁移」，用户视角就是数据全丢）。
- **迁移脚本**：`scripts/migrate_data_packages.py`（默认 dry-run，只打印计划；`--apply` 执行；`--apply --rollback` 回退，要求台账 `status=done`）。
- 应用工厂 `app.factory.create_app(Settings(data_root=...))` 可显式指定实例数据基根；核查落点应以运行实例配置为准，不能只猜 `<repo>/data` 或当前终端环境。请求通过 ContextVar 绑定实例服务；`paths.configure_*` 和注册表 configure 只在启动/独立子进程初始化使用，禁止请求期靠全局 configure 切客户。
- **包配置按需重读**（键 = 包 + 指纹）：修改客户包文件后无需因建包而重启；修改基座代码或部署启动配置（包括数据根、模型配置）需重启对应服务。`import app` / `import app.main` 不创建数据目录；导入成功只说明可导入，不能证明工件、上传、模型或完整业务健康。

## 二、输入准备（读什么、怎么读）

### 2.0 读报告文档：用项目自带的读取器，不要转换格式

`.doc`（OLE2 老格式）与 `.docx`（OOXML）都能直接读：**不需要转换、不需要 Word、不需要装任何库**。统一入口是 `core/tools/template_compare.py` 的 `parse_report_document`——它内部就是 `read_doc(target) if is_legacy_doc(target) else read_docx(target)`。

| 格式 | 用什么 | 说明 |
|---|---|---|
| `.docx` | `core.tools.ooxml.read_docx` | 手写 OOXML 解析（zipfile + ElementTree） |
| `.doc`（OLE2 老格式） | `core.tools.doc97.read_doc` | 直接解析 OLE2，**不需要转换** |
| 不确定 | `core.tools.template_compare.parse_report_document` | 自动判断并分派，**首选** |

前置（完整 preamble 见 2.1）：

```powershell
cd D:\智能分析报告重构版V5
$env:PYTHONIOENCODING = 'utf-8'
$py = 'D:\智能分析报告重构版V5\.conda\JJDreport\python.exe'
```

```python
from core.tools.template_compare import parse_report_document
doc = parse_report_document(r'<报告路径>')      # 自动识别 .doc / .docx
blocks = doc['blocks']                          # [{'index','kind','text','style'}, ...]
```

返回结构：`parse_report_document` 回 `{'path', 'sha256', 'blocks'}`（`sha256` 是整份文件哈希）；单独调 `read_doc` / `read_docx` 只回 `{'path', 'blocks'}`。两种格式的 `blocks` **同构**——`paragraph` 有 `index/kind/text/style`，`table` 有 `index/kind/text/rows`，所以下游代码不用按扩展名分叉。

**禁止**（都会在无人值守环境出事）：
- ❌ Word COM / `win32com.client.Dispatch('Word.Application')` —— 实测会起一个隐形 WINWORD 进程挂住（`MainWindowTitle` 为空 = 隐形模态框），60 秒超时也不退
- ❌ LibreOffice / `soffice --convert-to` —— 同上，且依赖安装
- ❌ `pip install python-docx` / `docx2txt` / `antiword` 等 —— 项目不用这些库，装了也用不上
- ❌ 手动把 `.doc` 改名成 `.docx` —— `parse_report_document` 读 8 字节 OLE2 魔数识破，抛 `UnreadableDocument`：`该文件实际是 Word 97-2003 (.doc) 格式，请把扩展名改回 .doc 后重新上传`

**一个反直觉的点**：`import docx` 失败是正常现象，项目不依赖 `python-docx`。看到它失败不要去装库，直接换 `read_doc` / `parse_report_document`。

实测基线（拿到新客户报告先对一下数量级）：龙川月报 8/9/10 月三份 `.doc` 各 41 块（40 段 + 1 表），安顺 `.docx` 历史报告 21 块。一条命令验一份：

```powershell
@'
import sys
from core.tools.template_compare import parse_report_document
doc = parse_report_document(sys.argv[1])
print('blocks', len(doc['blocks']))
for b in doc['blocks'][:3]:
    print(b['index'], b['kind'], (b.get('text') or '')[:60])
'@ | & $py - '<报告路径>'
```

`blocks` 为空就是材料缺口，按 2.6 停下报给维护者，不要猜。

### 2.1 环境与读法

整篇命令都假定下面这个 preamble 已执行过（PowerShell 5.1；`$py` 是仓库自带解释器）：

```powershell
cd D:\智能分析报告重构版V5
$env:PYTHONIOENCODING = 'utf-8'
$py = 'D:\智能分析报告重构版V5\.conda\JJDreport\python.exe'
```

`python -c "..."` 里带引号的长表达式在本机 PowerShell 会被吞引号，所以下面复杂代码一律用 here-string 喂 `-c` 的替代写法 `& $py -`（从 stdin 读脚本），可原样复制。

输入一共四类，缺一类就不动手：

| 材料 | 位置 | 读法 | 从这里提取 |
|---|---|---|---|
| 已确认模板工件 | `template_version` artifact（维护者给 ref 或导出 JSON） | `store.get_artifact(ref)` 或 `json.loads(Path(...).read_text(encoding='utf-8'))` | `blocks` / `fields` / `rules` / `writer_schema` / `business_decisions` |
| 包级模板 | `packages/<pkg>/template.json` | `json.loads` | `vocabulary.localities` / `vocabulary.cluster_terms` / `writer_slots` / `data_contract` / `charts` |
| 占位符清单（可选） | `templates/<pkg>/report.template.json` | `json.loads` | 99 个 `placeholders` 的 `slot_type` / `semantic` / `source_fields_or_calculation` / `verification` |
| 历史报告 | `*.doc 或 *.docx`（两种都要支持；本项目现有 2026 年 6/7/8/10 月四份 `.docx`（anshun_monthly），龙川月报另有 3 份 `.doc`——龙川已建正式第三个包 `longchuan_yuebao`，`packages/` 下三包并列，可作第三个参照，也是 `.doc` 客户样例） | `from core.tools.template_compare import parse_report_document`（自动分派；读法与禁用清单见 2.0） | `blocks`（段落/表格）、章节序列、字数、数字类型、句式、体例 |
| 基座提示词 | `core/prompts/base/agent/<key>.md` | `read` / `read_bytes().decode('utf-8')` | 34 条正文与方法论、硬阈值、调用约束 |
| 包级索引 | `packages/<pkg>/prompts/index.yaml` | `yaml.safe_load` | 34 个 key 的声明顺序、`template_policy`、`report_prompt_profiles` |
| 角色定义 | `packages/<pkg>/prompts/roles.yaml` | `yaml.safe_load` | 角色 id 与 `responsibility/boundary/output` |
| 包能力 | `packages/<pkg>/manifest.yaml` | `yaml.safe_load` 或 `load_manifest` | `agents`、`features`、`tools`、`capabilities`、`charts`、`skills` |

### 2.2 已确认模板（`template_version` 工件）

模板有四个面，**每个面的家不同，不要在一个文件里找不存在的键**：

| 面 | 内容 | 家 | 用途 |
|---|---|---|---|
| 章节与字段 | `blocks`（段落/表格，`parts` 里带 `text` 或 `field`；`field` 位置就是动态槽）、`fields`（字段表） | `template_version` 工件 | 判断固定文字与动态槽的边界、字段 owner、字段数、章节序列 |
| 模板规则 | `rules`（`features` + 口径） | `template_version.rules` | 判断这次模板跑不跑去重/分类/重点预警/TOP10，以及阈值 |
| 词表与槽位 | `vocabulary.localities`、`vocabulary.cluster_terms`、`writer_slots` | `packages/<pkg>/template.json` | 判断客户事实（地名、类目、槽位）是否已被正确注入 |
| 占位符口径（可选） | 99 个 `placeholders` | `templates/<pkg>/report.template.json` | 核对槽位语义与统计口径；**不要用它反推 blocks 结构** |

能直接读盘的是后两面。第三步的占位符清单：

```powershell
@'
import json, pathlib
d = json.loads(pathlib.Path('templates/anshun_monthly/report.template.json').read_text(encoding='utf-8'))
print('placeholders', len(d['placeholders']))
print(sorted({p['slot_type'] for p in d['placeholders']}))
print([p['id'] for p in d['placeholders']][:10])
'@ | & $py -
```

实测输出：`placeholders 99`；七个 `slot_type` = `computed_judgement / existing_field / narrative_from_sources / number / source_text / table_dynamic / theme_cluster`；id 首项 `B5_COVER`。

`blocks` / `fields` 这两个面你拿不到盘上文件，只能从维护者给的 `template_version` 工件读；**不要用占位符清单去反推 blocks 结构**。

`template_version` 的常见顶层键（模板确认接口组装，经 `core/storage.py` 的 `put_artifact` 落盘）：

- 候选原有：`blocks`、`charts`、`fields`、`output_schema`、`writer_schema`、`source_reports`、`review_items`、`format_version`、`layout_source`、`comparison_ref`、`other_report_hypotheses`
- 确认时追加：`version`、`status`（`confirmed_by_human`）、`name`、`model_analysis`、`source_file_ids`、`human_reason`、`template_validation_ref`、`human_resolutions`、`business_decisions`
- 规则：`rules`（开关归一后的结果，真相源是 `core/structured_template.py` 的 `template_feature_switches`）
- TOP10 开启时可能还有：`top10_rule`
- `review_items` 是三轮模板研判的意见载体（见 1.5.4 ③）：已确认工件里留下的是**第三轮终审的 advisory 意见**（人工可采纳也可忽略），不要把它当成模板缺陷清单或待办。

`fields` 的常见键（以实际工件为准）：`id`、`display_name`、`owner`、`kind`、`semantic`、`block`、`binding`、`value_schema`、`sources`、`rule`、`format`。其中：

- 字段 `id` 有两套命名空间：预设字段是 `block_<块>_field_<序号>`，**用户在确认弹窗自定义的字段是 `custom_field_N`**（全表递增、独立计数器；名称/语义/归属由用户在小表单里填，见 1.5.4 ④）。读到 `custom_field_N` 当正常字段处理，它同样进 fields 表与 `writer_schema`，不是异常。
- `owner=data`：统计/任务元信息，由程序或数据工具填；
- `owner=writer`：需要按本期证据写的文字；
- `kind`：`number`、`text`、`analysis`、`paragraph_list`、`table_rows` 等，决定这条字段走哪条提示词；
- `binding`：取数绑定，只能来自确认阶段的 `available_bindings`（兼容的 `{tool, path}`，或计算目录中的 `{metric, ...参数}`）。不明确的留 `null` 并在字段 `rule` 写缺口；不要猜造工具名或 metric。

`rules` 的键（`app/review_service.py` 的 `check_rules` 归一校验）：

| 键 | 取值 | 用途 |
|---|---|---|
| `event_threshold` | `0 < x <= 1`，缺省 `0.65` | 同事件判定阈值 |
| `first_warning_scope` | `negative_or_warning` 或 `warning` | 第一部分「重点预警」范围 |
| `ranking` | 固定 `negative_warning_member_count` | TOP10 排序口径 |
| `top10_scope` | 固定 `negative_and_warning` | TOP10 范围 |
| `top10_unit` | 固定 `deduplicated_event` | TOP10 计数单位 |
| `top10_display` | 固定 `serious_concise_summary` | TOP10 呈现 |
| `summary_min_chars` / `summary_max_chars` | `15` / `35` | 事件梗概字数 |
| `features` | `{dedup, classification, first_warning, top10}` 布尔 | 这次模板跑不跑这四件事 |

**关键纠正**：`template_version` 工件里**没有** `vocabulary` 和 `writer_slots`；它们在 `packages/<pkg>/template.json`。看到任务说「模板里带词表和 writer_slots」时，要拆成两个文件读。

### 2.3 现有包文件（三个现成参照）

- `packages/anshun_monthly/`：全量参照。34 个提示词键（全部继承基座、0 覆盖，`prompts/agent/` 目录存在但为空）、11 个角色、8 个区县（含 9 个别名）、12 个类目、5 张图、9 个 writer 槽位、显式 `agents:` 9 个。
- `packages/demo_b/`：最小参照。10 个提示词键（10 条全部覆盖）、3 个角色、2 个片区、2 个类目、3 张图、**没有** `agents:` 段。
- `packages/longchuan_yuebao/`：第三个、已正式在册的包（龙川月报，`.doc` 客户样例；`report_type` 与 anshun 同为「舆情月报」，两个包只能靠包代号区分，见 1.5.4 ①）。34 键全继承、未声明 `agents:`（= 9 角色全启用）。

一次看三个包的四个文件的结构（不要通读全部文本）：

```powershell
@'
import json, pathlib, yaml
for name in ('anshun_monthly', 'demo_b', 'longchuan_yuebao'):
    root = pathlib.Path('packages') / name
    m = yaml.safe_load((root / 'manifest.yaml').read_text(encoding='utf-8'))
    t = json.loads((root / 'template.json').read_text(encoding='utf-8'))
    i = yaml.safe_load((root / 'prompts' / 'index.yaml').read_text(encoding='utf-8'))
    r = yaml.safe_load((root / 'prompts' / 'roles.yaml').read_text(encoding='utf-8'))
    print('==', name)
    print(' manifest:', sorted(m), '| agents:', m.get('agents'))
    print(' template:', sorted(t))
    print(' data_contract:', json.dumps(t['data_contract'], ensure_ascii=False)[:300])
    print(' vocab: localities', len(t['vocabulary']['localities']),
          '| cluster_terms', len(t['vocabulary']['cluster_terms']))
    print(' index:', sorted(i), '| prompts', len(i['agent_prompts']))
    print(' roles:', list(r))
'@ | & $py -
```

要点（实测）：`manifest.yaml` 的键是 `package/report_type/version/template/prompts` + 可选 `agents/tools/charts/skills/capabilities/features`；`template.json` 的键是 `package/version/data_contract/vocabulary/charts` + 可选 `writer_slots`；各包的 `index.yaml` 都恰好四个顶层键；`roles.yaml` 是 `角色 id → {responsibility, boundary, output}`。

### 2.4 历史报告

`read_docx` / `read_doc` 的返回结构（`core/tools/ooxml.py` 的 `read_docx`；`.doc` 走 `core/tools/doc97.py` 的 `read_doc`，返回结构同构——`blocks` 的 `kind/text/style` 一致，所以下游代码不用分叉；外层 `sha256` 见 2.0）：

```python
{'path': str(path), 'blocks': [
    {'index': 3, 'kind': 'paragraph', 'text': '...', 'style': ''},
    {'index': 34, 'kind': 'table', 'rows': [['序号','事件','热度'], ...], 'text': '...'},
]}
```

- `paragraph` 有 `text`、`style`；空段落会被跳过，所以 `index` 是原文档 body 的序号，不连续。
- `table` 有 `rows`（二维数组）和拼好的 `text`；TOP10 表就是 `kind='table'`。
- **不要用 `style` 判断章节**：这四份报告的章节标题 `style` 多为空，`（一）` 段反而可能是 `style='5'`。按 `text` 正则判断。`.doc` 的 `style` 取值又不一样（实测二级节是 `Heading2` / `Heading3`，`一、` 级标题仍为空），同样只认 `text`。

从每份报告提取五类信息：

1. **章节序列**：`一、涉安信息传播态势` → `（一）从总体来看` / `（二）从平台上看` / `（三）从内容上看` / `（四）从负面舆情看` → `二、月度风险研判` → `（一）研判分析` / `（二）工作建议` → 建议 `1.` 起。
2. **每章字数分布**：见 2.4.1 的实测表，用来判断基座提示词里的字数阈值要不要改。
3. **数字类型**：总量「约 X 万余条」、条数整数、占比两位小数、负面重点预警「X 条（已去重）占 Y%」、同比「较去年同期有所下降/上升」（不带数字）、区县「X 条，占比 Y%」、图注「单位：条 / 条/百分比」。
4. **句式特征**：每章的开头、连接词、收尾。例：
   - 总体：「境内全网涉安顺信息量约……，其中正面……条，占……%；中性……；负面……%含重复事件信息（详见图1）。信息峰值在……（详见图2），媒体报道……等。负面单一重点预警数据……条占……%（已去重），……信息占比较高。」
   - 平台：「……主要传播阵地为……，其中……条，占……%；……（详见图3）。涉及我市……，聚焦“……”等。」
   - 内容：「……央级、省级媒体及重要新闻平台……，重点关注……等方面，如“……”……」
   - 负面：「本月监测发现并会同处置涉我市敏感及负面舆情……条（已去重），较去年同期有所下降，……类信息占比约……%，占比较高，涉及……（详见图4）。其中，……（详见表1）。从县（区）分布情况来看，……（详见图5）。」
   - 研判：「从 X 月份网络舆情监测信息来看，网民主要通过……发表诉求，负面舆情内容主要涉及……。其中……类信息发布较多，……容易引发……，极易被舆论放大为……，持续影响……。建议……」
   - 建议：「1.警惕/关注/防范……。X 月……。……建议相关部门……。」
5. **体例**：标题 / 期号 / 发文机关 + 成文日期 / 报告标题；章节用「一、」「（一）」；图用「图1」…「图5」，表用「表1」；建议用「1.」；正文无 Markdown、无编号列表符号；全角标点。

#### 2.4.1 四份历史报告的实测基线（写判断依据时直接引用）

| 位点 | 6 月 | 7 月 | 8 月 | 10 月 | 范围 |
|---|---:|---:|---:|---:|---|
| 全文总字符 | 3393 | 3522 | 3908 | 3915 | 3393~3915 |
| 一（一）总体 | 218 | 222 | 232 | 248 | 218~248 |
| 一（二）平台 | 451 | 500 | 510 | 535 | 451~535 |
| 一（三）内容 | 437 | 447 | 450 | 370 | 370~450 |
| 一（四）负面 | 276 | 280 | 281 | 284 | 276~284 |
| 二（一）研判正文 | 393 | 468 | 371 | 428 | 371~468 |
| 二（二）建议条数 | 3 | 3 | 4 | 4 | 3~4 |
| 二（二）每条字数 | 332~376 | 325~337 | 316~448 | 315~446 | 315~448 |

**由这张表直接得到的三个判断**：

- 基座 `writer.analysis` 要求 300~500 字、建议 350~420 字：历史实测 371~468 字，**落在范围内**，通常不用改。
- 基座 `writer.outlook` / `writer.outlook_field` / `historical_researcher.research` 要求 **4~5 类**：历史实测 **3~4 条**，这是真实冲突，必须问用户（见 5.4 Q1）。
- 基座 `event_summarizer.summary` 要求 15~35 字：历史 TOP10 事件标题多在十几到三十字，**通常不用改**；但要在测试里核对，不能凭印象。

#### 2.4.2 多份历史报告怎么合并

目标不是「取平均」，而是得到两样东西：**固定章节** 与 **动态槽候选**。

1. **章节层**：把每份报告的章节标题抽成有序列表，求交集。
   - 交集 = **固定章节**（四份都有 `一、涉安信息传播态势`、`二、月度风险研判` 及六个二级节）。
   - 差集 = **可选章节 / 客户新增章节**。只在一份报告出现的章节，不直接判固定；先问用户或查模板，再决定「固定 / 动态 / 不要」。
2. **段落层**：在每个章节内按句号/分号切句，做「骨架归一化」：
   - 数字 → `{{number}}`，日期 → `{{date}}`，地名 → `{{locality}}`，类目 → `{{category}}`，平台名 → `{{platform}}`，事件标题 → `{{event}}`。
   - 统计每种骨架在几份报告里出现；**四份都出现**的骨架 = 固定候选，**只在一份出现**的 = 动态候选，**两三份出现**的 = 需人工判断（可能是季节性套话）。
3. **反事实检查**（这是 `template_analyst.template` 的硬要求，不是可选）：
   - 对每个「固定候选」问：下个月数据、平台排名、主要类别、事件、风险变化后，这句话还成立吗？
   - 不成立 → 必须设为动态字段，不能因为「四份文字碰巧一样」就固定。
   - 例：四份报告的平台列表都以「移动客户端」开头，但第 2~8 位每月都变（6 月网站第二、8 月微信公众号第二、10 月网站第二）；平台整段必须动态，不能把顺序固定。
   - 例：四份报告的区县排序都按条数降序，但顺序每月不同；「市区」是报告里的独立口径行，不属于 `vocabulary.localities` 的 8 个区县，不要把 9 行都当词表成员。
4. **产出**：一张 `evidence.md`（可临时放 `.conda/docs/` 或包内 `接入记录.md`），四列：

| 章节 | 固定候选（逐字） | 动态证据（哪几份、哪一段） | 反事实结论 |
|---|---|---|---|

完成判据：每个章节都有固定/动态判定；每个固定候选都有反事实结论；没有「因为多份相同所以固定」这种未检查的条目。

### 2.5 本月全量数据（Excel）

只看两件事：首行列名、每列抽样值。本环境**没有 openpyxl**，用仓库自己的 OOXML 读取器 `core/tools/ooxml.py` 的 `read_xlsx`；`sheet_index` 是 1 起的 `worksheet` 序号（`xl/worksheets/sheet<N>.xml`），不是 tab 名。

```powershell
$xlsx  = '安顺市委10月总数据.xlsx'   # 换成维护者给的本月全量文件
$sheet = '3'                         # 目标工作表序号，A 包是 3

@'
import sys, zipfile, re
x = zipfile.ZipFile(sys.argv[1]).read('xl/workbook.xml').decode('utf-8')
print('tabs', re.findall(r'<sheet [^>]*name="([^"]+)"', x))
from core.tools.ooxml import read_xlsx
b = read_xlsx(sys.argv[1], sheet_index=int(sys.argv[2]), max_rows=4)
print('sheet', b['sheet'])
print('header', b['rows'][0]['cells'])
for r in b['rows'][1:]:
    print(r['excel_row'], r['cells'][:6])
'@ | & $py - $xlsx $sheet
```

A 包实测：`tabs ['Sheet1', 'Sheet5', '03101627']`、`sheet xl/worksheets/sheet3.xml`、`header ['标题','发布时间','来源信息','作者','作者Id','事件分类','网址','媒体环节','媒体属性','媒体级别','舆情调性','是否预警','摘要']`。13 列与 `template.json` 的 `column_map` 12 条键一一对上（`摘要` 走 `summary_columns`）。

> **为什么历史报告和数据表既要上传到界面、也要给建包 agent 读一遍？**
>
> 两件事产出不同的东西：
> - **界面（02 模板确认）** 产出 `template_version` —— 报告的**结构**：有哪些字段、占位符在哪、表格几行几列、版式取自哪份报告。
> - **agent（阶段 3）** 产出 `prompts/agent/*.md` —— 报告的**写法**：每段什么语气、选材标准、数字怎么表述、哪些词不许出现，以及 `writer_slots` 与 `column_map`。
>
> 模板只给字段名，不给写法。同一个字段「总体态势判断」，可能是「同比上升 X%，主要集中在……」也可能是「本期总体平稳，需关注……」，这只能从历史报告原文里读出来。本月数据表同理：agent 要从列名推 `column_map`（字段 ↔ Excel 哪一列），模板确认页只看版式，不看数据表。

### 2.6 输入自检（不通过就停，不要猜）

- [ ] 每份历史报告都能 `parse_report_document` 读出非空 `blocks`（`.doc` 与 `.docx` 都要过，格式分派见 2.0），章节标题能按正则找到。
- [ ] `template_version.status == 'confirmed_by_human'`；`version` / `name` 与客户对应。
- [ ] `fields` 的 `id` 不重复；每个字段都有 `owner`、`kind`、`semantic`；`owner=writer` 的字段能对应到章节。
- [ ] `rules.features` 四个键都在；`rules.event_threshold` 在 `(0,1]`。
- [ ] `packages/<pkg>/template.json` 有 `vocabulary.localities`、`vocabulary.cluster_terms`、`writer_slots`、`data_contract`。
- [ ] `manifest.agents` 里的角色都在 `roles.yaml` 里。
- [ ] 打开 `packages/<pkg>/manifest.yaml`，找到 `features:` 这一段，它下面应该有这 5 行，每行形如 `dedup: {enabled: true}`：
  `locality` / `dedup` / `event_classification` / `first_warning` / `top10`。
  少一行不会立刻报错（该能力按缺省处理），但客户级开关就丢了；把 `enabled` 写成 `enable`（少一个 d）会被 `check_package` 专门报出来：`features.X.enable 不是合法键（少一个 d，应为 enabled）`。
- [ ] `prompts/index.yaml` 的 `agent_prompts` 覆盖 34 个 key；`provenance()` 能跑通。

任一项不满足：把它当作**材料缺口**报告给维护者，不要用推断补。材料缺口不是「判断类问题」，不要混进 5.4 的提问批次。

### 2.7 维护者确认模板之后的第一步

不要先写 `manifest.yaml`。先跑这三条命令看现状，把输出贴进 `接入记录.md` 的「输入」段（这三条是 **agent 自己跑**的，不要把命令发给用户让他执行）：

```powershell
cd D:\智能分析报告重构版V5
$env:PYTHONIOENCODING = 'utf-8'
$py = 'D:\智能分析报告重构版V5\.conda\JJDreport\python.exe'

# 1 基座提示词此刻必须仍然客户无关（新包的地名/类目名会让词数变大，判据是 RESULT: PASS）
& $py scripts\gate_prompt_neutral.py

# 2 记下基座与宿主的字节身份（建完包后四行必须逐字符不变）
& $py -c "import sys;sys.path.insert(0,'scripts');import gate_core_iso as g;o=g.observe(g.REPO/'core',g.REPO/'app');print('CORE-FILES',o['core_files']);print('CORE-DEP',o['core_dep']['sites'],'sites /',o['core_dep']['files'],'files');print('CORE-HASH',o['core_hash']);print('APP-HASH',o['app_hash'])"

# 3 现有包的契约必须全绿（三条用例遍历 packages/*/）
& $py scripts\run_scoped_checks.py tests/test_s7_package_contract.py
```

三条都符合预期才动手：第 1 条不是 `RESULT: PASS` → 基座已经脏了，先报给维护者；第 2 条的四行写进记录，建完包后重跑对比；第 3 条不是 `3 passed` → 现有包已经坏了，新包会继承同一个问题。

然后按顺序做：第二章读输入 → 第五章判缺口并成批提问 → 第七章定 `agents:` → 第三章推需求集、第四章逐条判、第六章写提示词 → 第八章落文件 → 第九章测试对比 → 第十章六条自检 → 把证据贴回 `接入记录.md`。

## 三、能力开关与需求集推导（先定底线，再逐条判断）

### 3.1 三层开关，别混

| 层 | 位置 | 决定 | 谁改 | 对提示词需求集的影响 |
|---|---|---|---|---|
| ① 客户包能力 | `manifest.agents` + `manifest.features` | 这个客户**有没有**这项能力 | 建包时定 | **决定节点是否被裁**（`core/agent_steps.py` 的 `prune_spec`）：裁掉的节点驱动的 key 才可能不写；这是文件集下限的来源之一 |
| ② 模板开关 | `rules.features`（`dedup` / `classification` / `first_warning` / `top10`） | **这一次建模板**要不要用 | 每次建模板 | **不缩小文件集**：只决定这一次调不调，真实影响见 3.6.1 |
| ③ 提示词覆盖 | `packages/<pkg>/prompts/` | 这个客户**怎么写**这段话 | 建包时写 | 30 条必写键按「改写 / 沿用基座」落文件 |

**包级 `manifest.features` 实际只消费三个键**（`core/tools/registry.py` 的 `FEATURE_TOOLS`）：

- `locality`（控制 `resolve_locality`）
- `dedup`（控制 `group_events`、`propose_keyword_event_candidates`、`propose_vector_event_neighbors`）
- `event_classification`（控制 `classify_records`、`cluster_event_themes`、`discover_topics`）

`first_warning` / `top10` **有包级开关**（`manifest.features` 五键之一），但它们**没有专属工具白名单**：`FEATURE_TOOLS['first_warning']` 映射为空组，`top10` 只映射 `select_materials`。所以关掉它们时「给模型的工具清单」几乎不变，真正被停掉的是**口径产物与冻结事实**（不再写 `first_section_warning_event_count`、不再产 TOP10 梗概与榜单），以及模板侧对应段落不再生成。

两层开关的相与发生在 `app/workflow.py` 的 `_template_features`：**生效值 = 包级 AND 模板级**。注意 `resolve_tools` 不认识 `first_warning` / `top10` 这两个键名的模板侧写法（模板级用 `top10`，包级映射到 `select_materials`），所以判断「这次跑不跑」要看生效值，不要只看模板里的 `template_rules.features`。

### 3.2 两条不同的推导：文件集 vs 本次调用集

| 问题 | 能否静态推导 | 结果 |
|---|---|---|
| 「这个客户要交付哪些提示词文件」 | **能**，机械推导 | 34 − 可省 4 = **30 条必写**；指纹读的 17 条与包级 `agents` 无关 |
| 「这个客户这一轮实际会发哪些提示词给模型」 | **不能**，只能给上界 + 逐条条件 | 由 `manifest.agents` + 模板级 `rules.features` + 入口 + **运行时数据/模型返回** 共同决定 |

为什么模板级开关不缩小文件集：

- 模板级开关的语义是「这次建模板用不用」，不是「这个客户永远不用」。
- 同一个客户可以建多个模板：A 模板关掉 TOP10，B 模板可能开。若按 A 模板把 `event_judge.top10` 判成可省不写，B 模板一开就会**静默回退基座**，产出不符合客户体例的结果。
- 包级开关才是能力边界：`manifest.agents` 不声明某角色，图里对应节点会被 `prune_spec` 裁掉；`manifest.features.dedup=false`，`group_events` 等工具直接退出白名单。**但即使节点被裁，指纹读的 17 条照读**——这是底线的第一块；另一块是图节点无条件驱动的 13 条（含模板三轮三键，见 3.3），合计底线 30。

**一致性规则**：包级关了的能力，模板级也要关；否则模板会要求一个产不出来的产物。例：包级 `dedup=false`，模板 `rules.features.dedup` 必须也是 `false`，否则分析门禁 `_analysis_refs()` 仍恒要求 `group_events`，而工具已被扣掉。

### 3.3 需求集 = 必写 30 / 可省 4（外加一个正交标签「待定」）

| 清单 | 判定 | 条数 | 动作 |
|---|---|---|---|
| **必写** | 不管客户声明什么角色、开哪些 `features`，文件必须存在且非空。其中 **17 条**被 `prompt_fingerprint` 无条件读，**13 条**由图节点无条件驱动（含模板三轮三键） | **30** | 写；基座够用也要写一条「沿用基座」+ 一句依据 |
| **可省** | 旁路/条件键，客户真的不用时可以不出文件 | **4** | 不出文件，登记到 `NOT_USED.md`（3.7） |
| **待定**（正交标签，不是第四张清单） | 文件**仍必须存在**，但「这一次调不调」由运行时数据 / 模型返回决定 | 标在必写内部 | 照写；触发条件看该行判据 |

**为什么底线是 30 而不是 15~25**：`core/agent.py` 的 `prompt_fingerprint(prefix=('writer.', 'historical_researcher.'))` 在每次结构化写作开头，把已声明的 13 个 `writer.*` + 4 个 `historical_researcher.*` 一次性全读一遍（17 条），不管这个客户声明了哪些角色。实测：客户包**不声明** `historical_researcher` 时，4 个历史键**仍被 `_write_draft` 路径取用**（`app/structured_writer.py` 的 `_write_draft` 调 `prepare_history`），读不到直接 `ValueError: invalid_agent_prompt` → **整个写作入口 500**。另外 13 条由图节点无条件驱动，其中最容易省错的是模板三键：模板语义研判 2026-11 已重写为**三轮状态机**（`app/template_execution.py`），`template_analyst.batch`（第 1 轮）、`.repair`（第 2 轮）都必跑，`.advice` 在第 2 轮不完美时必跑——详见下表 #27/#28/#31。

> ⚠️ **缺键不会被自检拦住（懒加载）**：`core/agent.py` 已改成 PEP562 懒加载（见 6.4），三键缺失时 `check_package.py` 七段全绿、`import app` 也不报错——`packages/demo_b` 只声明 10 个键（不含模板三键）实测仍 `PKG-OK`。缺键只在该客户**第一次建模板跑到对应轮次**时才抛 `KeyError: 'unknown_agent_prompt:template_analyst.<键>'`。所以**不许用「自检绿了 / import 成功」推断 34 键齐**：键齐不齐只能逐键比对 `index.yaml` 声明集（照抄 anshun 的 34 行）。

34 条逐条分类（顺序 = `packages/<pkg>/prompts/index.yaml` 的 `agent_prompts` 声明序）：

| # | key | 分类 | 判据（为什么落在这张清单） | 依据（文件 · 函数/符号） |
|---|---|---|---|---|
| 1 | `style.application` | 必写·节点 | writer 分析/前瞻段、`content_reviewer`、退修都读它；有写作或审核节点就必须在 | `app/structured_writer.py` 的段提示词拼装；`app/reviewers.py` 的 `run_reviewer` 与退修路径 |
| 2 | `format_reviewer.review` | 必写·节点 | 声明 `format_reviewer` 即驱动 `format_review` + `final_format_review` 两个节点；`review_policy` 也读它做 hash | `app/reviewers.py` 的 `run_reviewer`（`role + '.review'`） |
| 3 | `content_reviewer.review` | 必写·节点 | 声明 `content_reviewer` 即驱动 `content_review` | 同上 |
| 4 | `writer.revise` | 必写·指纹（待定） | 指纹无条件读；真调只在审核意见可机器修时 | `prompt_fingerprint`；`app/reviewers.py` 退修路径 |
| 5 | `historical_researcher.plan` | 必写·指纹（待定） | 指纹无条件读——**不声明该角色也照读**；真调才看角色 + 模板 outlook 段 | `prompt_fingerprint`；`app/historical_research.py` 的 `prepare_history` |
| 6 | `historical_researcher.research` | 必写·指纹（待定） | 同上 | 同上 |
| 7 | `historical_researcher.page_note` | 必写·指纹（待定） | 指纹读；真调只在模型调用 `fetch_historical_page` 时 | `prompt_fingerprint`；`app/historical_research.py` |
| 8 | `historical_researcher.current_note` | 必写·指纹（待定） | 指纹读；真调条件同 `research` | 同上 |
| 9 | `writer.analysis` | 必写·指纹（待定） | 指纹读；真调看模板是否有 analysis 段 | `prompt_fingerprint`；`app/structured_writer.py` |
| 10 | `writer.outlook` | 必写·指纹（待定） | 指纹读；真调看模板是否有 outlook 段 + 历史是否 ready | 同上 |
| 11 | `template_analyst.template` | 必写·节点 | 进模板图即读（`make_input`） | `app/template_review.py` |
| 12 | `writer.general` | 必写·指纹（待定） | 指纹读；真调看模板是否有无 `section_role` 的写作块 | `prompt_fingerprint` |
| 13 | `writer.source_binding` | 必写·指纹（待定） | 指纹读；真调在写作 / 退修 / legacy 槽位 | `app/structured_writer.py`；`core/source_binding.py` |
| 14 | `writer.reference_repair` | 必写·指纹（待定） | 指纹读；真调只在 `SourceBindingError` 后的补引用回合 | `core/source_binding.py` |
| 15 | `writer.analysis_output` | 必写·指纹（待定） | 指纹读；真调条件同 `writer.analysis` | `prompt_fingerprint`；`app/structured_writer.py` |
| 16 | `writer.outlook_field` | 必写·指纹（待定） | 指纹读；真调看 outlook 段 / 有人审推荐字段且有历史 | 同上 |
| 17 | `writer.data_planner` | 必写·指纹（待定） | 指纹读；真调看模板里是否有 `owner=data` 且无 KNOWN 映射、无 binding 的字段 | `app/structured_writer.py` |
| 18 | `writer.slot.base` | 必写·指纹 | 指纹读。**legacy 槽位路径当前不可用，勿承诺**（见 3.11 注） | `prompt_fingerprint`；`core/slot_writer.py` |
| 19 | `writer.slot.themes` | 必写·指纹 | 同上 | 同上 |
| 20 | `writer.slot.narrative` | 必写·指纹 | 同上 | 同上 |
| 21 | `writer.slot.titles` | 必写·指纹 | 同上 | 同上 |
| 22 | `event_judge.top10` | 必写·节点（待定） | `dedup=true` 时 `analyse_events` 会读；`top10=false` 整段不跑 | `core/event_analysis.py` 的 `analyse_events` |
| 23 | `event_classifier.classify` | 必写·节点（待定） | 只由 `dedup` 决定；`classification=false` **不影响** | 同上 |
| 24 | `event_summarizer.summary` | 必写·节点（待定） | `top10=false` 不跑 | 同上 |
| 25 | `event_judge.pairs` | 必写·节点（待定） | `dedup=false` → 节点根本不进 `analyse_events` | 同上 |
| 26 | `event_judge.repair` | 可省·条件 | 只在 TOP10 结构化校验失败的重试轮读（payload 追加，非独立调用） | `core/event_analysis.py` 的 `analyse_events` |
| 27 | `template_analyst.batch` | 必写·节点 | **三轮研判第 1 轮（初稿轮，必跑）**：输出整份模板稿 v1 + 第一轮修改意见，不做完美判定 | `app/template_execution.py` 的 `ROUND_INSTRUCTION_KEY` |
| 28 | `template_analyst.repair` | 必写·节点 | **三轮研判第 2 轮（判定轮，必跑，不是失败兜底）**：对第一轮意见逐条回执 `prior_opinion_resolved` + 6 条固定清单自审，输出完整模板 v2；完美＝结构0错误＋重要0＋建议<3＋意见全 resolved | 同上 |
| 29 | `data_processor.next_tool` | 可省·条件 | 只在任务 `metadata['mode']=='dynamic'`（且非 reprocess_events）时读；走 fallback 计划时从不读 | `app/workflow.py` 的 `_process_records` |
| 30 | `template_analyst.charts` | 必写·节点 | `make_input` 拼提示词必读 | `app/template_review.py` |
| 31 | `template_analyst.advice` | 必写·节点（条件必跑） | **三轮研判第 3 轮（终审轮）**：第 2 轮不完美时必跑——输出**整份**最终模板 v3（不是只提意见）＋全部 advisory 意见；终审仍报「重要」记质量事故。建模板就必须声明，旧「模板修审旁路」已不存在 | `app/template_execution.py` 的 `ROUND_INSTRUCTION_KEY`（旧 `app/template_advice.py` 已删除） |
| 32 | `model.json_output` | 必写·节点 | 拼进每条真实模型请求的 system prompt | `core/model_client.py` |
| 33 | `model.tool_budget_exhausted` | 可省·条件 | 只在带 tools 且工具回合到第 7 轮（`turn==6`）时作为消息追加 | `core/model_client.py` |
| 34 | `hotspot_collector.collect` | 可省·旁路 | 只在首页热点采集接口；独立宿主任务，不在报告图里 | `app/hotspot.py` |

合计数：必写 = 1~25、27、28、30、31、32（共 **30**）；可省 = 26、29、33、34（共 **4**）。

**30 条必写清单全文**（照此核对 `index.yaml`，一条不缺）：
`style.application`、`format_reviewer.review`、`content_reviewer.review`、`writer.revise`、`historical_researcher.plan`、`historical_researcher.research`、`historical_researcher.page_note`、`historical_researcher.current_note`、`writer.analysis`、`writer.outlook`、`template_analyst.template`、`writer.general`、`writer.source_binding`、`writer.reference_repair`、`writer.analysis_output`、`writer.outlook_field`、`writer.data_planner`、`writer.slot.base`、`writer.slot.themes`、`writer.slot.narrative`、`writer.slot.titles`、`event_judge.top10`、`event_classifier.classify`、`event_summarizer.summary`、`event_judge.pairs`、`template_analyst.batch`、`template_analyst.repair`、`template_analyst.charts`、`template_analyst.advice`、`model.json_output`。
**4 条可省清单全文**：`event_judge.repair`（#26）、`data_processor.next_tool`（#29）、`model.tool_budget_exhausted`（#33）、`hotspot_collector.collect`（#34）。

### 3.4 「可省」的唯一安全边界

**只能省 3.3 表里这 4 条，且各自有前提；前提不成立就要写。**

| 可省 key | 不出的前提 |
|---|---|
| `hotspot_collector.collect` | 客户不要首页「今日热点」 |
| `data_processor.next_tool` | 该客户所有任务走 `fallback` 模式（不开动态规划） |
| `model.tool_budget_exhausted` | 该客户所有调用都不带 tools，或已确认到不了第 7 轮 |
| `event_judge.repair` | 客户永不开 `top10`（没有 TOP10 校验失败的重试轮）。保守做法：随 `event_judge.top10` 一起写 |

注意：`template_analyst.repair` 与 `template_analyst.advice` **已不在可省清单里**——三轮研判中第 2 轮固定必跑、第 3 轮在第 2 轮不完美时必跑（常态），建任何客户模板都会用到，缺键自检不拦、跑到对应轮次才炸（3.3 懒加载警告）。旧版「客户不用模板修审接口 / 永不重建模板」两个前提已作废，不得再引用。

**绝对不可省**（省了会 500 或在对应轮次炸）：

- 13 个 `writer.*`，包括 4 个 `writer.slot.*`（legacy 路径虽然跑不通，但指纹照读）；
- 4 个 `historical_researcher.*`——「客户不做历史调研」**不是**不写的理由；
- `model.json_output`、`style.application`、两条 reviewer 键、**5 个** `template_analyst` 结构键（`.template` / `.charts` / `.batch` / `.repair` / `.advice`）、4 条事件键（`event_judge.pairs` / `event_judge.top10` / `event_classifier.classify` / `event_summarizer.summary`）。

**一个已知例外（仍按必写处理）**：包级 `dedup=false` 且模板级对齐时，`analyse_events` 根本不进 → 5 条事件键这一次不被读。但它们仍按必写处理，理由有二：带旧 `group_events` 产物重跑（`reprocess_events` 分支）会让门禁重新满足，`analyse_events` 仍会跑；客户后建的模板可能把 `dedup` 打开。

**拿不准时一律写**，哪怕只写「沿用基座」+ 一句依据。

**声明面口径（已核实，不再存疑）**：加载器**不校验条数**。`core/prompts/registry.py` 的 `_bundle` 对 `agent_prompts` 只有两项校验——非空映射、逐 key 路径可解析；`scripts/check_package.py` 的 `check_prompts` 也只逐 key 校验，PROMPTS 段打印 `N keys: base + overrides` 而不判 `N==34`。实测 `packages/demo_b/` 只声明 10 条（不含模板三键），`PKG-CHECK` 输出 `PROMPTS ok (10 keys: 0 base + 10 overrides)`、`LOAD ok`。但**少声明不是安全动作**：任何被 `get_prompt` 取用而未声明的键都会在**首次取用那一刻**抛 `KeyError: 'unknown_agent_prompt:<key>'`。注意旧版手册说的「`core/agent.py` 顶部 5 个 import 期模块级硬依赖」**已不存在**——旧名 `AGENT_PROMPTS` 等改成了 PEP562 懒加载代理，`import app` 与 LOAD 段都不再触发键校验（见 6.4），缺哪条只有该条第一次被用时才暴露，模板三键因此尤其危险。所以操作口径固定为：**34 条全部声明**；「可省」只表示「不写覆盖、按基座继承」，`NOT_USED.md` 记录前提与证据，不改变声明面。

### 3.5 建包顺序（不能反）

```
① 先定包级能力（manifest.agents 声明哪些角色 + manifest.features 开关）
② 由 ① 定可省清单：默认空 —— 30 条全要
③ 对 30 条必写逐条判断：改写 / 沿用基座
④ 确要省时，只省 3.3 那 4 条，并在 NOT_USED.md 写明前提与证据
```

先写提示词再定能力，会写一堆永远不会被调用的文件；更糟的是，能力后来打开时，没写的条目会静默回退基座。反过来「先省后写」更危险：省错一条不在那 4 条之内的键，要么写作入口直接 500，要么模板研判跑到第 2/3 轮才抛缺键（自检全绿，见 3.3 懒加载警告）。

### 3.6 已知的连带关系（关之前先知道代价）

#### 3.6.1 `rules.features` 四开关的真实影响（实测）

| 开关关掉 | 不再被调的 key | 机制（代码依据） |
|---|---|---|
| `dedup=false` | **5 条事件提示词全停**：`event_judge.pairs` / `event_judge.top10` / `event_judge.repair` / `event_classifier.classify` / `event_summarizer.summary` | `group_events`、`propose_*` 退出工具白名单（`core/tools/registry.py` 的 `FEATURE_TOOLS` + `app/workflow.py` 的 `_processing_policy`）；保底计划删掉 `group_events`；分析门禁 `_analysis_refs()` **恒要求 `group_events`** → 产物不齐 → `after_processing` 走 `finish`，`event_analysis` 节点根本不进 `analyse_events` |
| `top10=false` | 3 条：`event_judge.top10` / `event_judge.repair` / `event_summarizer.summary` | `top10` 分支与榜单/梗概整段被 `if features['top10']` 包住；`select_materials` 也退出白名单 |
| `classification=false` | **0 条** | `analyse_events` **完全不读**这个开关，只读 `top10`；且 `_required_refs` 不再要求 `cluster_event_themes` → 研判节点照跑 |
| `first_warning=false` | **0 条** | 只停口径产物与模板段落（不再写 `first_section_warning_event_count`；`app/api_views/template.py` 的 `PROCESSING_FEATURES`）。没有任何 prompt 以它为条件 |

> 「0 条」不等于「可以关」：`classification=false` 会少掉主题分布段，`first_warning=false` 会少掉第一部分预警句。它们影响产物，不影响提示词条数。
> 「关掉」是**正常配置**，不是 legacy 降级（3.13）：关掉的功能不产段落，但已产出的段落照常要审。
>
> `dedup=false` 的「节点不进」有一个运行期例外：带旧 `group_events` 产物重跑（`reprocess_events` 分支）时门禁可能仍满足，`analyse_events` 仍会跑。这是脏数据/重跑路径，不是正常新任务。

#### 3.6.2 `manifest.agents` 不声明时的连带

| 关掉 / 不声明 | 连带失去 | 报告上表现为 |
|---|---|---|
| 包级 `dedup=false`（且模板级对齐） | 事件归组 → 事件研判 → TOP10 候选 | 无事件级分析、无 TOP10 段 |
| 包级 `event_classification=false` | 记录级分类 / 主题聚类 / 选题发现工具 | 无记录级分类与「主题分布」段；**事件级 5 条提示词一条不少**（`analyse_events` 不读该开关） |
| 模板级 `first_warning=false` | 第一部分重点预警统计与预警句 | 第一部分无预警句；**提示词 0 条受影响** |
| 模板级 `top10=false` | TOP10 事件表、TOP10 候选材料 | 无 TOP10 表；`event_judge.top10` / `.repair` / `event_summarizer.summary` 3 条不调 |
| `manifest.agents` 不声明 `historical_researcher` | 历史调研 → **整段「工作建议」不生成**（不是只少环比句） | `monthly_recommendations` 缺失，`historical_evidence_insufficient`；但 **4 条历史提示词照读**（指纹），必须写 |
| `manifest.agents` 不声明 `event_judge` / `event_classifier` / `event_summarizer` | 三个角色全不声明，`report:event_analysis` 节点才被裁 | 五条事件提示词都不再被读（见 3.10 的粒度警示） |
| `manifest.agents` 不声明 `format_reviewer` / `content_reviewer` | 对应审核节点被裁（`format_reviewer` 一裁就是两个节点） | 没有格式/内容审核轮次 |
| `manifest.agents` 不声明 `writer` | `write_draft` 整段不跑 | 没有机器稿；此时 17 条指纹键才真的不会被读 |
| `manifest.agents` 不声明 `data_processor` | `data_processing` 整段不跑 | 无导入/筛选/去重/分类/选材 |

**两个容易说错的点**：

- 「不声明 `historical_researcher` = 只少历史对比」是错的。实测会连工作建议一起没有；而且 4 条历史提示词仍会被指纹读——省掉它们直接 500。
- 「模板级 `top10=false` = `event_judge.top10` 可省」是错的。它只保证这次模板不调；客户若还有别的模板会开 TOP10，这条仍要留在需求集。**即使客户书面确认永不做 TOP10，也按必写处理**（保存量、可从基座继承），不要登记成可省。

### 3.7 必须登记的「可省」清单

文件：`packages/<pkg>/prompts/NOT_USED.md`（不存在就建；**大多数包不需要这个文件**）。

```markdown
# 本项目可省的提示词

- hotspot_collector.collect
  前提：客户不要首页「今日热点」。证据：Q5 客户确认只用月报，不用首页。
- data_processor.next_tool
  前提：该客户所有任务走 fallback 模式，不开动态规划。证据：manifest / 任务参数。
```

写法要求：

- 一条一行：**key + 不出的前提 + 证据**；前提必须是 3.4 表里那一条。
- **只登记那 4 条可省键**（`event_judge.repair` / `data_processor.next_tool` / `model.tool_budget_exhausted` / `hotspot_collector.collect`）。下列 key 写进这个文件就是错误：13 个 `writer.*`、4 个 `historical_researcher.*`、`model.json_output`、`style.application`、`format_reviewer.review`、`content_reviewer.review`、**5 个 `template_analyst.*`（`.template` / `.charts` / `.batch` / `.repair` / `.advice`）**、`event_judge.pairs` / `.top10`、`event_classifier.classify`、`event_summarizer.summary`。
- **特别记住**：模板三键 `template_analyst.batch / .repair / .advice` 缺一，第 1/2/3 轮研判即在该轮失败，而 PKG-CHECK 不拦（懒加载，3.3）——「客户不用模板修审接口」这类旧理由已作废，advice 现在是第三轮终审，必声明。
- 不要写「暂时不用」。暂时不用 = 这次不调但文件仍要存在 → 按必写处理，状态写「沿用基座」+ 依据。
- 半年后有人问「为什么这个客户没有首页热点」，翻这一个文件就有答案；反过来，有人问「为什么客户不用历史调研还得写 4 条历史提示词」，答案在 3.3，不在这个文件。

### 3.8 两条硬约束（反向比正向更要紧）

```
❌ 某功能启用了，但对应提示词没写
```

这时系统会**静默回退到基座提示词**（前提是该键已在 `index.yaml` 声明、基座文件存在），产出「语法正确但不符合该客户体例」的结果——**而且不报错**。`provenance()` 只会显示 `base`，不会告诉你「这里本该有覆盖」。若键连声明都没有，则不是静默回退，而是首次取用即 `unknown_agent_prompt`（懒加载，3.3/6.4）。

```
❌ 某功能没启用（角色没声明 / 开关关着），提示词也没写
```

这不一定安全，**可能直接 500**：`prompt_fingerprint` 不看角色是否声明，每次结构化写作开头无条件读 17 条（13 个 `writer.*` + 4 个 `historical_researcher.*`）。实测「不声明 `historical_researcher`」的包，4 个历史键仍被读，读不到直接 `ValueError: invalid_agent_prompt` → 写作入口 500。模板侧同理：研判三轮的 `batch/repair/advice` 不随角色裁剪，缺键在第 1/2/3 轮才炸。所以「省」只能省 3.3 那 4 个确认安全的键。

规则只能是二选一：

```
要么按 3.3 那 4 条的口径省（并登记）
要么写（哪怕只写「沿用基座」+ 一句依据）
不存在「不在 4 条之内、但可以不写」
```

为什么：基座兜底是分层查找的正常行为，不是错误；它不会区分「客户确实想用基座」和「客户忘了写」。把「开着但没写」当成合法状态，等于把判断责任推给运行时，而运行时只会静默选基座；把「关着也没写」当成安全，等于把 500 留给客户第一次点「起草」。

### 3.9 角色 → 提示词映射（已按调研填入）

| 角色 | (graph, node) | 该动作内实际读的 key |
|---|---|---|
| `template_analyst` | `template` / `local_compare_and_analysis` | 结构审查：`template_analyst.template` + `template_analyst.charts`（`app/template_review.py` 的 `make_input`）→ **三轮语义研判链**（`app/template_execution.py` 的 `ROUND_INSTRUCTION_KEY`）：r1 `template_analyst.batch`（必跑，初稿 v1＋一轮意见）→ r2 `template_analyst.repair`（**必跑**，意见回执＋6 条自审，出 v2）→ r3 `template_analyst.advice`（**仅 r2 不完美时必跑**，出整份终审 v3＋advisory 意见）。三轮都全量输出整份模板，模型调用 2~3 次 |
| `data_processor` | `report` / `data_processing` | `data_processor.next_tool`（`app/workflow.py` 的 `_process_records`）——**仅 `metadata['mode']=='dynamic'`** |
| `event_judge` | `report` / `event_analysis` | `event_judge.pairs` → `event_judge.top10` →（校验失败重试时）`event_judge.repair`（`core/event_analysis.py` 的 `analyse_events`） |
| `event_classifier` | `report` / **`event_analysis`（同一节点）** | `event_classifier.classify`（同一个 `analyse_events`） |
| `event_summarizer` | `report` / **`event_analysis`（同一节点）** | `event_summarizer.summary`（同一个 `analyse_events`） |
| `writer` | `writing` / `write_draft` | 结构化：`writer.data_planner` / `writer.general` / `writer.analysis` / `writer.analysis_output` / `writer.outlook` / `writer.outlook_field` / `style.application` / `writer.source_binding` / `writer.reference_repair`，**外加 `prompt_fingerprint` 一次性读 17 条**（见 3.3）；legacy：`writer.slot.base/themes/narrative/titles` + `writer.source_binding` |
| `historical_researcher`（内联，不是图节点） | `writing` / `write_draft` 内部 | `historical_researcher.plan` / `.research` / `.current_note` / `.page_note`（`app/historical_research.py` 的 `prepare_history`）；**且无论声明与否都被指纹读** |
| `format_reviewer` | `writing` / **`format_review` 与 `final_format_review`（两个节点）** | `format_reviewer.review`（`app/reviewers.py` 的 `run_reviewer`，走 `role + '.review'`；`review_policy` 也读它做 hash） |
| `content_reviewer` | `writing` / `content_review` | `content_reviewer.review` + `style.application`（同一个 `run_reviewer`） |
| （写手退修） | `writing` / `revise_draft` | `writer.revise` + `style.application` + `writer.source_binding`（`app/reviewers.py` 的退修路径） |

**注（legacy 路径）**：`writer.slot.*` 4 条对应 legacy 槽位写作（`core/slot_writer.py`）。调研实测：用 `template_ref='anshun-monthly-colored'`（legacy 哨兵）建的任务跑 preview-draft，会在 `begin_run` 抛 `KeyError`——`app/reviewers.py` 的 `begin_run` 把哨兵当 artifact id 传给 `store.get_artifact`，而 `core/storage.py` 的 `get_artifact` 对未知 ref `raise KeyError(ref)`。**这 4 条提示词在图上当前不可达，一律「勿承诺」legacy 路径可用**；文件仍必须存在（指纹要读）。结构化模板路径不受影响。写文档/报价/交接时不要承诺「legacy 槽位写作可用」。

### 3.10 裁剪粒度是「节点」，不是「提示词」

| 共用节点 | 覆盖的角色 / 提示词 | 后果 |
|---|---|---|
| `report` / `event_analysis` | `event_judge` + `event_classifier` + `event_summarizer` 三个角色 | 只要**留任一角色**，节点就在，`analyse_events` 照跑；`core/event_analysis.py` 内部没有任何 `agents` 参数或角色判断 → 三个角色的 5 条提示词全部照用。**三个角色全不声明**，节点才消失 |
| `writing` / `format_review` + `writing` / `final_format_review` | `format_reviewer` 一个角色驱动**两个**节点 | 声明 `format_reviewer` = 两个审核节点都在，都读 `format_reviewer.review` |
| `writing` / `content_review` | `content_reviewer` 一个角色驱动**一个**节点 | 声明 `content_reviewer` = 只有 `content_review` |

**结论（必须记住）**：裁剪粒度是「**节点**」不是「**提示词**」。少声明一个角色 ≠ 少写一条提示词；反过来说，不声明某角色也**不一定**会让它的提示词停止被读（指纹那 17 条照读）。要判断「这条提示词的节点还在不在」，看 `core/agent_steps.py` 的 `ROLE_STEPS` + `BYPASS`，不要按角色名字逐条推断。

### 3.11 不做的功能：文件必须在，内容可以只写说明

#### 3.11.1 机制：读取 ≠ 调用

| 动作 | 做什么 | 调模型吗 |
|---|---|---|
| `prompt_fingerprint()` 的读取 | 把 17 条读成文本 → **算哈希** → 当缓存键 | ❌ 不发请求 |
| `historical_research` 的实际调用 | 真调模型做调研 | ✅ 花钱 |

不声明角色 → `app/structured_writer.py` 的 `_write_draft` 里那段条件块不执行 → `prepare_history()` 不跑 → `app/historical_research.py` 整个不跑 → **模型一次都不调**。实测 `test_historical_research_never_runs_when_not_declared`：17 次读取、0 次模型调用。所以那 4 条**只是被读来算哈希，内容不进任何请求**。

但**读取那一刻不允许失败**：文件不存在 → `ValueError: invalid_agent_prompt` → **整个写作入口 500**。

#### 3.11.2 可降级清单（**封闭清单，仅限这 4 条**）

| 键 | 降级条件（必须是**包级事实**） | 判定依据 |
|---|---|---|
| `historical_researcher.plan` | `manifest.agents` 未声明 `historical_researcher` | 该键只在 `app/historical_research.py` 的 `prepare_history` 里被真正调用；角色未声明时 `prepare_history` 不执行；指纹读只算哈希 |
| `historical_researcher.research` | 同上 | 同上（`prepare_history` 内） |
| `historical_researcher.current_note` | 同上 | 同上（`prepare_history` 内） |
| `historical_researcher.page_note` | 同上 | 同上；且**即使声明了角色**，也只在模型主动调用 `fetch_historical_page` 时才读——「声明了但没触发」**不属于**可降级条件 |

四条的共同体：`historical_researcher` 在 `core/agent_steps.py` 的 `INLINE_STEPS` 里（内联在 `write_draft`，不是图节点），所以它不被 `prune_spec` 裁剪，而是在写作代码里按 `manifest.agents` 判条件——这正是「角色未声明 = 确定不调用」成立的原因。

降级后的写法（就这三行，不要写方法论）：

```markdown
# historical_researcher.plan

本客户不做历史调研（`manifest.agents` 未声明 `historical_researcher`）。
本文件仅用于满足 `prompt_fingerprint()` 的读取要求，内容不会被发送给模型。
若未来启用该角色，须重写本提示词。
```

**降级条件只能是包级事实**（`manifest.agents` 未声明该角色）。不能拿下列任一条件去降级：

- 「模板没有 outlook 段」（模板级、会变）；
- 「这次任务缓存命中」（运行时、会变）；
- 「客户说暂时不做」（不是宣言，随时会打开）。

#### 3.11.3 绝对不可降级（红线）

| 类别 | 为什么不能写成说明 |
|---|---|
| 13 条 `writer.*`（含 4 条 `writer.slot.*`） | `prompt_fingerprint` 无条件读，且结构化写作**真的会调用**它们；写空壳 = 报告正文直接塌。`writer.slot.*` 虽因 legacy 路径当前跑不通而读不到，也按红线处理：路径修好后空壳会静默产出空槽位 |
| `model.json_output`、`model.tool_budget_exhausted` | 全局 system prompt / 工具预算，任何真实任务都会用 |
| `style.application` | 跨角色复用（写作 + 内容审核 + 退修） |
| `template_analyst.template` / `.charts` / `.batch` / `.repair` / `.advice` | 建模板时必跑：结构审查两键 + 研判三轮三键（r1 batch、r2 repair、r3 advice），缺键 PKG-CHECK 不拦、跑到对应轮次才炸（3.3） |
| `data_processor.next_tool` | 动态规划模式必跑 |
| `format_reviewer.review` / `content_reviewer.review` | `review_policy` 会把 `role + '.review'` 当 hash 材料读，**即使审核节点被裁**；不能靠「不声明角色」降级 |
| `event_judge.pairs` / `.top10` / `.repair`、`event_classifier.classify`、`event_summarizer.summary` | 三个角色共用一个节点（3.10）：声明任一角色，5 条全用 |
| 任何「角色**已声明**」的情况 | 已声明 = 会被调用，写空壳就是静默减配 |

注：「可省」（3.3）与「可降级」是两回事。可省的键要么不出文件；**一旦决定保留文件，就必须按正文标准写**，不能写成空壳。

#### 3.11.4 违反后果（最难发现的失败）

把**会调用**的键写成空壳 → 报告该段**直接缺失或质量塌陷，而且不报错**。运行时只看到「有文件、有内容、能跑通」，不会告诉你「这一条本来是正文」。这比 `prompt_missing` 难查得多：报错至少说得出哪一条缺，空壳什么信号都不给。

#### 3.11.5 与「可省」的区别（别混）

| | 可省（3.3 那 4 条） | 可降级（3.11.2 这 4 条） |
|---|---|---|
| 文件要不要存在 | **不要** | **要**（指纹会读） |
| 登记位置 | `NOT_USED.md` | `接入记录.md` 的提示词清单：状态 `仅说明（占位）` + 条件 |
| 内容要求 | 无文件 | 一句说明 + 「启用须重写」 |

### 3.12 能力开关矩阵（建包时必须问客户，实测结论）

四个开关都写在 `manifest.features`（客户级硬开关，3.1），与模板级 `rules.features` 相与成生效值。**关掉任何一个都不报错**，所以建包时要把连带影响讲给客户听再定：

| 关掉什么 | 连带影响 |
|---|---|
| 事件去重 `dedup` | 没有事件归组 → 事件研判不发生 → **TOP10 也不产出**（即使 `top10` 开着） |
| 自动分类 `event_classification` | 事件研判照常，但没有记录级分类/主题聚类；**5 条事件提示词一条不少**（`analyse_events` 不读该开关） |
| 第一部分重点预警 `first_warning` | 只停口径产物与模板段落，不影响提示词文件是否存在 |
| TOP10 `top10` | 报告里没有 TOP10 段落，工具清单裁掉 `select_materials` |

**四个全关也能走通完整流程**（建任务 → 数据审核 → 确认 → 写作 → 出报告）。早期环境曾实测产出约 37~38 KB 的 docx，那是当时环境的历史数字（本次未复核），不要拿文件大小当判据。

问客户按「关之前先知道代价」问（5.1.2 第 5 条）：说清关掉后报告里少什么、哪些提示词仍要写、以及为什么「关掉」不等于「省文件」（3.2、3.3、3.4）。

### 3.13 术语：「legacy（旧格式工件）」≠「功能关闭」

两者在报告里的表现可能都是「这段没有」，**处置完全不同**：

| | legacy（旧格式工件 / 旧数据） | 功能关闭（正常状态） |
|---|---|---|
| 是什么 | 迁移前留下的旧格式数据或产物（旧单根 `data/demo.sqlite3`、旧 `group_events` 产物、`writer.slot.*` 的 legacy 槽位路径） | 客户正常选择不启用某项能力（`features.X.enabled: false`） |
| 前端表现 | **降级**：按旧口径读，可能整块不显示 | 正常：该段本来就不生成 |
| 要不要审核 | 要：旧工件仍可能进报告，必须能审核、能追溯来源 | 要：关掉的功能不产段落，已产出的段落照常审核 |
| 处置 | 迁移（`scripts/migrate_data_packages.py`）或按 3.9 注「勿承诺 legacy 路径可用」 | 按 3.6.1 / 3.12 的连带表确认代价，登记进 `接入记录.md` |
| 报告里怎么判 | 数据里有旧格式工件（旧 db / 旧 `group_events` 产物） | `manifest.features` / `rules.features` 的生效值是 `false` |

**不要写「因为是 legacy 所以不用审核」，也不要写「功能关了所以这段是坏数据」**：前者放过该审的旧产物，后者把正常配置当故障。

## 四、34 条逐条差异分析（核心）

### 4.1 先约定证据位点

后文的「判断依据」用这些缩写，指向真实位置，不写空话：

| 缩写 | 指向 |
|---|---|
| S1 / S2 / S3 / S4 | 2026 年 6 / 7 / 8 / 10 月四份 `.docx` 历史报告 |
| §一（一） | 「一、涉安信息传播态势」下的「（一）从总体来看」段 |
| §一（二） | 「（二）从平台上看」段 |
| §一（三） | 「（三）从内容上看」段 |
| §一（四） | 「（四）从负面舆情看」段 |
| §二（一） | 「二、月度风险研判」下的「（一）研判分析」正文 |
| §二（二） | 「（二）工作建议」下的 `1.` 起的条目 |
| 表1 | 文末 TOP10 表（`kind='table'`） |
| 图1~5 | 情绪分布、每日信息量、信源分布、负面分类、区县分布 |
| T | `template_version` 工件；`T.fields` / `T.blocks` / `T.rules` |
| P | `packages/<pkg>/template.json`；`P.vocabulary` / `P.writer_slots` / `P.data_contract` |
| B | 基座 `core/prompts/base/agent/<key>.md` 的正文 |
| U | 用户对 5.4 问题的回答（记 `Q1`、`Q2`…） |

34 行的顺序 = `packages/<pkg>/prompts/index.yaml` 的 `agent_prompts` 声明序，也是 `prompts-S5.json` 的 `prompt_keys` 序。**这张表就是 34 条的完整清单**，不再另抄一份；每条属于「必写 / 可省 / 待定」的那一栏见 3.3。

**引用纪律（agent 自用）**：引用代码位置一律用「**文件 + 函数名 + key 字面量**」，**不写行号**。理由不是洁癖：调研期间 `app/workflow.py` 正在被并行修改，同一个 `get_prompt('data_processor.next_tool')` 调用点在三个不同版本里落在不同位置，`app/workflow.py` 本身也被读到过两个长度不同的版本。位置一漂，文档里的「证据」就变成假的。写不出函数名时退一步写「文件 + 符号字面量」（如 `app/hotspot.py` 的常量 `ITEM_COUNT=30`），也不要写行号。

**这条只管 agent 自己读代码、写 `接入记录.md` 与对比报告**；说给用户听的话不按这条写——按 1.2 的三条规矩翻译成功能描述，不出现函数名、字段名、异常名（1.2 的「不许直接抛内部标识符」）。

### 4.2 34 行必读表

| 键 | 这条产出什么 | 判断「要不要改」的依据 | 通常改什么 |
|---|---|---|---|
| `style.application` | 给写作/审核注入授权声明与文风规则（lieflat-less-ai-tone），被 writer/reviewers 多阶段复用 | 看 S1~S4 是否公文分析体；看 §二（二）是否「建议相关部门…」；看 `manifest.skills.use` 是否含该 skill；看历史有无口语/第一人称/AI 腔 | 通常不改；客户要简报风/口语风才改文风约束（**措辞**），不改取数 |
| `format_reviewer.review` | 审机器稿与 `readonly_data`/`template_layout` 的格式一致性：残缺句、重复、单位、编号 | 看 T.blocks 的固定文字与图注；S1~S4 都是「一、」「（一）」「图1」「表1」「1.」；看历史单位写法（条、%、万余） | 客户编号/图注体例不同才改判据（**措辞**）；单位/数值来自模板/数据，不改取数 |
| `content_reviewer.review` | 审事实、来源、判断强度、篇章逻辑 + 文风；输出 `semantic_judgments` | 看 S1~S4 的判断强度（「较去年同期有所下降」「占比约」）；看客户是否接受无本地历史的季节预警（`T.rules` / 接入记录）；看模板 evidence 字段 | 客户要求更严的本地证据/禁止模型季节知识才改审核口径（**措辞**）；不改事实来源 |
| `writer.revise` | 按两位审核员与本地校验退修机器稿，只改 `editable_fields`，返回 `patches` | 看 T.fields 的 `value_schema` 字数/格式；看 S1~S4 对应段长度；看审核 issue 类型与 `editable_fields` 实际集合 | 通常不改；客户字数/保留数字规则不同才改（**措辞**） |
| `historical_researcher.plan` | 不联网，先比较 5~8 类未来 1~2 个月风险候选（c1~c8） | 看 S1~S4 §二（二）建议条数（3~4）与主题跨度；看未来窗口月份（payload `forecast` / `report_context`）；看客户是否允许季节知识 | 客户只要 3 类/固定主题才改候选数与方向约束（**措辞**）；地区/月份来自 payload，不许硬编码 |
| `historical_researcher.research` | 核对 5 类选题依据（历史/季节/地方活动），至少 4 类；最多 6 轮联网、近 3~5 年 | 看 S1~S4 建议条数（3~4）；看客户是否要求本地历史（接入记录）；看 `manifest.agents` 是否声明该角色（不声明则整段不跑，见 3.6；**但本文件仍必须存在**——指纹无条件读） | 改条数、联网预算、依据类型（**措辞**）；不改地区事实。角色未声明时可降级为一句说明（3.11.2，仅限这类键） |
| `historical_researcher.page_note` | 单页阅读笔记：只给与本地风险相关的连续原文片段，引用用 `excerpt_index` | 看 S1~S4 是否有原文引用/摘录；看客户是否要求可追溯；看网页材料是否可用 | 通常不改；客户禁止网页引用才改（**措辞**）。注意：关角色 ≠ 可以不写文件（3.3），可选的是降级为一句说明（3.11.2） |
| `historical_researcher.current_note` | 声明本月分类只作当前信号，不等于历史同期高发 | 看 S1~S4 是否出现「较去年同期」；看模板/客户是否把本月当历史 | 通常不改 |
| `writer.analysis` | 写 §二（一）研判分析：300~500 字（建议 350~420），2 条风险链，段尾 1~2 句阻断 | 实测 S1~S4 研判正文 393/468/371/428 字；看是否「从 X 月份…来看」开头、是否 2 条链、是否段尾建议；看 T.fields 该字段 `kind=analysis`、`owner=writer`、`value_schema` | 客户字数/结构不同才改阈值与句式约束（**措辞**）；事实来自 evidence/payload，不改取数 |
| `writer.outlook` | 写 §二（二）工作建议：4~5 类，每类 250~400 字（最高 600），面向未来 1~2 个月 | 实测 S1~S4 建议条数 3/3/4/4，每条 315~448 字；看 `index.yaml.template_policy.recommendations`（min4/max5）；看 `templates/<pkg>/report.template.json` 的 `recommendations_max=5`；看 T.rules | 最常见判断是 3~4 还是 4~5；同步改 `writer.outlook` + `writer.outlook_field` + `historical_researcher.research` + `template_analyst.template` + `index.yaml.template_policy`（**策略/措辞**） |
| `template_analyst.template` | 按规则 + 全部历史报告重制模板 `blocks`/`fields`（固定 vs 动态），给人工审核 | 看 S1~S4 的章节/段落/句子；看模板候选；做反事实检查（下月数据变是否仍成立）；看平台/区县/类目顺序是否每月变（实测变） | 基座方法论通常不改；客户专属章节/字段进**模板**（取数/结构），不要写进 prompt；结构根本不同才改（**措辞**），且必须先问 |
| `writer.general` | 按确认模板逐字段填 `values`；可调只读工具补本月原文/统计，不重判事件 | 看 T.fields 的 `owner`/`kind`/`value_schema`；看 S1~S4 对应段落；看 `P.data_contract` 列映射 | 通常不改；字段口径/顺序来自模板，不在 prompt 里硬编码客户字段名 |
| `writer.source_binding` | 引用用程序分配的正整数编号；`source_refs`/`history_refs` 只能是整数 | 看 S1~S4 是否有编号引用/「（详见…）」；看模板字段是否要求 `source_refs`；看 payload `allowed_numbers`/refs | 客户引用格式不同才改（**措辞**）；底层编号规则不改（**契约**） |
| `writer.reference_repair` | 正文已生成，只补选引用，不重写正文 | 看审核 issue 是否有引用缺失；看 S1~S4 引用体例；看 `reference_requests` | 通常不改 |
| `writer.analysis_output` | 约束 `analysis_plan` 的 `source_refs`、300~500 字、恰好 2 条链 | 同 `writer.analysis`；看 `allowed_source_refs` 的实际 ref 类型；看 S1~S4 研判段 | 与 analysis 同步改（**措辞**） |
| `writer.outlook_field` | 5~8 类候选 → 4~5 类；只选类别，依据性质由程序继承 | 看 S1~S4 建议条数；看 `historical_research.topics` 实际类别；看客户是否允许季节/地方活动依据 | 条数/候选数（**措辞**）；类别来自 topics/payload，不写死 |
| `writer.data_planner` | 把模板数据字段映射成计算定义（只给定义不给数值） | 看 `P.data_contract` 的列/口径；看 T.fields 的 data 字段 `binding`；看 S1~S4 数字的分母/单位 | 客户新增指标且现有 binding 不支持时，改**取数来源**（data_contract/工具），不是改 prompt 文案；prompt 通常不改 |
| `writer.slot.base` | 只填一个模板槽位，输出 `slot_id`/`value`/`source_refs`；数字由程序填 | 看 `P.writer_slots`（A 包 9 个）；看 `templates/<pkg>/report.template.json` 的 `slot_type`；看 S1~S4 对应槽文本 | 通常不改；槽位语义/数量来自 `template.json`，不改 prompt。**legacy 路径当前不可用，勿承诺**（见本表末注） |
| `writer.slot.themes` | 主题名称列表：顿号连接证据中语义相符的 theme，不编造 | 看 `P.vocabulary.cluster_terms` 键；看 S1~S4「主题分布」/分类表述；看 T.blocks 的 `theme_cluster` 槽位 | 客户类目名/连接符不同才改**措辞**；类目名进 `template.json`，不进 prompt。**legacy 路径当前不可用，勿承诺** |
| `writer.slot.narrative` | 问题概述：只写证据中与槽位语义相关的事件，不加证据外事实 | 看模板 `narrative_from_sources` 槽位语义；看 S1~S4 对应段 | 通常不改。**legacy 路径当前不可用，勿承诺** |
| `writer.slot.titles` | 报道标题原文引用；多个按模板标点连接；`source_refs` 1~3 | 看模板 title 槽位；看 S1~S4 标题引用格式（引号/顿号/分号） | 客户标题格式不同才改标点/数量（**措辞**）。**legacy 路径当前不可用，勿承诺** |
| `event_judge.top10` | 核对 TOP10 前 30 候选，按同一具体事件分组，覆盖 `allowed_ids` | 看 `T.rules.features.top10` 是否为 true；看模板 TOP10 表；看 S1~S4 表1 的 10 行；看 `select_materials` 是否在白名单 | 通常不改；TOP10 口径（负面+预警/去重/排序）在模板 rules，不在 prompt；文件一律要写（3.3） |
| `event_classifier.classify` | 对每个已去重事件按主体/事实分类，`items` 覆盖每个 id | 看 `P.vocabulary.cluster_terms` 键；看 S1~S4 事件分类/主题；看 `manifest.features.event_classification` 与 `T.rules.features.classification` | 类目集合来自 vocab/payload，不改 prompt；客户分类依据不同才改**措辞** |
| `event_summarizer.summary` | 事件梗概 15~35 字，一句话，只写谁/哪里 + 发生什么 + 有依据后果 | 看 `T.rules.summary_min_chars/max_chars`；看 S1~S4 表1 事件标题长度/风格；看模板 summary 字段 | 客户梗概字数不同才改阈值（**措辞/规则**）；数量来自 template/rules |
| `event_judge.pairs` | 逐项判两组代表记录是否同一具体事件（same/different/uncertain） | 看 S1~S4 表1 是否有「（重复发布）」/同事件多篇；看数据重复程度；看 `human_distinct_pairs` | 通常不改；「同主题算不算同事件」是判断类，客户口径不同才改判据（**措辞**），且要问 |
| `event_judge.repair` | 修正前次覆盖/分组错误，返回完整结果 | 看上轮校验错误；看 S1~S4 事件边界 | 通常不改 |
| `template_analyst.batch` | **第一轮初稿（必跑）**：对照历史报告逐段修改机器模板，一次性输出整份模板稿 v1，同时在 `review_items` 给第一轮修改意见（「重要/建议」两级）；不做完美判定（`app/template_execution.py` 的三轮状态机，r1 经 `ROUND_INSTRUCTION_KEY` 取本键） | 看模板块总数；看 S1~S4 报告长度（3.4k~3.9k 字） | 通常不改；客户结构特殊才改（**措辞**），不得改成「分批输出/只修错误字段」 |
| `template_analyst.repair` | **第二轮判定（必跑，不是失败兜底）**：逐条核对第一轮意见并回执 `prior_opinion_resolved`，按 6 条固定清单自审，输出完整模板 v2；完美＝结构0错误＋重要0＋建议<3＋一轮意见全改到位，不完美则自动进第三轮 | 看 6 条自审清单与客户体例是否冲突；看校验错误 | 通常不改；客户包覆盖时不得删掉意见回执、6 条清单与整份输出契约 |
| `data_processor.next_tool` | 每轮只选一个工具：导入→筛选→属地→候选→去重→分类→聚类→选材 | 看 `manifest.tools.allow`/`capabilities.require`/`features`；看 S1~S4 需要的图/表/TOP10/属地产物；看 T.rules | 客户关能力时白名单裁剪；prompt 步骤描述可能要同步（**措辞**），但不要用 prompt 绕过白名单（**取数/工具**） |
| `template_analyst.charts` | 图表规则：调性/平台饼图、分类纵向柱状、日趋势折线 | 看 `P.charts` 的 `family`/`style`（A 包 5 张）；看 S1~S4 图1~5 类型；看客户是否要不同图 | 客户图表类型不同才改规则/模板 charts（**取数/样式**）；prompt 通常不改 |
| `template_analyst.advice` | **第三轮终审（第二轮不完美时必跑）**：在 v2 基础上输出**整份**最终模板 v3（不是只提意见！），另给仅供人工参考的 advisory 意见（可采纳可忽略）；终审仍报「重要」会记质量事故 | 看 T.fields 边界/owner；看 S1~S4 原文；两轮仍未改到位的差异 | 通常不改；客户包覆盖时**不得删掉整份输出与两级 severity 约束**，否则第三轮候选结构直接坏 |
| `model.json_output` | 强制只输出符合给定 JSON Schema 的对象，不解释不加 Markdown | 看所有模型调用都带 `response_schema`；客户无例外 | 不改 |
| `model.tool_budget_exhausted` | 预算用完只依据已读资料总结；证据不足写缺口，不编造/不再调工具 | 看 `manifest.tools.budgets`（A 包 `default: 40`、`writing: 80`）；看客户数据量 | 通常不改；预算在 manifest 改 |
| `hotspot_collector.collect` | 从检索结果挑 30 条要闻，排序/归类/链接，只输出 JSON | 看 `payload.categories`；看 `app/hotspot.py` 的常量 `ITEM_COUNT=30` 与同一文件的硬校验；看 S1~S4 月报没有首页热点（它是独立开关）；看客户是否要首页热点 | 若要 20 条，**不能只改 prompt**（会 `hotspot_items_incomplete`），必须改代码/配置并立项；类别来自 payload，不要硬编码 |

**本表两条读法**：

1. 「通常改什么」栏说的是**判断**（改写 / 沿用基座）；「这条属于必写还是可省」看 3.3 的分类表，不要从这里推。
2. 4 条 `writer.slot.*` 标注「legacy 路径当前不可用，勿承诺」的确切含义：用 `template_ref='anshun-monthly-colored'` 建的任务跑 preview-draft，写作图 `validate_input` 就抛 `KeyError`（`app/reviewers.py` 的 `begin_run` 把哨兵当 artifact id → `core/storage.py` 的 `get_artifact` 对未知 ref `raise KeyError(ref)`），根本走不到槽位写作。所以这 4 条**只能按「必然存在、本次不会调」处理**：写文件（可从基座继承），但不要在任何交付物里承诺 legacy 写作可用。
3. 碰到**图表/工具能力**的判断（能不能加一张图、某个工具该改哪里），先读第十三章：落点已列全，不要通读 `core/`、`app/` 找答案。

### 4.3 填表方法（避免把「判断」写成「感觉」）

每行按四步填：

1. **找产物**：这条提示词被哪个阶段、哪个字段/工具消费？看 B 的正文和调用点；不确定就写「需实测」。
2. **找证据**：在 S1~S4 的哪个位置能看到这个产物的「客户体例」？在 T/P 的哪个字段能看到「客户口径」？证据必须能指到文件 + 段落/字段，不写「历史报告风格如此」。
3. **判性质**：是**措辞**问题（字数、句式、称谓、语气、编号）还是**取数/结构**问题（字段、词表、binding、工具、模板）？前者改 prompt；后者改 `template.json` / 模板 / manifest，或登记为缺口。
4. **写结论**：`改写` 或 `沿用基座`。只有 3.3 的 4 条可省键才可能「不出文件」，且必须先核 3.4 的前提；其余 30 条一律写。

#### 4.3.1 五个最容易写错的点

1. **`b5_cover` / `b5_amber` 不是提示词 key**。34 条是 `core/prompts/base/agent/*.md` 的文件名；`B5_COVER` 是 `templates/anshun_monthly/report.template.json` 的占位符 id。写文档/提问时不要把字段 id 当 prompt key。
2. **`writer.outlook` 的 4~5 类与历史的 3~4 条冲突**。这是真实冲突，必须问用户；不要默认按基座 4~5 写，也不要把历史 3 条硬编码。
3. **`template_analyst.template` 的「多篇相同 ≠ 固定」**。平台列表、区县排序、类目列表、代表事件都可能每月变；必须先做反事实检查，再决定固定/动态。
4. **`event_judge.top10` 不能因为「这次模板关了 TOP10」就不写**。模板级 `top10=false` 只影响这一次；它不改变「文件必须存在」。即使客户书面确认永不做 TOP10，也按必写处理（可从基座继承）。
5. **`hotspot_collector.collect` 的 30 条是代码硬校验**。对照表与 `roles.yaml` 还写 20（陈旧），以 `app/hotspot.py` 的 `ITEM_COUNT=30` 和 prompt 正文为准；改 prompt 到 20 不会生效，会直接失败。

#### 4.3.2 最难写对的 5 条（按返工概率排序）

1. **`writer.outlook`**：要同时满足 4~5 类、每类 250~400 字、类别必须来自 `historical_research.topics`、依据性质不能吹成「本地高发」、不能逐条改写本月 TOP10；历史却只有 3~4 条。条数、依据、结构三个变量互相牵制，最容易写成「本月事件处置清单」。
2. **`template_analyst.template`**：要把「固定 vs 动态」划对，还要做反事实检查；平台列表、区县排序、类目列表、代表事件都可能每月变。划错一次，后面所有 writer 都会继承错边界。
3. **`writer.analysis`**：300~500 字、2 条风险链、不能统计复述、不能写「容易发酵、影响形象」这种跳步结论；历史正文 371~468 字，给了体例但没给可机械套用的句式，最考验「理解语义单元」。
4. **`event_judge.top10`**：TOP10 是「负面且预警、按事件去重、按事件内条数排序」，还要覆盖 `allowed_ids` 每个 ID 且只出现一次；模板级 `top10=false` 与「永远不做 TOP10」的区分也容易写错。
5. **`hotspot_collector.collect`**：30 条是代码硬校验，类别来自 `payload.categories`，URL 必须原样照抄；改条数不是改 prompt 能解决的。它是「提示词边界 = 代码契约」的典型。

## 五、立项决策（哪些必须问用户）

### 5.1 一条硬分界线

| 类型 | 例子 | 谁负责 |
|---|---|---|
| **事实类**（能从材料确定的） | 本市几个区县、有哪些类目、报告第几期、章节序列、字数分布、平台列表、TOP10 有没有 | **agent 自己读，不许问** |
| **判断类**（材料里读不出来的） | 要不要 TOP10？章节称谓用「一、」还是「（一）」？公文风还是简报风？工作建议 3~4 条还是 4~5 条？ | **必须问用户** |

判定方法：先在第二章的材料里找；找得到就是事实，找不到或材料互相矛盾才是判断。**发问前先过一遍 1.2 的自查表**：读文件、调 `GET /api/...`、跑 `scripts/check_package.py`、查字段/常量在哪定义、看某个包能不能被系统识别——这五类都是 agent 自己能查的，查完把结果写进「证据」，不写成「请你确认」。只有客户业务事实 / 界面操作 / 物理环境三类才让用户做（1.2）。**不要把自己没读全的东西包装成判断类问题。**

#### 5.1.1 事实类：读哪里

| 事实 | 读哪里 |
|---|---|
| 区县清单 / 别名 | `P.vocabulary.localities`；数据里出现的写法用 `resolve_locality` 核对 |
| 类目清单 | `P.vocabulary.cluster_terms` 的键（顺序 = 枚举序） |
| 报告期号 / 月份 / 成文日期 | 历史标题（`2026年第N期`）+ 任务参数 `issue_number` / `report_month` / `publication_date` |
| 章节序列 / 称谓 | S1~S4 的 `text`；T.blocks |
| 每章字数 / 建议条数 | 2.4.1 实测表 |
| 平台列表 / 区县排序 | S1~S4 对应段；以数据为准，不是固定文字 |
| TOP10 有没有 / 几条 | T.rules.features.top10；T.blocks 的 TOP10 表；S1~S4 表1 |
| 提示词会不会被调用 | `manifest.agents` / `manifest.features`；3.6 的连带表 |
| 写作字数 / 梗概字数 | B 的正文 + T.fields.value_schema + T.rules |

#### 5.1.2 判断类：只问这些

只有下列情况才问；每问都要能说清「为什么材料里读不出来」：

1. **历史与基座冲突**：如建议条数历史 3~4、基座 4~5；只能人选一个。
2. **多份历史互相矛盾**：如两份报告章节称谓不同，无法判断客户要哪种。
3. **材料缺失且影响结构**：如模板没有 TOP10 字段、客户却提到 TOP10；需要确认要不要补。注意：预设分类装得下的定性内容，用户在确认弹窗选「自定义：我自己定义这个字段」就能自己补（生成 `custom_field_N`，见 1.5.4 ④），不必升级成提问；只有自定义也覆盖不了的结构性缺口（新章节、新图表、取数来源）才问。
4. **业务取舍**：如是否允许「无本地历史、仅季节机制」的预警；是否保留「较去年同期」这种无数字同比。
5. **代价性开关**：如不要历史调研（会连工作建议一起没有）、不要分类（会没有主题分布）；必须让用户知道代价再关。
6. **代码硬约束与客户要求冲突**：如首页热点客户要 20 条，但代码硬校验 30；这不是 prompt 能解决的，必须问是否接受 30 或立项改代码。

### 5.2 建包 12 项缺口表

把下面的清单逐项对照第二章的读盘结果，判成三类，写进 `packages/<新包>/接入记录.md`：

- ✅ **已有**：输入里字面存在，直接抄。
- 🔶 **可推导**：按表里的推导规则能算出来，且能用命令复核；写进文件并注明依据，**不问**。
- ❓ **必须问**：两条都不成立，问维护者。

判定是机械的：一项只能落在三类之一；说「应该是」就是没判完。

| # | 必需项 | 判定 | 推导规则 / 复核依据 | 什么情况转 ❓ |
|---|---|---|---|---|
| 1 | package 名、report_type | 🔶 | 包名 = 目录名 = `manifest.package` = `template.json.package`（现成包都同值；不一致不会启动失败，但审计行与目录对不上）。`report_type` 取客户报告名称 | 客户同时出多种报告、本期只做一种 → 问做哪一种 |
| 2 | 必需列 `required_columns` | 🔶 | 导入器只校验这个清单，缺列抛 `missing_required_columns`（行为在 `core/tools/records.py` 的 `import_records`；常量出口在 `core/tool.py` 的 `_LAZY['REQUIRED_COLUMNS']`，懒代理指向 `core/tools/vocabulary.py` 的 `required_columns()`——records.py 内已无模块级常量）。现成包都是 `['标题','舆情调性']` | 首行里没有能判调性的列 → 问用哪列判调性 |
| 3 | 列映射 `column_map` | 🔶 | 首行中文列名 → records 英文字段；**键序就是 records 的字段序**（`tests/test_s2_manifest_vocabulary.py` 的 column_map 顺序用例钉住，哈希门禁看不见这层）；常量出口同在 `core/tool.py` 的 `_LAZY['COLUMN_MAP']` | 首行有映射表之外、但客户要求进报告的列 → 问映到哪个字段 |
| 4 | 摘要列 `summary_columns` | 🔶 | `[0]` 优先，缺失时取 `[1]` 并截 1200 字（截断行为在 `core/tools/records.py` 的 `import_records`；常量出口在 `core/tool.py` 的 `_LAZY['SUMMARY_COLUMNS']`）；某列不存在不会报错，取空串 | 首选列与兜底列都在首行里 → 问哪一列是正文摘要 |
| 5 | 工作表序号 `sheet_index` | 🔶 | 记在 `data_contract.sheet_index`。**该键目前无消费者**：实际 sheet 来自任务参数，缺省 3（`app/main.py` 的请求参数 `sheet_index:int=3`；`app/workflow.py` 里取 `state.metadata.get('sheet_index',3)`） | 目标表不是第 3 个、且客户会每期换位置 → 问固定哪一个 |
| 6 | 区县清单 `localities` | 🔶 候选 / ❓ 范围 | 候选 = 2.5 数据里出现的行政区写法（噪声很大，见 5.3）；`resolve_locality` 只做词表子串匹配，要求**恰好命中 1 个**（`core/tools/locality.py`） | **辖区范围一律必须问**（见 5.3） |
| 7 | 类目词典 `cluster_terms` | 🔶 候选 / ❓ 口径 | 候选 = 模板图注字段名 + 数据 `事件分类` 列取值分布；键序 = 枚举序（`core/tools/vocabulary.py` 的 `cluster_terms()`）；词典打分 = 词表成员在 `title + 摘要前300字` 的出现次数求和取最大（`core/classify/dictionary.py` 的 `DictionaryStage`） | **分类体系/类目口径一律必须问**（见 5.3） |
| 8 | 去重参数（4 个） | 🔶 | `data_contract.dedup`：`threshold`、`candidate_floor_ratio` 必填无默认；`merge_rounds` 缺省 1、`merge_threshold` 缺省 0.5（`core/tools/vocabulary.py` 的 `dedup_threshold` / `dedup_candidate_floor` / `dedup_merge_rounds` / `dedup_merge_threshold`）。现成包实测均为 0.65 / 0.6 / 2 / 0.5 | 客户对「什么算同一事件」有明确口径且与 0.65 冲突 → 问 |
| 9 | 图表清单 `charts` | 🔶 | 从模板图注推导 `id/drawing_index/family/style/binding/unit/scope/axis_label`；`manifest.charts.use` 必须与 `template.json` 的 `charts[].id` 同集合。id 不限于基座 5 个；先判断能否复用已有图族与取数口，不能再考虑补取数 | 模板里有图的位置但看不出画什么，或口径能否复用已有统计判断不了 → 问 |
| 10 | `agents:` 声明 | ❓ | 无证据可推 | **一律必须问**（见 5.3 与第七章） |
| 11 | 提示词覆盖面 | 🔶/❓ | 先按 3.3 推导需求集：必写 30 条逐条判「改写 / 沿用基座」，4 条可省须按 3.4 前提登记。基座够用 = 「沿用基座 + 依据」，不是「不判断」 | 客户口径/口吻与基座冲突、且材料裁决不了 → 问（模板见 5.4 Q1/Q6/Q7） |
| 12 | 报告月份/期号/成文日期来源 | 🔶 | 来自任务参数 `report_month` / `issue_number` / `publication_date`（`app/main.py` 的请求参数）；期号可从报告标题推出（`2026年第99期` → 99，`tests/test_report_parameters.py` 钉住） | 客户报告标题不含期号 → 问期号从哪来 |

### 5.3 三项必问（辖区 / 分类 / agents）

#### 5.3.1 ❓ 辖区范围（localities）

- **为什么需要**：`resolve_locality` 只用这份词表做子串匹配（`core/tools/locality.py`），词表外的地名不会出现在属地统计与属地图里。
- **不给会怎样**：命中 0 个或 ≥2 个都进 `needs_review`，第一部分属地表空、属地图无数据，且**不报错**。
- **默认值**：没有。不能拿 A 包的八区县顶替——那是另一个客户的辖区。
- **候选从哪推导**：扫数据的行政区写法（下面是噪声候选，只用来提问，不要直接落文件）：

```powershell
@'
import sys, re, collections
from core.tools.ooxml import read_xlsx
b = read_xlsx(sys.argv[1], sheet_index=int(sys.argv[2]), max_rows=2000)
hdr = b['rows'][0]['cells']; ti, si = hdr.index('标题'), hdr.index('摘要')
pat = re.compile(r'[\u4e00-\u9fa5]{2,6}?(?:自治县|县|区|镇|街道|开发区)')
c = collections.Counter()
for r in b['rows'][1:]:
    cells = r['cells']
    text = (cells[ti] if ti < len(cells) else '') + ' ' + (cells[si] if si < len(cells) else '')
    c.update(pat.findall(text))
print(c.most_common(40))
'@ | & $py - $xlsx $sheet
```

实测（A 包 10 月数据前 2000 行）：候选里既有 `西秀区(74)`、`普定县(38)`、`黄果树景区(46)` 这种真辖区，也有 `其余地区(71)`、`省的北部地区(48)`、`位于黄果树景区(32)` 这种垃圾，还有 `安顺市西秀区(19)`、`安顺市关岭自治县(16)` 这种**全称写法**。所以候选只能当提问素材。
- **影响面**：`resolve_locality` 的未解项、报告属地统计口径、`locality` 图。
- **问法（四段，照 1.2 写）**：
  > **问题：** 这份报告的辖区范围是哪几个行政区？每个区在数据里写成什么样？
  >
  > **证据：**
  > · 报告里的一段文字必须**恰好被认出 1 个**辖区；认出 0 个或 2 个以上都算没定，属地表空、属地图没有数据，**全程不报错**。
  > · 差异在写法：A 包 10 月数据前 2000 行实测，同一辖区有简称也有全称（「西秀区」74 次 / 「安顺市西秀区」19 次），候选里还混着「其余地区」「位于黄果树景区」这类非地名噪声。
  > · 基座没有默认辖区——抄别的客户的八区县，就是把别人的事实塞给这个客户。
  >
  > **有哪些选择：** A 按数据里出现过的**全部写法**建全词表（含全称/简称/别名）；B 只按报告里的标准区名建，别名留给人工确认；C 不按辖区拆分（写一条整体称谓兜底 + 关掉属地统计，见 5.3.4）。
  >
  > **不同的选择会有什么影响：** A 属地表与属地图完整、未解项最少，代价是词表变大。B 部分记录要人工确认，报告里可能缺行。C 报告没有属地表与属地图，只改一个开关。

#### 5.3.2 ❓ 分类体系（cluster_terms）

- **为什么需要**：类目名是报告「事件分类」图与事件分类结果的取值集合；词典级的判据是词表成员出现次数之和取最大，**全 0 命中就判不出来**。
- **不给会怎样**：`dictionary_no_hit` → 事件分类列空、事件全落人工确认；流程照常走完，**不报错**。
- **默认值**：没有。不能抄 A 包的 12 类目。
- **候选从哪推导**：数据 `事件分类` 列的取值分布 + 模板图注字段名 + 摘要高频词：

```powershell
@'
import sys, collections
from core.tools.ooxml import read_xlsx
b = read_xlsx(sys.argv[1], sheet_index=int(sys.argv[2]), max_rows=2000)
hdr = b['rows'][0]['cells']; ci = hdr.index('事件分类')
c = collections.Counter()
for r in b['rows'][1:]:
    cells = r['cells']
    c[(cells[ci] if ci < len(cells) else '').strip() or '(空)'] += 1
print(len(b['rows']) - 1, 'rows')
print(c.most_common(30))
'@ | & $py - $xlsx $sheet
```

实测（A 包 10 月数据）：`1999 rows`、`[('(空)', 1999)]` —— 源数据分类整列为空。这种情况候选**只能**从模板图注（`template.json` 里 `theme` 图与 `事件分类` 字段名）与摘要高频词推，口径必须问，不许自己编 12 类。
- **影响面**：`classify_records`、`cluster_event_themes`、`discover_topics`、`theme` 图、事件清单的分类列。
- **问法（四段，照 1.2 写）**：
  > **问题：** 分类体系用哪几个类目？每个类目在数据里用什么说法能被认出来？
  >
  > **证据：**
  > · 类目名是「事件分类」图与分类结果的取值集合；一份记录都认不出来时，分类整列空、事件全落人工确认，流程照常走完、**不报错**。
  > · 差异在候选来源：A 包 10 月数据实测 1999 行，「事件分类」整列为空——候选只能从模板图注与摘要高频词推。
  > · 基座只能枚举客户自己的类目，给不出默认值。
  >
  > **有哪些选择：** A 按客户报告/模板图注的类目全名单建（每类带数据里真实出现的说法）；B 直接用数据源分类列的取值（本月实测整列为空，等于做不成）；C 不做事件分类（词表写一条占位 + 关掉分类能力）。
  >
  > **不同的选择会有什么影响：** A 分类与主题聚类可用，报告里有分类图与主题分布段。B 本月不可行，要有分类列的数据才成立。C 没有主题分布段与分类图，但写作量不减（相关的 5 条提示词照样要写）。

#### 5.3.3 ❓ agents 声明（要做哪些步骤）

- **为什么需要**：这一段直接决定哪些流程步骤跑、哪些整段跳过（第七章）。
- **不给会怎样**：不写 = 9 个角色全启用，历史调研会联网检索、两位审核员会各跑一轮。
- **默认值**：不写 `agents:`（全部启用）。这也是老包兼容语义。
- **候选从哪推导**：没有。没有任何输入能证明客户要不要历史调研/双审/事件研判。
- **影响面**：图结构（节点被裁 + 前驱改接）、耗时、外部请求、审核轮数、人工确认点。
- **问法（四段，照 1.2 写）**：
  > **问题：** 这份报告要跑哪些步骤——历史调研（联网核对未来选题）、格式审核、内容审核、事件研判（同事件判定 / 分类 / 梗概），各自要不要？
  >
  > **证据：**
  > · 不点名 = 9 个步骤全跑；点名 = 只跑列出的，未列步骤整段裁掉，报告里对应段落随之消失。
  > · 两处连带比字面大：①「同事件判定 / 分类 / 梗概」三步共用一个环节，点名任一个就整段跑（3.10）；②不做历史调研时，**整段「工作建议」不生成**（不是只少一句环比，3.6.2 实测）。
  > · **没有任何客户材料能证明客户要不要联网调研与双审**——这是纯取舍，不是事实。
  >
  > **有哪些选择：** A 全部照跑（9 个步骤全启用，最全也最慢）；B 只列真要的步骤（其余整段裁掉）；C 关历史调研与双审、保留事件研判（省外部请求与审核轮次）。
  >
  > **不同的选择会有什么影响：** A 每期联网检索 + 两轮审核，耗时最长、有外部请求。B 被裁掉的步骤对应的报告段落整段消失，耗时随之下降。C 省外部请求与审核轮次，质量由人工兜底。

#### 5.3.4 问辖区/类目时，先分清两件事（客户说「不涉及」怎么答）

客户答「报告不涉及自己辖区分组数据」「不涉及事件分类」时，按字面理解成「词表留空」，包直接建不起来。两件事要分开：

| 问题 | 能不能空 | 怎么定 |
|---|---|---|
| `vocabulary.localities` 写什么 | **不能空**（`scripts/check_package.py` 报 `vocabulary.localities 必须是非空映射`） | 报告怎么划分区域就怎么写；不分区域就写一条整体称谓 |
| 属地统计要不要用 | 可以关 | `manifest.features.locality.enabled: false` |
| `vocabulary.cluster_terms` 写什么 | **不能空**（同上，报 `vocabulary.cluster_terms 必须是非空映射`） | 报告有哪些类目就写哪些；不做分类就写一条占位 |
| 事件分类要不要用 | 可以关 | `manifest.features.event_classification.enabled: false` |

**客户说「不涉及」时，不要理解成留空**，而是三步：

1. 词表写最小合法内容（一条真实出现的称谓/类目；别名列表可以是空 list）；
2. 把对应 `manifest.features.*.enabled` 设成 false；
3. 在 `接入记录.md` 的问答记录里写明「客户明确不做辖区拆分 / 不做事件分类」（证据 = 哪一轮问答）。

**后果对照**：词表留空 → `check_package` 直接 FAIL（TEMPLATE 段），包建不起来；词表非空但能力关掉 → 合法，报告里不生成相应段落——`locality: false` 时 `resolve_locality` 不进工具白名单，属地统计与属地图没有数据；`event_classification: false` 时没有记录级分类与主题分布（连带见 3.6.2 / 3.12）。

**问法也要改**：不要问「辖区/类目有哪些（可留空）」——那是个会让客户答「留空」的坏问题。要按四段问：「问题：报告怎么分区域 / 有哪些类目；证据：留空会让 `check_package` 直接 FAIL（TEMPLATE 段），而词表非空 + 能力关掉是合法的；选择：按维度建词表 / 不做这一个维度；影响：报告少哪一段、改哪个开关」。客户答「不做」时你要拿到的是「关能力 + 写最小词表」，不是「空着」。

### 5.4 判断类问题库（按需选，一次最多 4 个）

若客户对提示词口径有硬要求，下面七问覆盖了 34 条里所有真实冲突。**一次只问一批（≤4 个）**。

每问按 1.2 的四段写（问题 / 证据 / 有哪些选择 / 不同的选择会有什么影响）。**Q3 是标准范例**：它由一次真实失败的问题改写而来（原标题写「Q3 图3【信源分布】怎么处理（机制缺口）」，正文按「背景 → 我的建议 → 为什么问你」排，构建者读完仍不知道客户的做法与基座差在哪）。新写的问题照 Q3 的排法与颗粒度写。

**Q1 工作建议条数**

> **问题：** 这份报告的工作建议写 3~4 类还是 4~5 类？
>
> **证据：**
> · 历史四期：6 月、7 月各 3 条，8 月、10 月各 4 条，每条 315~448 字（2.4.1 实测）；基座写死 4~5 类、每类 250~400 字。
> · 差异：客户有时只写 3 条，低于基座下限——照基座走，每期多 1~2 类、篇幅变长。
> · 材料里没有第三份证据能裁决该听哪边。
>
> **有哪些选择：** A 按历史取 3~4 类；B 按基座取 4~5 类（不改任何文件）；C 放宽成 3~5 类（上下限都动）。
>
> **不同的选择会有什么影响：** A 与历史篇幅一致；改动落在条数设定与 3 条提示词的措辞上，不动代码。B 一行不改，但每期比历史多 1~2 类，正文变长。C 改动面同 A，只是下限放到 3 类、上限仍 5 类。

**Q2 历史调研角色要不要**

> **问题：** 这个客户要不要「联网核对未来 1~2 个月风险选题」这一步？
>
> **证据：**
> · 要这一步：每期联网检索一次，报告里有「二（二）工作建议」段。
> · 不要：省掉外部请求与联网耗时，但**整段「工作建议」不生成**，不是只少一句环比（3.6.2 实测）。
> · 历史四期都有这一段（3~4 条），并出现「较去年同期」这类跨期表述（2.4 第 4 项）。
>
> **有哪些选择：** A 要这一步（保留联网调研与工作建议）；B 不要（省掉外部请求，但报告没有工作建议段）。只有「要 / 不要」两种状态：把提示词写得多好，都补不回被裁掉的段落。
>
> **不同的选择会有什么影响：** A 每期一次联网检索（最多 6 轮、近 3~5 年），耗时与外部依赖都在这。B 报告整段少「二（二）」，省掉外部请求与耗时。

**Q3 图 3「信源分布」怎么处理**

> **问题：** 客户报告有信源分布图，要怎么处理？
>
> **证据：**
> · 客户三份报告各有一张「信源分布」图（抖音 731 / 微信公众号 1079 / 今日头条 580…），数据取自表格「来源信息」列。
> · 基座已经能画情绪分布、每日信息量、平台分布、主题分布、区县分布；客户包还可以按自己的图清单声明实例，不必先改基座的图类型表。
> · 若「信源」与已有的「平台分布」是同一口径，只需在客户包里为这张图声明实例、对齐版式图位；若口径不同、现有统计又没有按来源聚合，才需要补取数。
>
> **有哪些选择：**
> - A 本期只做现有两张图，信源分布以正文列表保留
> - B 口径能复用已有统计，在客户包里声明这张图
> - C 口径确实是新的，再补取数并出图
>
> **不同的选择会有什么影响：**
> - A 报告少一张图，不影响其它内容，不改代码，可随时补做
> - B 改动落在客户包的图清单和版式图位，不必改基座图类型表；改完要按该模板验证
> - C 要补统计或绘图能力，版式也要留图位，改完须重跑该模板验证

上述「证据」一条是四段式的**硬要求**：没有「客户的做法 vs 基座现有能力」这条差异，构建者就无法判断 A 究竟丢掉了什么、B 究竟改动了什么。

**Q4 TOP10 要不要 / 几条**

> **问题：** 这份报告做不做 TOP10、几行、按什么口径排？
>
> **证据：**
> · 历史四期文末表 1 都是 10 行，口径「负面且预警、按事件去重、按事件内条数排序」（2.2 实测）。
> · 基座支持关掉 TOP10：这次不跑榜单与梗概。但关掉只影响这一次运行，不改变提示词要不要写。
>
> **有哪些选择：** A 10 行、按历史口径（这次照跑）；B 不做 TOP10（这次不跑）；C 做但改行数或口径（要改模板里的口径）。
>
> **不同的选择会有什么影响：** A 与历史一致、不改任何文件。B 报告没有 TOP10 表。C 还要另核对排序规则，属立项级改动。

**Q5 首页热点要不要 / 几条**

> **问题：** 这个客户要不要首页「今日热点」，收几条？
>
> **证据：**
> · 首页热点独立于月报采集，条数被程序写死 30 条——改提示词无效，要改程序。
> · 历史四期月报里没有这个段落（2.4 第 5 项体例）。
>
> **有哪些选择：** A 要，按 30 条；B 要，但 20 条（须改程序）；C 不要（这一步整体不做）。
>
> **不同的选择会有什么影响：** A 采集页可用，不改任何文件；30 条是程序写死的。B 改提示词无效，必须改程序并按规则重录基线，属立项。C 采集与报告都没有该段，只需登记前提与证据。

**Q6 文风 / 章节称谓**

> **问题：** 正文文风与章节称谓沿用历史那套「一、」「（一）」的公文分析体，还是换客户另一套体例？
>
> **证据：**
> · 历史四期全是公文分析体：章节「一、」「（一）」，建议「1.」，正文无 Markdown、全角标点（2.4 第 5 项）。
> · 基座按这套体例写（文风、格式审核、模板分析三处一致）。
> · 差异只在「客户另有报告用别的体例」时出现：那时材料自相矛盾，读不出该以哪份为准。
>
> **有哪些选择：** A 沿用历史体例（三处都不改）；B 换体例（三处同步改措辞 + 模板固定文字同步改）。
>
> **不同的选择会有什么影响：** A 不改任何文件，三处提示词与版式全部沿用现状。B 要改三处提示词措辞与模板固定文字，须重建模板并重跑对比。

**Q7 季节条件预警允不允许**

> **问题：** 允许「无本地历史、仅按季节/时令机制」的风险预警吗？
>
> **证据：**
> · 基座允许「无本地历史、只按季节/时令机制」的预警，并要求声明「本月分类只作当前信号」。
> · 历史侧出现「较去年同期」这类跨期表述，但没有逐条本地案例（2.4 第 4 项）。
> · 差异：基座默认的证据强度低于「每条都有本地历史」，而客户的合规要求从材料里读不出来。
>
> **有哪些选择：** A 允许，但要求标注「案例参考/季节条件」；B 只允许有本地历史的选题（预期写不满计划条数）。
>
> **不同的选择会有什么影响：** A 与基座一致，通常只改两条提示词措辞，不改代码。B 建议段会变短、可能写不满计划条数，须人确认篇幅可接受。

### 5.5 问法纪律

- **一次最多问 4 个**；按决策分组，不要按 34 个 key 逐条刷问。
- **每个问题四段齐全**：问题 / 证据 / 有哪些选择 / 不同的选择会有什么影响（1.2）。缺一段就是不合格的问题。「我的建议」不是问题的一部分——它只能作为「有哪些选择」里的某一个出现。
- **标题不许用内部术语**：写「图 3 信源分布怎么处理」，不写「机制缺口」「代码契约」「钉住」——构建者不知道这些词指什么，也就无从判断。
- **证据必须含「客户的做法 vs 基座现有能力」这一条差异**，并指到位置（哪份报告哪一段、哪次实测输出）。**不写函数名/字段名，最多 5 行**（见 1.2 的「证据是给决策用的」）。只写「需要你定」不给可核查事实 = 不合格。
- **信息顺序固定**：问题 → 证据 → 选择 → 影响。背景归入证据、一段内说完，不写五六段散文式铺垫，不把结论藏在铺垫后面。
- **不许输出思考过程**：不写「我先分析一下」「我理解你的意思是」「接下来我将」；不解释你如何得出结论，只给结论和证据。
- **不许预告**：不写「我准备改哪几条」「稍后我会……」。用户没答完前，不动任何文件。
- **先自查再问**：每个问题发出前，按 1.2 的自查表过一遍——能读盘、能调接口、能跑 `scripts/check_package.py`、能按第十三章读文件确认的，自己查完写进「证据」；不要把「请你确认 / 你去看一下」当问题。
- **不许把事实包装成问题**：能从 `P.vocabulary` / S1~S4 / T.fields 读到的，自己读。
- **不许用「应该是」「可能」代替判断**：不确定就写「需实测」，并说明测什么。

### 5.6 回答与记录落盘

`packages/<新包>/接入记录.md` 固定六段，缺一段视为没做完：

```markdown
## 输入
（四类输入的实际路径 + 2.2/2.3/2.4/2.5 命令的原始输出）

## 缺口表
（5.2 表格逐项：✅ / 🔶 / ❓，🔶 写明依据命令）

## 问答记录
（问 / 答 / 落到哪个文件哪个字段）

## 提示词清单
（30 条必写逐条 `key | 状态 | 依据`；状态 = 改写 / 沿用基座 / 仅说明（占位））
（4 条可省：`key | 可省 | 前提 + 证据`，与 NOT_USED.md 一致）

## 自检证据
（第十章六条命令的原始输出）

## 遗留
（本次没解决、需要维护者后续决定的项）
```

问答记录怎么写（必须落到字段，不能只写「用户说可以」）：

```markdown
## 问答记录
- Q1 工作建议条数：用户选择 3~4 条。落到 `index.yaml.template_policy.recommendations.min_items=3`、`max_items=4`；同步 `writer.outlook` / `writer.outlook_field` / `historical_researcher.research`。
- Q2 历史调研：保留 `historical_researcher`，不做修改。
```

这个文件不在任何门禁扫描面内：`scripts/gate_prompt_neutral.py` 只扫 `core/prompts/base/agent/**/*.md`，提示词指纹只吃 `index.yaml` 声明的文件，`scripts/gate_core_iso.py` 只扫 `core/` 与 `app/`。放在包里不影响任何哈希。

## 六、撰写规范（产出格式）

### 6.1 每条必须带四项，缺一不可

```text
键           writer.analysis
状态         改写 / 沿用基座
正文         ……
依据         历史报告 S3 §二（一）研判正文 371 字、2 条风险链；模板字段 b40_analysis_paragraph（kind=analysis, owner=writer）；用户回答 Q1
与基座差异    字数建议 350~420 保持；删去基座中「安顺」示例，改为「本地区」；新增「段尾 1~2 句阻断」约束
```

字段说明：

- **键**：必须与 `packages/<pkg>/prompts/index.yaml` 的 `agent_prompts` 键逐字一致；文件名 = `<key>.md`。
- **状态**：`改写`（包内放同名文件并声明）、`沿用基座`（不写文件，但要在 `接入记录.md` 的提示词清单里登记 + 依据）或 `仅说明（占位）`（**只允许 3.11.2 那 4 条**，文件存在但正文是一句说明）。**不存在「不写也不登记」**。
- **正文**：写入 `packages/<pkg>/prompts/agent/<key>.md` 的最终文本；不要带「以下是提示词」之类包装。
- **依据**：必须能指到具体位置：`S1~S4` 的章节/段落/表、`T.fields` 的字段 id、`P.vocabulary` 的键、`B` 的某句、`U` 的 Qn。**依据为空的不许交付。**
- **与基座差异**：写清改了什么、为什么；没改就写「无（逐字沿用）」；不要写「优化了一下」这种不可核对的描述。

### 6.2 依据的最低标准

一条合格的依据至少满足一项：

- 历史报告：文件 + 章节/表 + 可复述的事实（如「S3 §一（一）：负面单一重点预警 272 条占 1.41%；§一（四）：负面舆情 272 条（已去重）」）。
- 模板：字段 id + `owner`/`kind`/`value_schema`/`binding` 的实际值。
- 词表/配置：`P.vocabulary.cluster_terms` 的键、`P.writer_slots` 的槽位 id、`P.data_contract` 的键。
- 代码：文件 + 函数/符号字面量 + 行为（如 `app/hotspot.py` 的常量 `ITEM_COUNT=30`）。**不写行号**——理由见 4.1 的「引用纪律」。
- 用户：Qn + 原话要点 + 落到哪个文件哪个字段。

不合格的依据：「历史报告风格如此」「一般来说」「客户应该想要」「基座默认」——这些都不是依据。

### 6.3 红线：提示词里不许出现客户特有的事实

> **提示词里不许出现客户特有的事实。**
>
> ✅ 「覆盖面文本取自 payload 注入的字段（如 `payload.fields` / `payload.evidence`），不写死数字」
> ❌ 「今年正面信息 9357 条」
>
> 客户事实（地名、类目、章节称谓、示例句）全部落 `template.json`（`vocabulary` / `writer_slots` / `data_contract`）或运行时 `payload`，由 payload 注入。
>
> 违反的后果：明年数据变了，模型照着去年的例子写——报告看着对，数字是旧的。

具体禁止写进 prompt 正文的内容：

- 具体地名（「安顺」「西秀区」「黄果树」）、具体类目名（「交通管理」「文化旅游」）、具体平台名（「移动客户端」「微信公众号」）作为**固定事实**；除非是通用示例且不绑定客户。
- 具体数字、百分比、期号、日期、事件标题、人名、企业名。
- 具体章节称谓如果只适用于这个客户（「一、涉安信息传播态势」），应进模板固定文字，不进 prompt。
- 历史报告里的原句作为「范例」整句复制；prompt 只能写「按历史报告的体例」，不能把原句当模板。

允许写进 prompt 的：

- 通用方法论（「先比较 5~8 类候选」「至少 4 类」「15~35 字」）。
- 通用约束（「不得编造」「只用给定证据」「保留归因」）。
- 对 payload/模板字段的**引用方式**（「类别取自 `payload.categories`」「数值由程序填」）。

**为什么这条比门禁更重要**：`scripts/gate_prompt_neutral.py` 只扫基座 `core/prompts/base/agent/**/*.md`，包内覆盖不会被它拦；所以「包内 prompt 可以写客户事实」在门禁上是成立的，但在维护上是错的——下一年数据变了，prompt 里的示例就是过期事实。门禁管不住的地方，靠这条纪律。

### 6.4 覆盖机制（分层查找、声明、字节口径）

- 基座 34 条在 `core/prompts/base/agent/`，键名 = 文件名（`writer.analysis` ↔ `writer.analysis.md`）。
- 包内放**同名文件**（`packages/<pkg>/prompts/agent/<key>.md`）并在 `prompts/index.yaml` 的 `agent_prompts` 里声明该相对路径，即覆盖基座；`provenance()` 显示 `package`。
- **不写 = 继承基座**（`base`）。但「不写」现在是一条**判断结论**，不是默认动作：30 条必写都要判一次并登记依据（3.3、6.5）。两个现成包的实测：`packages/anshun_monthly/prompts/agent/` 目录存在但为空（34 条全部继承基座），`packages/demo_b/prompts/agent/` 有 10 个文件（10 条全覆盖）。
- `index.yaml` 四个顶层键必须齐：`agent_prompts` / `template_policy` / `report_prompt_profiles` / `default_prompt_profile`，缺一个就 `prompt_index_missing_keys:<键>`（`core/prompts/registry.py` 的 `_INDEX_KEYS` 与 `_bundle`）。
- **没有 import 期硬依赖了（2026-11 核实，旧手册说法作废）**：`core/agent.py` 文件头明写「本模块没有 `AGENT_PROMPTS=...` 这种 import 期求值的快照」，旧名（`AGENT_PROMPTS` / `AGENT_DEFINITIONS` / `TEMPLATE_POLICY` / `REPORT_PROMPT_PROFILES`）改成了 PEP562 `__getattr__` 懒代理——首次读取才解析当前包并各发一次 `DeprecationWarning`。后果链必须背下来：缺某键 → `import app` **不报错**、`check_package` 的 LOAD 段**全绿**（demo_b 缺 24 个键实测仍 `PKG-OK`）→ 直到运行时第一次 `get_prompt('该键')` 才抛 `KeyError: 'unknown_agent_prompt:<key>'`。模板三键就是这样在第 1/2/3 轮研判才炸的（3.3）。**因此 34 键齐不齐只能逐条比对 `index.yaml` 声明集（照抄 anshun 的 34 行），不能靠「import 成功 / 自检绿了」推断。**
- 声明的键在包内和基座都没有对应文件 → `prompt_missing:<key>`（`core/prompts/registry.py` 的 `_resolve`）。
- 最简单的做法：**复制 A 包的 `index.yaml`，只改 `report_prompt_profiles` 的 profile 名与 `default_prompt_profile`**；`agent_prompts` 34 行原样保留。
- 字节口径（`core/prompts/registry.py` 的 `_text` 加载实现，`tests/test_s7_package_contract.py` 钉住）：UTF-8 **无 BOM**、`\n` 换行、正文 + **恰好一个**结尾 LF。写文件用 `write_bytes`；不要用 `write_text`（Windows 默认转 CRLF，`\r` 会进正文并改指纹）。

查找与来源（`core/prompts/registry.py` 的分层查找）：

```text
包内 <prompts>/agent/<key>.md
  → 基座 core/prompts/base/agent/<key>.md
  → PromptBundleError('prompt_missing:<key>')
```

- 两级都缺才报错；**不回落任何内置默认值**。
- `agent.prompts()` 返回 `{key: 全文}`；`agent.provenance()` 返回 `{key: 'package' | 'base'}`，顺序 = `index.yaml` 声明序。
- `provenance()` 只说明「文件从哪来」，不说明「内容是否合适」；`base` 不等于「可以不改」，`package` 不等于「改对了」。

复核覆盖面（anshun 这类 34 键包未覆盖时应当是 `34` 与 `[]`）：

```powershell
@'
from app import agent
from core.packages import load_package
pkg = load_package(None)
print(len(pkg.agent_prompts))
p = agent.provenance()
print(sorted(k for k, v in p.items() if v == 'package'))
'@ | & $py -
```

注意：`agent.AGENT_PROMPTS` 旧名还能用，但它是 PEP562 懒代理、会发 `DeprecationWarning`，新写法用 `load_package().agent_prompts`（上面已换）。这段只回答「声明的键各自从哪来」，**不回答「代码需要的键是否都声明了」**——注册表不校验条数（demo_b 只声明 10 键这里就打印 10）。键齐不齐的检查是与 anshun 的 34 行做集合比对：

```powershell
@'
import pathlib, yaml
base = yaml.safe_load(pathlib.Path('packages/anshun_monthly/prompts/index.yaml').read_text(encoding='utf-8'))['agent_prompts']
new  = yaml.safe_load(pathlib.Path('packages/<新包>/prompts/index.yaml').read_text(encoding='utf-8'))['agent_prompts']
missing = sorted(set(base) - set(new))
extra   = sorted(set(new) - set(base))
print('declared', len(new), '| missing vs anshun:', missing, '| extra:', extra)
'@ | & $py -
```

新包 `missing` 必须为 `[]`（34 键全声明；确要省的 4 条按 3.4 在 `NOT_USED.md` 登记后，再由维护者拍板是否从声明集拿掉，默认不拿）。

### 6.5 四种状态的写法

- `改写`：包内有文件 + `index.yaml` 声明 + 依据 + 与基座差异。
- `沿用基座`：包内无文件；在 `接入记录.md` 的「提示词清单」里写一行 `key | 沿用基座 | 依据`；不要为了「看起来完整」复制一份基座正文（复制会制造第二份真相）。
- `仅说明（占位）`：包内有文件，正文只有 3.11.2 那三行说明；**只允许 `historical_researcher.*` 4 条且角色未声明时使用**；在 `接入记录.md` 写 `key | 仅说明（占位）| 条件`。别把它当选省事的选项（3.11.4 的后果）。
- `可省`：包内无文件；只允许 3.3 那 4 条；在 `NOT_USED.md` 写一行前提 + 证据；不要写进 `index.yaml` 的 `agent_prompts`。

> 模板三键 `template_analyst.batch / .repair / .advice` 与 `template_analyst.template / .charts` 在任何情形下都必须声明并从基座继承——它们不是「文件可以缺席」的候选；缺键 PKG-CHECK 不拦（懒加载），第一次建模板才炸（6.4）。

### 6.6 包内目录结构

```text
packages/<pkg>/prompts/
  index.yaml          # 34 个 key 全部声明；template_policy / report_prompt_profiles / default_prompt_profile
  roles.yaml          # 角色 id → {responsibility, boundary, output}
  agent/<key>.md      # 只放「改写」的 key；其余从基座继承
  NOT_USED.md         # 仅在确要省 3.3 那 4 条时创建；登记前提 + 证据
```

## 七、`agents:` 怎么声明

`manifest.yaml` 的 `agents:` 是**能力开关**：客户包只写角色 id，角色驱动哪一步由基座决定（`core/agent_steps.py` 的 `ROLE_STEPS` / `INLINE_STEPS`）。

九个可裁角色与各自的步骤：

| 角色 id | 驱动的步骤（图:节点） | 不声明（且无人替代）时会发生什么 |
|---|---|---|
| `template_analyst` | template:`local_compare_and_analysis` | 模板比对与结构化分析整段不跑；该链在 `BYPASS=None` 的节点上结束 |
| `data_processor` | report:`data_processing` | 工具循环整段不跑（导入/筛选/属地/候选/去重/分类/聚类/选材全部不发生），前驱改接到 `await_data_review` |
| `event_judge` | report:`event_analysis` | 见下方「共用节点」说明 |
| `event_classifier` | report:`event_analysis` | 见下方「共用节点」说明 |
| `event_summarizer` | report:`event_analysis` | 见下方「共用节点」说明 |
| `writer` | writing:`write_draft` | 正文撰写整段不跑 |
| `historical_researcher` | **内联**在 writing:`write_draft` 内 | 历史调研整步不跑（不联网、不查历史），`write_draft` 其余部分照跑 |
| `format_reviewer` | writing:`format_review` + writing:`final_format_review` | 两次格式审核都不跑 |
| `content_reviewer` | writing:`content_review` | 内容审核不跑 |

规则（全部来自 `core/agent_steps.py`、`core/manifest.py`，可用 `& $py -c "import app"` 复现）：

- **不写 `agents:` = 全部启用**（9 个角色都参与），老包兼容。
- **写了 = 只跑列出的角色**；未列出角色驱动的节点整段裁掉，前驱按 `BYPASS` 改接到后继（`core/agent_steps.py` 的 `BYPASS` 与 `prune_spec`）。
- **`agents: []` 等于不写**：空列表 falsy → 仍解析成「全部启用」（`core/agent_steps.py` 的 `enabled_agents`，实测 `len(enabled_agents(空列表)) == 9`）。没有「一个角色都不跑」这种合法配置。
- **`event_judge` / `event_classifier` / `event_summarizer` 三个共用 `report:event_analysis` 一个节点**：只要声明其中之一，整段 `event_analysis` 仍会跑（裁节点看的是「这个节点有没有任一驱动角色在名单里」，`core/agent_steps.py` 的 `prune_spec`，详见 3.10）。要整段跳过必须**三个都不声明**。
- **声明里出现 `roles.yaml` 没有的角色 → 启动即失败** `manifest_unknown_agent:<id>`（`core/agent_steps.py` 的角色校验，实测 `ValueError: manifest_unknown_agent:nope`）。别指望它被静默忽略。
- **声明了 `agents:` 但 `prompts/roles.yaml` 不存在 → `manifest_agents_unverifiable:<包名>`**（`core/manifest.py` 的 `_validate_agents`）。
- 不在 `ALL_AGENTS` 里的角色（`writer_data_planner`、`hotspot_collector`）**`agents:` 开关不了**：它们不驱动可裁步骤，声明与否都不改变它们是否被调用（`core/agent_steps.py` 的 `ALL_AGENTS` 只把 9 个角色纳入调度）。

例：不要历史调研（其余 8 个全要）

```yaml
agents:
  - template_analyst
  - data_processor
  - event_judge
  - event_classifier
  - event_summarizer
  - writer
  - format_reviewer
  - content_reviewer
```

验证（就一条命令）：

```powershell
$env:REPORT_PACKAGE='<新包>'; & $py -c "import app"
```

这里的 `REPORT_PACKAGE` 只决定**进程的部署默认包**是谁（`core/packages/context.py` 的 `default_package`）——设成新包是为了让子进程去加载它（`scripts/check_package.py` 的 LOAD 段同样这么做：`env['REPORT_PACKAGE'] = c.name`）。**它不是切客户手段**；接客户靠建任务时选客户（1.5.4 ①）。

`exit 0` 且**无任何输出** = 声明合法；否则异常里带具体错误码（`manifest_unknown_agent:` / `manifest_agents_unverifiable:` / `manifest_missing_keys:` / `prompt_index_missing_keys:` …）。注意这只验证「声明的东西本身合法」（agents/roles/index 结构）：提示词键懒加载后，**少声明键不会让 `import app` 失败**（demo_b 只声明 10 键也 exit 0），34 键齐不齐要另跑 6.4 的集合比对。

## 八、答案落到哪个文件（逐项对应表）

| 答案 | 落点 | 字段 / 位置 |
|---|---|---|
| package 名 | 目录名 + `manifest.yaml` + `template.json` | `packages/<名>/`、`package`（三处同值） |
| report_type | `manifest.yaml` | `report_type` |
| 工作表序号 | `template.json` | `data_contract.sheet_index`（仅记录；实际值来自任务参数） |
| 必需列 | `template.json` | `data_contract.required_columns`（必须都在 Excel 首行） |
| 列映射 | `template.json` | `data_contract.column_map`（**键序 = records 字段序**） |
| 摘要列 | `template.json` | `data_contract.summary_columns`（`[0]` 优先、`[1]` 截 1200 字兜底） |
| 去重参数 | `template.json` | `data_contract.dedup.{threshold, candidate_floor_ratio, merge_rounds, merge_threshold}` |
| 区县清单 | `template.json` | `vocabulary.localities`：键 = canonical，值 = **参与匹配的写法**（含别名） |
| 类目词典 | `template.json` | `vocabulary.cluster_terms`：键 = 类目名（顺序 = 枚举序），值 = 词表成员 |
| writer 槽位 | `template.json` | `writer_slots`：99 个占位符里由 writer 填的业务子集（A 包 9 个）。不写则回退到「按 `slot_type` 推出的 15 个」，比业务口径宽 |
| 图表清单 | `template.json` + `manifest.yaml` | `charts[]`（`id/drawing_index/family/style/binding/unit/scope/axis_label`）+ `charts.use`（与前者同集合；id 不限于基座 5 个） |
| 步骤声明 | `manifest.yaml` | `agents:` |
| 角色定义 | `prompts/roles.yaml` | `角色 id → {responsibility, boundary, output}`（恰好三键，多一个少一个都 `prompt_role_invalid:<id>`） |
| 提示词覆盖 | `prompts/agent/<key>.md` + `prompts/index.yaml` | 同名文件 + `agent_prompts` 里声明该 key |
| 提示词取舍 | `packages/<新包>/接入记录.md` | 「提示词清单」段：`key | 改写/沿用基座/仅说明（占位）| 依据` |
| 模板策略/画像 | `prompts/index.yaml` | `template_policy`、`report_prompt_profiles`、`default_prompt_profile` |
| 工具白名单 | `manifest.yaml` | `tools.allow` / `tools.phases` / `tools.budgets`；`capabilities.require`（产物 → 反推可达工具）；`features.<能力>.enabled`（能力开关） |
| 数据槽计算绑定 | `packages/<包>/calculations.yaml` | 字段 id → 基座 `CALCULATION_CATALOG` 中的通用运算及参数。目录里没有的算法才改基座 `Calculation`，不要把客户字段写进基座。 |
| 缺口与问答 | `packages/<新包>/接入记录.md` | 见 5.6 |
| 测试结论 | `packages/<新包>/对比报告-<期号>-<日期>.md` | 见 9.2 |

注意两处容易白写的地方：

- `column_map` 里不要把摘要列映射成 `summary`：`core/tools/records.py` 的 `import_records` 会用 `summary_columns` 的结果覆盖它。
- `features` 的判定是 `config.get("enabled") is False` 才扣工具（`core/tools/registry.py` 的 `resolve_tools`），写错键名不会生效。

## 九、测试与对比

### 9.1 跑几次、用哪份数据

- **跑 2~3 次**，同一份输入、同一套提示词、同一模板；记录 run id / 时间 / 模型 / 参数。
- **数据选择**：
  - 要对比数字，用**与历史报告同月**的数据（例如 8 月数据 + 8 月报告）；否则数字不可比。
  - 只有新月份数据时，只对比结构、字数、句式、体例、TOP10 形态；**不要**拿新月份数字去对旧报告数字。
- 每次跑完保留：最终 docx、writer 字段值、审核 issue、TOP10、图表数据；对比报告引用这些产物，不引用对话记忆。

### 9.2 对比报告长什么样

文件建议 `packages/<pkg>/对比报告-<期号>-<日期>.md`。结构：

```markdown
# 对比报告：<客户> <期号>

## 0. 运行信息
- 数据：<xlsx 路径>，sheet=<n>
- 模板：<template_version ref / 文件>
- 提示词：必写 30 条 → 改写 <n> / 沿用基座 <n> / 仅说明（占位）<n>；可省 <n> 条（见 `NOT_USED.md`）
- 运行：run-1 / run-2（模型、时间、参数）

## 1. 结构对比
| 章节 | 历史报告 | 本次生成 | 判定 |
|---|---|---|---|
| 一（一）总体 | 有 | 有 | 一致 |
| 二（二）工作建议 | 4 条 | 3 条 | 缺失 1 条 |

## 2. 数字对比（同月数据才做）
| 指标 | 历史报告 | 本次生成 | 差异 | 疑似原因 |
|---|---:|---:|---:|---|
| 负面条数 | 1863 | 1851 | -12（相对 0.64%） | 口径/去重差异 |
| 负面占比 | 9.69% | 9.62% | -0.07 个百分点 | 分母不同 |

## 3. 段落/句子差异
- 缺失段落：...
- 多出段落：...
- 句式差异：...
- 固定文字被改写：...

## 4. TOP10 对比
| 排名 | 历史事件 | 本次事件 | 判定 |
|---|---|---|---|

## 5. 结论（给人）
- 必须改：...
- 建议改：...
- 可以不改：...
```

**具体样例**（数字为示例，不是真实生成结果；历史数字取自 S3 8 月报告）：

```text
第一部分（四）「从负面舆情看」
  历史报告：负面 1863 条，占 9.69%（S3 §一（一））；负面重点预警 272 条（已去重），文化旅游类占 17.65%（S3 §一（四））
  本次生成：负面 1851 条，占 9.62%
            条数差 12 条（相对 0.64%），占比差 0.07 个百分点；疑似口径/去重不同
  缺失段落：第 3 段少了「（已去重）」说明
  建议改：模板固定文字里补回「（已去重）」；若这句话落在动态字段内，则改写作口径
  备注：任务示例里的 b5_amber 是模板字段 id，不是提示词 key；不要照抄成 prompt 名
```

注意：不要写「差 0.66%」这种把「条数相对差」和「占比百分点差」混在一起的数。要么写「条数差 12 条（相对 0.64%）」，要么写「占比差 0.07 个百分点」。

**「5. 结论」是给人看的**：只写「哪一段少了什么、该改哪个地方的功能」，
不写提示词 key 名、字段名或文件路径——那些留在「0. 运行信息」与 `接入记录.md`（1.2 的第一条规矩）。

### 9.3 谁判断好坏

- **人判断**：结构对不对、措辞像不像、取舍接不接受。
- **agent 只负责产出对比**：不给自己打「PASS」，不替人决定「这条可以不改」；可以给「建议」，但结论栏写「待人工确认」。
- 对比报告要能让一个没参加生成的人看懂：每个差异都有位置、有数字、有疑似原因、有建议动作。

### 9.4 失败处理

- 同一条提示词连续 2 次产出同类问题：停，回到第四章重新判断，不要继续微调。
- 数字差异 > 1% 或结构缺段：先查口径/模板/字段，不要先改 prompt。
- 运行报 `prompt_missing` / `unknown_agent_prompt` / `prompt_index_missing_keys`：按第十二章修，不要绕过。
- 提示词改到第 3 版仍不对：把「证据不足」写进对比报告，交人决定，不要编。

## 十、建完自检（六条，逐条可执行）

执行前阅读 [基座兼容说明](references/base-compatibility.md)，核实实例数据根、隔离检查与当前历史门禁边界。

六条全绿、原始输出贴进 `接入记录.md`，才算建完。**建包之后先跑 10.2 的包归属四条**（新包可用、任务绑对包、产物落对根），再回来跑这六条。

**1. 基座提示词是否仍然客户无关**

```powershell
& $py scripts\gate_prompt_neutral.py
```

期望：`RESULT: PASS`，首行形如 `G-PROMPT-NEUTRAL  (34 files scanned, 40 terms: 5 static + 20 localities + 15 labels)`（2026-11-17 实跑：龙川包入列后为 40；早期两包时是 37）。括号里是 `5 + 地名去重数 + 类目名去重数`，**数字随在册包变大，以实跑首行为准**，不要把任何一次的数字当常量。新包加进去后这个数字通常**变大**（你的地名/类目名进词表了）；判据始终是 `RESULT: PASS`。

若新包的类目名/地名与基座提示词撞车，这里**会** FAIL——那是正确行为。处理是改基座提示词的措辞、或与维护者确认类目名，**不允许**给门禁加豁免（口径里没有豁免机制）。

**2. 包级契约检查（七段机械判定）**

```powershell
& $py scripts\check_package.py --package <新包名>
```

三段输出各看什么：

- 首行 `PKG-CHECK <新包名>` 之后是七段逐段判定：`FILES`（四个文件在不在）/ `MANIFEST`（必需键、features 键与阶段键、能力与图表名、agents 形态）/ `TEMPLATE`（template.json 顶层键与 data_contract、cluster_terms）/ `PROMPTS`（index.yaml 每个键能否在包内 `prompts/` 或基座 `core/prompts/base/` 找到）/ `ROLES`（roles.yaml 角色字段集）/ `AGENTS`（`manifest.agents` 是否都在 roles.yaml 里）/ `LOAD`（子进程 `import app` 真能加载）。每段是 `ok`（括号里给摘要）、`skip`（前置文件缺失，见对应段提示）或 `FAIL`。
- 末行要么 `PKG-OK <新包名>`，要么 `PKG-FAIL <新包名>  (N errors)`。
- 退出码：`0` = 全绿；`1` = 有 PKG-FAIL（含包目录不存在、基座常量读不到）。

失败项在对应段下逐条以 `- ` 给判据与定位句子（例：`- 缺少必需键: package`、`- features.dedup.enable 不是合法键（少一个 d，应为 enabled）`、`- agents 声明了 roles.yaml 没有的角色: ghost_role`），照句改包即可。七段判据用到的常量全部从基座源码 ast 读（`core/ports.py` / `core/prompts/registry.py` / `core/tools/registry.py` / `core/charts/spec.py`），没有第二份副本可漂移。

**3. 包能被加载**

```powershell
$env:REPORT_PACKAGE='<新包>'; & $py -c "import app"
```

（同第七章验证：这里 `REPORT_PACKAGE` 只当「让子进程加载哪个包」用，不是切客户。）

期望：`exit 0` 且**无输出**。这一步绑定启动上下文与四个注册表，包文件和提示词按需加载；仅导入可能尚未读到坏配置。提示词键也已懒加载——**少声明键这里照样 exit 0**（6.4），键齐不齐看第 6 条与 6.4 的集合比对，别把这条当成「34 键齐」的证据。

**4. 加包前后 `core/` 与 `app/` 逐字符不变**

```powershell
& $py -c "import sys;sys.path.insert(0,'scripts');import gate_core_iso as g;o=g.observe(g.REPO/'core',g.REPO/'app');print('CORE-FILES',o['core_files']);print('CORE-DEP',o['core_dep']['sites'],'sites /',o['core_dep']['files'],'files');print('CORE-HASH',o['core_hash']);print('APP-HASH',o['app_hash'])"
```

加包前跑一次、加包后再跑一次，**四行逐字符相同**。这条不依赖任何基线文件，只做纯观测（`scripts/gate_core_iso.py` 的 `observe`）。包在 `packages/` 下，纯建包不应改 `core/` 与 `app/`。比较起点必须是**当前优化完成后的基座**，不是优化前的历史哈希；差异先辨明来源，不自动覆盖现有修改或重录基线。

**5. 最小冒烟（包契约三连）**

```powershell
& $py scripts\run_scoped_checks.py tests/test_s7_package_contract.py
```

期望 `3 passed`。这三条用例遍历 `packages/*/`（不是手写清单），新包自动进入判据：①子进程 `import app` 能加载 ②提示词提到的已注册技能都已在 `manifest.skills.use` 声明 ③提示词文件字节口径（至多一个结尾 LF）。输出恒为 `3 passed`——每个用例内部对**所有**包逐个断言。

需要覆盖本批优化时，按 [基座兼容说明](references/base-compatibility.md) 执行显式定向回归。不要直接运行全量 pytest：历史用例可能访问本机业务数据或模型。隔离启动器使用仓库外临时数据、清空凭据并限制网络/写入（Python 审计防误用，不是操作系统沙箱），**不能代替真实客户出稿验收**。记录实际节点、退出码及日志位置；不得把历史结果或多个重叠批次相加当作当前通过数。

**6. 覆盖可见性（改写的 key 才是 `package`）**

```powershell
@'
from core.packages import load_package
from app import agent
print(len(load_package(None).agent_prompts))
print(sorted(k for k, v in agent.provenance().items() if v == 'package'))
'@ | & $py -
```

期望：34 键声明集的包第一行 `34`；第二行恰好是「改写」的 key 集合，不多不少。没改写任何一条时第二行是 `[]`。注意 `provenance()` 只说明来源，不说明内容是否合适（6.4）；第一行也不证明键齐——它只是声明条数，键齐要靠 6.4 的集合比对（懒加载下少声明照样全绿）。

### 10.1 门禁边界（改哪里会动哪个基线）

| 动作 | `docs/team/baseline/prompts-S5.json` | `docs/team/baseline/core-S10-*.json` | `gate_prompt_neutral` |
|---|---|---|---|
| 只写 `.conda/docs/` | 不动 | 不动 | 不动 |
| 改本手册 `.dsh/skills/onboard-client-package/SKILL.md`（旧位置 `core/prompts/base/接入新客户.md` 已删除） | **不动**（不在 `agent_prompts` 里） | **不动**（不在 `core/` 或 `app/` 下） | 不动（不扫 `base/*.md`） |
| 修改提示词 | 默认包解析到的正文变化才影响 S5；非默认客户覆盖不等于 S5 基线变动，禁止自动重录 | 改 core/app 内文件才影响其树哈希 | 基座改动会扫；包内覆盖不扫 |

三条依据：

- `scripts/gate_prompts.py` 不哈希文件，哈希的是四个数据对象：`BASELINE`（`prompts-S5.json`）与 `BUNDLE_KEYS = ("AGENT_PROMPTS", "AGENT_DEFINITIONS", "TEMPLATE_POLICY", "REPORT_PROMPT_PROFILES")`，由同一文件的 `bundle()` 组装。`AGENT_PROMPTS` 来自 `core/agent.py` 的 `_registry.prompts()`，只遍历 `index.yaml` 的 `agent_prompts`。改部署默认包（`REPORT_PACKAGE`）会改变 `AGENT_PROMPTS`，所以 `prompts-S5.json` 只对默认包 `anshun_monthly` 有意义，不能给新客户当基线。
- `scripts/gate_prompt_neutral.py` 的扫描面是 `core/prompts/base/agent/**/*.md`（34 条提示词正文），docstring 明写不扫 `core/prompts/base/*.md`：那些是对照表（接入说明已移出 core，见本手册）。
- `scripts/gate_core_iso.py` 的 `observe()` 用 `tree_hash(core_root, "*")` 把 `core/` 下所有文件（含 `.md`）算进 `CORE-HASH`。本手册原来就放在 `core/prompts/base/` 下，移出到 `.dsh/skills/` 后 `CORE-FILES` 少一个、`CORE-HASH` 必变，`--baseline docs/team/baseline/core-S10-J.json` 会 FAIL；那是预期行为，按团队当前的 core 基线规则处理，**不要随手录基线**。

**当前历史例外（2026-11-18 核查）**：`tests/test_s5_prompt_gate.py::test_prompts_match_baseline` 和 `::test_gate_rejects_corrupted_bundle` 已有基线不匹配；详见仓库 `docs/verification/2026-11-18-optimization/remaining-report.md`。新客户接入不得重录 `prompts-S5.json`、删断言、skip/xfail 消红。将既有问题与本次新增失败分开记录，不能宣称全套门禁通过；独立损坏探针通过也不等于旧 S5 基线匹配。未来是否已修复须以当时源码与实跑为准。

### 10.2 包归属自检（建包之后、写提示词之前跑）

**这四条全部由 agent 自己跑、自己看输出**，不让用户去开页面或翻接口；看不到证据就别往下写提示词，把缺口写进 `接入记录.md` 的「自检证据」段再报告维护者。

**1. 新包有没有被系统识别**

```powershell
$item = (Invoke-RestMethod http://127.0.0.1:8765/api/packages) | Where-Object { $_.package -eq '<新包>' }
$item | Format-List package,usable,error
```

- **看什么**：`package  : <新包>`、`usable   : True`、`error    :`（空）。
- **算成功**：三行如上；把这段原始输出贴进证据段。
- **不对劲**：什么都打不出来 → 注册表没认出这个包，跑 `& $py scripts\check_package.py --package <新包>` 看 FILES / MANIFEST 段；`usable : False` → `error` 那行就是原因（多半是 manifest / template / 提示词某一环坏了），按 error 修完重跑本节。

**2. 任务绑的是不是新包**（用户在 1.5.4 ① 建完模板任务后跑）

```powershell
# $taskId 来自本次创建响应/页面任务地址；禁止按全局时间排序挑任务
$pkg = '<新包>'
$taskId = '<本次模板任务ID>'
$task = Invoke-RestMethod "http://127.0.0.1:8765/api/tasks/$taskId" -Headers @{ 'X-Report-Package' = $pkg }
if ($task.package -ne $pkg -or $task.kind -ne 'template') { throw '任务归属或类型不匹配' }
$task | Select-Object id,kind,package
```

- **看什么**：输出形如 `package` / `-------` / `<新包>`。
- **算成功**：值 = `<新包>`，不是部署默认包。
- **不对劲**：值不是 `<新包>`（最常见：建任务时没带 `X-Report-Package`，落到默认包）→ 废弃这个任务，按 1.5.4 ① 重新选客户建，别在错包上继续。

**3. 产物落在哪个根**：按运行实例的实际数据基根解析 `<基根>/packages/<新包>/`，核对本次上传响应 file_id 和本次 task_id 引用的工件；默认包兼容旧根时按 `resolve_data_root` 判定。不能只检查仓库 data、空目录或同名旧文件；任务/工件归属以创建响应和目标包本地库为准。

**4. 请求与任务归属**：建任务/上传请求显式携带 `X-Report-Package`，请求体若含 package 必须一致；不一致会被拒绝，不应产生任务/工件。未带包信息可能按默认包处理。发现落错包时停止沿用该任务，记录本次确切 ID 后在目标包重建；不能凭默认包「刚多文件」推断归属，更不能自动清理他包文件或任务。删除仍遵守人工确认流程。

四条都看到证据之后才写提示词；任何一条不对劲，先按各自的「不对劲」修，**不要把这一步转成用户作业**。

**真要把这里的结论讲给用户时只讲现象**：说「系统还不认这个新包」「数据落到了另一个客户名下」，不报请求头名、字段名或接口名（1.2 的第一条规矩）。

## 十一、交接与定稿

### 11.1 人工改什么

人做的是判断，不是查证——查证已在 9.2 的对比报告里做完。请人只看这一份：

- **去哪**：打开 `packages/<包>/对比报告-<期号>-<日期>.md`（agent 写好并附了原始命令输出）。
- **看什么**：「1. 结构对比」的「判定」列（一致 / 缺失 1 条）、「2. 数字对比」的差异列、「5. 结论」的必须改 / 建议改 / 可以不改三行。
- **算成功**：人明确回答「这版可以」或指出「第几段哪条必须改」；签字只认这个。
- **不对劲**：报告缺「结构 / 数字 / 段落 / TOP10」任一段，或结论只写「待人工确认」→ 退回 9.4 重跑，不要让人对着半份报告猜。

人改的三件事：

- **措辞**：像不像客户/公文、判断强度、归因方式、称谓。
- **结构**：章节要不要、段落顺序、建议条数、TOP10 要不要。
- **取舍**：哪些差异可以接受、哪些必须改、哪些是本轮不修的已知问题。
- **定稿签字**：只有人能宣布「这版可以」。

agent 不改人已经确认的模板字段、固定文字、TOP10 梗概；需要改这些时，写进对比报告的「必须改/建议改」，由人决定。

### 11.2 定稿检查清单

- [ ] 需求集清单齐全：30 条必写全部有归属（改写 / 沿用基座 / 仅说明（占位）），4 条可省全部登记或全要。
- [ ] `NOT_USED.md` 存在（或确认不需要）；每条可省都有前提 + 证据；**里面没有 4 条之外的 key**；模板三键 `batch/repair/advice` 绝不在内。
- [ ] `index.yaml` 与 anshun 的 34 行做过集合比对（6.4 命令），`missing` 为 `[]`——不靠「PKG-OK / import 成功」推断键齐（懒加载不拦缺键）。
- [ ] 每条「必写」都有：键 / 状态 / 正文 / 依据 / 与基座差异；依据不为空。
- [ ] 每条「沿用基座」都有一句依据；没有为了凑数复制基座正文。
- [ ] 「仅说明（占位）」只出现在 `historical_researcher.*` 的未声明角色场景，没有扩散到 `writer.*` 或其它键。
- [ ] prompt 正文没有客户特有事实（地名、类目、数字、期号、日期、事件标题、示例原句）。
- [ ] 字节口径：UTF-8 无 BOM、`\n`、正文 + 恰好一个结尾 LF。
- [ ] `index.yaml` 的 `agent_prompts` 覆盖 34 个 key（模板三键 `batch/repair/advice` 在内；旧「五个 import 期硬依赖」说法已作废，见 6.4）。
- [ ] `provenance()` 显示：改写的 key 为 `package`，其余为 `base`。
- [ ] 2~3 次运行完成；对比报告有结构/数字/段落/TOP10 四段；结论待人工确认。
- [ ] 人工已签字；已知问题写进「遗留」。

### 11.3 定稿校验（命令原样重跑）

在仓库根目录、用项目解释器：

```powershell
cd D:\智能分析报告重构版V5
$env:PYTHONIOENCODING = 'utf-8'
$py = 'D:\智能分析报告重构版V5\.conda\JJDreport\python.exe'

# 1 包级契约（七段；PROMPTS 段显示 n keys: base + overrides）
& $py scripts\check_package.py --package <pkg>

# 2 包能被加载（exit 0 且无输出；REPORT_PACKAGE 只指定「加载哪个包」，不是切客户）
$env:REPORT_PACKAGE='<pkg>'; & $py -c "import app"

# 3 覆盖可见性：改写的 key 应该是 package，其余 base
@'
from core.packages import load_package
from app import agent
print(len(load_package(None).agent_prompts))
print(sorted(k for k, v in agent.provenance().items() if v == 'package'))
'@ | & $py -

# 4 基座提示词仍然客户无关（只扫 base/agent，不扫包内）
& $py scripts\gate_prompt_neutral.py

# 5 包契约三连（遍历 packages/*/）
& $py scripts\run_scoped_checks.py tests/test_s7_package_contract.py
```

判据：

- 1 的 `PROMPTS` 段是 `34 keys: N base + M overrides`，`M` 等于你改写的条数；末行 `PKG-OK`。
- 2 `exit 0` 且无输出。`PKG-OK` 与 `import app` 都**不证明 34 键齐**（懒加载，6.4），键齐另跑 6.4 的集合比对。
- 3 第一行 `34`；第二行是改写 key 的集合，不多不少。
- 4 `RESULT: PASS`；括号里的词数会随包增加，判据是 PASS。
- 5 `3 passed`。

## 十二、常见错误清单

| 现象 | 原因 | 修法 |
|---|---|---|
| 以为关了属地/分类/去重，模型仍能调对应工具 | `features` 开关写成 `enable: false`。判定是 `config.get("enabled") is False`（`core/tools/registry.py` 的 `resolve_tools`），键名写错 = 不生效，**不报错** | 统一写 `enabled:` |
| `prompt_index_missing_keys:template_policy`（或 `agent_prompts` / `report_prompt_profiles` / `default_prompt_profile`） | `index.yaml` 缺四个顶层键之一（`core/prompts/registry.py` 的 `_INDEX_KEYS`）。注意这是**顶层键**错，不是某条提示词缺项 | 补顶层键；`template_policy` 可以写 `{}`（demo_b 如此） |
| `prompt_missing:<key>` | `index.yaml` 声明了该 key，但包内与基座都没有对应 `.md`（`core/prompts/registry.py` 的 `_resolve`） | 补文件，或从 `agent_prompts` 删掉该行（后者仅当没有代码调用它） |
| `KeyError: 'unknown_agent_prompt:<key>'`（常出现在第 1/2/3 轮模板研判，键是 `template_analyst.batch/.repair/.advice`） | 代码要用的键没在 `agent_prompts` 里声明；提示词已是懒加载（`core/agent.py` PEP562），`import app` 与 PKG-CHECK 都不拦，缺键只在第一次取用时炸 | 照 anshun 的 34 行声明补齐（6.4 集合比对命令）；别再按「import 期硬依赖」排查，直接找该键的 `get_prompt` 调用点（三轮映射见 `app/template_execution.py` 的 `ROUND_INSTRUCTION_KEY`） |
| `manifest_unknown_agent:<id>` | `agents:` 里写了 `roles.yaml` 没有的角色（`core/agent_steps.py` 的角色校验） | 在 `roles.yaml` 补该角色，或从 `agents:` 删掉。不要指望静默忽略 |
| `manifest_agents_unverifiable:<包名>` | 写了 `agents:` 但 `prompts/roles.yaml` 不存在（`core/manifest.py` 的 `_validate_agents`） | 建 `roles.yaml` |
| 事件分类整列空、事件全落人工确认，且**没有任何报错** | 词表与类目名不匹配 → 词典全 0 命中 → `dictionary_no_hit`（`core/classify/dictionary.py` 的 `DictionaryStage`） | 用数据里真实出现的说法做词表成员；跑一次分类看命中率 |
| 属地命中 0、属地表空 | `localities` 的写法与数据写法不一致。匹配发生在**别名列表**上（`any(w in text for w in ws)`），要求恰好命中 1 个（`core/tools/locality.py` 的 `resolve_locality`）。实测数据同一辖区有多种写法（`西秀区` / `安顺市西秀区`），只写一种就会漏 | 把数据里出现的写法都放进该区县的别名列表 |
| `manifest_missing_keys:<键>` | `manifest.yaml` 缺 `package`/`report_type`/`version`/`template`/`prompts` 之一（`core/ports.py` 的 `REQUIRED_MANIFEST_KEYS`） | 补齐五个 |
| `prompt_role_invalid:<角色>` | `roles.yaml` 的角色不是恰好 `{responsibility, boundary, output}` 三键、或值不是字符串（`core/prompts/registry.py` 的 `_ROLE_FIELDS`） | 每角色恰好三键，值全部写成字符串 |
| 提示词指纹漂移、正文里混入 `\r` | 用 `write_text` 写文件，Windows 默认 CRLF；注册表按字节读、不做换行翻译（`core/prompts/registry.py` 的 `_text`） | 一律 `write_bytes` + `\n`，正文 + 恰好一个结尾 LF，UTF-8 无 BOM |
| 报告某段**缺失或质量塌陷，且不报错** | 把**会调用**的 key 写成了「仅说明」空壳（3.11.3、3.11.4）。比 `prompt_missing` 难查：运行时只看到「有文件、有内容」 | 按正文标准重写；「仅说明」只允许 `historical_researcher.*` 4 条且角色未声明 |
| 报告里出现去年的数字/事件 | prompt 正文写了客户特有事实（地名、类目、数字、期号、示例原句），违反 6.3 | 把客户事实挪进 `template.json` / payload；prompt 只留通用方法论与引用方式 |
| 承诺「legacy 槽位写作可用」后验收失败 | `writer.slot.*` 对应的 legacy 路径当前跑不通（`app/reviewers.py` 的 `begin_run` 传哨兵给 `core/storage.py` 的 `get_artifact` → `KeyError`） | 交付物与汇报里一律不承诺 legacy 路径；按 3.9 注处理 |
| 以「这次模板关了 TOP10」为由不写 `event_judge.top10` | 模板级 `top10=false` 只决定这一次跑不跑，不决定文件要不要存在（3.2、3.6.2） | 照写，可从基座继承；不登记成可省 |
| `charts.use 未注册: <id>`，或「模板有但 use 未列」 | `manifest.charts.use` 与 `template.json` 的 `charts[].id` 不是同一集合；或仍按「只能写基座 5 个 id」去写 `use` | 两边改成同一批 id；客户自有图 id 直接写入 `use`，不必先改 `ChartStyles` |
| 写作阶段一读到客户自有图 id 就校验失败，界面只有笼统的「写作未完成」 | 工作台进程还是改代码之前启动的，仍按旧的样式表校验 | 重启工作台后再跑写作 |

## 十三、图表与工具：只读这几个文件（防通读全库）

> 建包时最贵的一类浪费：为了回答「客户能不能多一张信源分布图」「这个工具该改哪里」，把 `app/`、`core/` 通读一遍。落点已经列全——按下面的表和清单读，**不要超过这个范围**。
>
> 本章给的是**路径与判据**。要不要这个问题、怎么问，见 5.4 Q3（那个范例就是按本章事实写的）。

### 13.1 图表：只读这些文件

| 文件 | 干什么的 |
|---|---|
| `core/charts/spec.py` | 图族、样式、实例投影与原图提取。基座内建 5 个图族（`sentiment / daily / platform / theme / locality`）的样式仍由 `ChartStyles` 校验；客户包在 `template.json` 或已确认模板里声明的其它 id，由 `styles_for` 按图族允许的样式校验，**不必**给 `ChartStyles` 加字段。 |
| `core/charts/registry.py` | 读某个客户包 `template.json` 的 `charts` 实例，提供 `charts()` / `ids()` / `chart()` |
| `core/charts/renderers/matplotlib.py` | 真正画图：`chart_payload` 按实例的 `family` / `scope` / `binding` 取数，按 `style` 画（pie/line/bar/barh）；工具入口是 `plot_frozen_chart` |
| `core/charts/renderers/pillow.py` | 另一个渲染后端：工具入口 `render_chart(args, ctx)`，自己从 metrics / 聚类 / 属地工件取数后直绘（**不是** `chart_payload` 的同构签名，别按同签名找它） |
| `packages/<包>/template.json` 的 `charts` 段 | 声明本包有哪些图（`id` / `drawing_index` / `family` / `style` / `scope` / `unit` / 标题 `title`·`draft_title`·`final_title` / `binding`）。运行期出图以这里以及已确认模板里的同结构为准。 |

#### 13.1.1 客户要多一张图时怎么做

先判断这张图能不能复用已有图族和取数口，再决定只改客户包还是要动基座。

```
① 在 packages/<包>/template.json 的 charts 增加一条实例
   （id、标题、style、unit、scope、binding；用 drawing_index 从 1 起对齐版式图位）
② 把 manifest.yaml 的 charts.use 写成与 charts[].id 同一集合
③ 版式 docx 里要有对应图位
④ 取数能落到已有的 metrics.* / theme_clusters.* / locality.* 时，渲染器不用改
⑤ 现有统计给不出这张图的数据时，才补 calculate_metrics 或渲染器取数
```

说明：

- **不要为了多一个实例 id 去改 `ChartStyles`。** 那 5 个字段是基座内建图族的样式校验，不是客户图清单的封闭白名单。
- id 与某图族同名，或使用「图族名 + 下划线 + 后缀」这种命名时，会继承该族的允许样式和默认取数口，便于同一图族出多张图（例如不同统计范围各一张）。不要把某个客户的 id 写进本手册当固定范例名。
- `scope` 写这张图的统计范围，须是冻结事实已支持的口径（当前为 `all_records` / `confirmed_events` / `warning_events` / `negative_warning_events`）。
- 模板已声明 `charts` 时，以声明为准，不再按基座默认图清单或版式图片数去截断实例。
- 基座内建 5 个图族的默认取数口是 `metrics.sentiment` / `metrics.daily_count` / `metrics.platform` / `theme_clusters.groups` / `locality.items`。`calculate_metrics` 现产 `record_count / sentiment / platform / warning_raw_count / daily_count / peak_day`（外加可选的 `negative_count` / `confirmed_event_*` / `ratio`）。没有的口径要补指标，不是补 `ChartStyles` 字段。
- `render_chart` 的入参 schema 里 `chart_type` 仍可能写着内建 id 的描述串（`core/tools/registry.py` 的 `BASE_ARGUMENTS['render_chart']`）。这只是给模型看的说明，**不改不报错**，别把它当成门禁；真正出图走的是 `plot_frozen_chart`。
- 改了出图相关的基座代码后，必须重启工作台进程再验证；旧进程不会加载新逻辑。

#### 13.1.2 必须写明的限制：`.doc` 不能从原文取图

`.doc` 格式的历史报告**无法从原文提取图片** —— `spec.py` 的 `source_image()` 对 `.doc` 直接抛 `ValueError('source_chart_unavailable')`（OLE2 里的图是 EMF 对象，不是 ZIP 内的 media 条目）。所以「从原文取一张信源图来预览」这条路对 `.doc` 客户**走不通**，只能程序画。

**判断依据**：`core/tools/doc97.py` 的 `is_legacy_doc(path)`。实测（2026-11-17）：

```
& $py -c "import sys;sys.path.insert(0,'.');from core.tools.doc97 import is_legacy_doc;from pathlib import Path;print(is_legacy_doc(Path(r'C:\Users\knwl\Desktop\国内研究室报告\月报\龙川月报\龙川县10月舆情月报.doc')))"
→ True
```

同一个 `.doc` 判断还管版式面：`layout_available()` 对 `.doc` 返回 `False`，`_drawings()` 直接返回 `[]`（不抛 `BadZipFile`）。后果是：**`.doc` 客户的图形数恒为 0**，靠版式推不出任何图，图只能由 `template.json` 的 `charts` 实例定义——所以 13.1.1 第 ① 步对 `.doc` 客户不是「顺手加」，而是唯一来源。

### 13.2 运行时工具：只有这 3 个位置相关

运行时工具是写作/数据处理时模型可以调用的函数（导入、统计、解析等），
和下面 13.2.2 的「数据槽计算绑定」不是同一件事。

| 文件 | 干什么的 |
|---|---|
| `core/tools/registry.py` | 三处：`BASE_ARGUMENTS`（基座侧工具的**入参 schema**）、`FEATURE_TOOLS`（哪个能力开关会裁掉哪些工具）、`resolve_tools()`（把 manifest 的 `tools.allow` / `capabilities.require` 解析成工具白名单） |
| `core/tools/<具体>.py` | 工具实现：`records.py`（导入/筛选/取字段）、`dedup.py`（事件归组）、`events.py`（事件候选）、`locality.py`（属地）、`metrics.py`（统计）、`documents.py`（报告解析） |
| `core/tool_executor.py` | 调度：按工具名找 handler、做策略与预算校验，子进程里跑（`_bounded_run`） |

#### 13.2.1 三种常见诉求，各自改哪里

```
① 客户要用一个基座已有的工具
   → 只改 packages/<包>/manifest.yaml 的 tools.allow（或 capabilities.require），**不改代码**
② 客户要一个基座没有的工具
   → core/tools/<新文件>.py 写实现 + core/tools/registry.py 的 BASE_ARGUMENTS 加入参 schema
③ 某个能力开关要连带裁掉某些工具
   → core/tools/registry.py 的 FEATURE_TOOLS
```

② 之后还有一步不能漏：在 `manifest.yaml` 的 `tools.allow` 里放行（或经 `capabilities.require` 让它可达）。白名单同时是门禁——没进白名单的工具，模型调了只会拿到 `tool_not_allowed`。

#### 13.2.2 数据槽计算绑定：客户包绑定，基座只加通用能力

模板确认和写作取数用的是另一套「计算工具箱」，不是 13.2 里那些运行时函数。
模型在确认阶段只能从 `available_bindings` 里挑选绑定；写作阶段的规划器对照同一套计算目录补尚未绑定的数据槽。

| 文件 | 干什么的 |
|---|---|
| `core/frozen_report.py` 的 `Calculation` / `CALCULATION_CATALOG` | 基座通用运算目录（条数、比例、峰值日期、平台集合计数、来源明细、周期起止、记录表等）。新算法若可复用，写在这里，名称和参数必须泛化，禁止出现某个客户或某张报告的字段 id、地名、渠道专名。 |
| `core/field_calculations.py` | 读取包内绑定：`calculations.yaml`，以及 `template.json` / manifest 里的 `field_calculations`。后写覆盖先写。 |
| `packages/<包>/calculations.yaml` | 本客户字段 id → 目录中已有运算，含该客户的平台集合、调性、范围、日期格式等参数。只属于客户包，不要写进基座 `KNOWN` 或目录。 |
| `app/template_review.py` 的 `available_bindings()` | 确认阶段模型可选项：旧的 `{tool, path}`、计算目录全部 metric，以及当前包 `calculations.yaml` 里按字段给出的建议绑定。 |

**建包时的分工（必须按这个顺序做）：**

1. 先读占位符的 `semantic` / `rule` / `format`，对着 `CALCULATION_CATALOG` 找已有口径。能绑上就只改客户包的 `calculations.yaml`（或确认模板里的 `binding`），**不要新加工具**。
2. 只有目录确实表达不了这种算法时，才向基座增加一条通用 `Calculation` metric，并同时把它纳入确认阶段工具箱（目录一经扩展，`available_bindings()` 会自动带上）。先说明缺口、复用方案和对已有报告的影响，确认后再改基座。
3. 不要在客户包里实现一套不能复用的私有运算，也不要把客户字段 id、渠道专名或报告标题写进基座目录。
4. 已确认模板上 `binding: null` 的数据槽，包内 `calculations.yaml` 在写作时仍可补上，不必为了补绑定而重做模板确认；新确认的模板则应直接绑到目录或包建议口径。
5. `peak_date` 默认按全量记录的信息峰值取日；若字段语义是某一类事件的高峰（例如已预警且负面），必须在 `calculations.yaml` 或确认绑定里写明 `scope` / `sentiment`，不能只写 `metric: peak_date`。未写范围时不要假设引擎会按图表口径自动收窄。
6. 删掉客户包再按本 skill 重建，只能重新落包内配置（图表声明、`calculations.yaml`、提示词覆盖、模板确认）。它不会自动修好当时还在基座里的缺陷。基座已修好的能力（高峰口径、段内衔接句、预览嵌图、审核轮次、确认工具箱等）会在下一次「确认模板」和「写作」时生效；删除会丢掉已确认模板和当期报告，需要用户明确同意。

### 13.3 硬规矩

**查图表/工具能力时只读上面列出的文件。**
不要去通读 `app/`、`core/` 的其它文件找答案 —— 路径已经给全，
通读整个仓库既慢又容易把别的模块的假设套到当前客户身上。

**本章的表、路径与命令是 agent 自己的查法，不是交给用户的作业。**
「客户能不能多一张图」「这个工具该改哪里」「某个字段在哪定义」都由 agent 按上面的清单读完后，用结论 + 证据回答；不要把路径、命令或文件列表转给用户让他自己看（1.2 的自查表）。先判断客户包声明是否够用；只有取数口不存在、需要改基座时，才把「要不要为这张图改代码」问给客户。

### 13.4 重建客户包能解决什么、不能解决什么

本 skill 指导的是**正确建包**，不是把基座漏洞一并抹掉。遇到过的问题要按层判断：

- **会随重建/重新确认模板而生效**（前提是基座已具备该能力，且包配置写对）：`peak_date` 的 `scope` 绑定、段内公共衔接句被拆成固定文字、包内图表 id 与 `calculations.yaml`、写作提示词覆盖。
- **只改基座、与是否删包无关**：token 计价、审核轮次上限、预览是否嵌图、版式装饰图被误计为待出图、确认阶段工具箱是否纳入计算目录。这些在基座修好后，对已有包同样生效，不必删包。
- **删包的代价**：已确认模板、当期任务和报告会被清掉，需要重新上传历史报告并走完整确认。没有用户明确要求时不要删包重建。

## 附录 A：证据索引（排障时按图索骥）

**列口径：文件 + 函数/符号，不写行号**（理由见 4.1 引用纪律）。找不到函数名时按符号字面量搜。

| 主题 | 文件 · 函数/符号 |
|---|---|
| 34 条声明顺序 | `packages/anshun_monthly/prompts/index.yaml` 的 `agent_prompts` |
| 分层查找 / 来源 | `core/prompts/registry.py` 的 `prompts()` / `_resolve` |
| 字节口径 | `core/prompts/registry.py` 的 `_text`（UTF-8 无 BOM、`\n`、恰好一个结尾 LF） |
| 四个数据对象 | `core/agent.py` 的旧名 `AGENT_PROMPTS` / `AGENT_DEFINITIONS` / `TEMPLATE_POLICY` / `REPORT_PROMPT_PROFILES`——**已是 PEP562 懒加载代理**（`__getattr__` + `_LAZY`），首次读取才解析当前包并发 DeprecationWarning；新代码用 `get_prompt()` / `core.packages.load_package()` |
| 缺键为什么 import 期不报错 | `core/agent.py` 的 `__getattr__` 懒代理与 `get_prompt`：模块级无快照，缺键只在首次取用抛 `unknown_agent_prompt`；`check_package.py` 的 LOAD 段同样不拦（demo_b 缺 24 键仍 PKG-OK） |
| **17 条无条件读取** | `core/agent.py` 的 `prompt_fingerprint(prefix=('writer.', 'historical_researcher.'))`；调用点 `app/structured_writer.py` 的 `_write_draft` |
| **共用节点 / 裁剪粒度** | `core/agent_steps.py` 的 `ROLE_STEPS` / `INLINE_STEPS` / `BYPASS` / `prune_spec` |
| 模板确认产物 | `app/api_views/template.py` 的模板确认接口 + `core/storage.py` 的 `put_artifact` |
| 模板规则归一 | `app/review_service.py` 的 `check_rules` |
| 模板开关（四开关真相源） | `core/structured_template.py` 的 `template_feature_switches`；`app/api_views/template.py` 的 `PROCESSING_FEATURES` |
| 包级 features 工具表 | `core/tools/registry.py` 的 `FEATURE_TOOLS` |
| 模板级开关消费 | `app/workflow.py` 的 `resolve_tools` / `_analysis_refs` / `after_processing` / `_processing_policy` |
| 基础角色→步骤 | `core/agent_steps.py` 的 `ROLE_STEPS` / `ALL_AGENTS` |
| 不声明历史调研的后果 | `app/structured_writer.py` 的 `_write_draft`（`prepare_history` 条件块）；`tests/test_s10_agent_dispatch.py` 的 `test_historical_research_never_runs_when_not_declared` |
| TOP10 分支 | `core/event_analysis.py` 的 `analyse_events` |
| 事件五条提示词的调用点 | `core/event_analysis.py` 的 `analyse_events`（`event_judge.pairs` / `.top10` / `.repair`、`event_classifier.classify`、`event_summarizer.summary`） |
| 首页热点 30 条 | `app/hotspot.py` 的常量 `ITEM_COUNT=30` 与硬校验；`core/prompts/base/agent/hotspot_collector.collect.md` |
| 三轮模板研判入口 | `app/template_execution.py` 的三轮状态机：`ROUND_INSTRUCTION_KEY`（r1 batch / r2 repair / r3 advice）、`review_batches`、轮次事件 `template_round_started` / `template_round_passed`（旧 `app/template_advice.py` 与 `app/template_advice_api.py` 已删除，功能并入第三轮终审） |
| **legacy 槽位路径（不可用）** | `app/reviewers.py` 的 `begin_run` → `core/storage.py` 的 `get_artifact`（未知 ref `raise KeyError`）；`core/slot_writer.py` 的槽位写作 |
| 历史报告读取 | `core/tools/ooxml.py` 的 `read_docx` |
| 包级模板词表/槽位 | `packages/anshun_monthly/template.json` |
| 占位符清单 | `templates/anshun_monthly/report.template.json`（99 个） |
| 门禁哈希对象 | `scripts/gate_prompts.py` 的 `BASELINE` / `BUNDLE_KEYS` / `bundle()` |
| 门禁扫描面 | `scripts/gate_prompt_neutral.py` 的 docstring（扫描面） |
| core 身份哈希 | `scripts/gate_core_iso.py` 的 `observe()` / `tree_hash` |
| 事实来源（调研报告） | `.conda/research/role-prompt-map.md`（34 键总表、features 四开关实测、共用节点、legacy KeyError、运行时例外清单） |

## 附录 B：本文用到的实测命令（可复现）

```powershell
# 读四份历史报告的结构与章节
@'
from core.tools.ooxml import read_docx
for f in ('2026年6月安顺市网络舆情分析报告.docx',
          '2026年7月安顺市网络舆情分析报告.docx',
          '2026年8月安顺市网络舆情分析报告.docx',
          '2026年10月安顺市网络舆情分析报告.docx'):
    d = read_docx(f)
    print(f, len(d['blocks']), sum(len(b['text']) for b in d['blocks']))
    for b in d['blocks']:
        t = b['text'].strip()
        if t.startswith(('一、', '二、', '（一）', '（二）', '（三）', '（四）')):
            print('  ', b['index'], t[:60])
'@ | & $py -

# 看模板的三面
@'
import json, pathlib
t = json.loads(pathlib.Path('templates/anshun_monthly/report.template.json').read_text(encoding='utf-8'))
print('placeholders', len(t['placeholders']))
print(sorted({p['slot_type'] for p in t['placeholders']}))
p = json.loads(pathlib.Path('packages/anshun_monthly/template.json').read_text(encoding='utf-8'))
print('vocabulary', list(p['vocabulary']))
print('writer_slots', p['writer_slots'])
print('data_contract', list(p['data_contract']))
'@ | & $py -

# 看覆盖来源
@'
from core.packages import load_package
from app import agent
print(len(load_package(None).agent_prompts))
print(sorted(k for k, v in agent.provenance().items() if v == 'package'))
'@ | & $py -
```

完成判据：三条命令都能跑；输出与本文的实测数字一致（不一致时以你的实际包为准，并把差异写进对比报告）。
