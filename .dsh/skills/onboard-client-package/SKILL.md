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
| 机制与落点 | 二、七、八、十、十二 | 输入怎么读、`agents:` 怎么声明、每个答案落到哪个文件哪个字段、建完怎么自检、报错怎么修 | 包跑不起来，或建出来的包缺机制 |
| 流程与协议 | 一、三、四、五、六、九、十一 | 怎么和人对话、需求集怎么推、34 条怎么逐条判、什么该问什么不该问、正文怎么写、怎么测、怎么交接 | 提示词写错：该改的没改、写了客户事实、或该写的没写 |

读法：先读第一章定交互方式；按 二 → 三 → 四 → 五 → 六 → 七 → 八 做题；九、十一 在写完提示词之后；十、十二 随时查。

产出物固定为六样：

1. `packages/<新包>/manifest.yaml`
2. `packages/<新包>/template.json`
3. `packages/<新包>/prompts/index.yaml`
4. `packages/<新包>/prompts/roles.yaml`
5. `packages/<新包>/接入记录.md`（输入 / 缺口表 / 问答记录 / 提示词清单 / 自检证据 / 遗留，六段格式见 5.6）
6. `packages/<新包>/对比报告-<期号>-<日期>.md`（每次测试运行一份，格式见 9.2）

三条纪律，违反任一条产出不接受：

- **不许猜**：材料能读出来的自己读；读不出来才提问，且按 5.1 先分事实类 / 判断类。
- **成批提问**：一次最多 4 问，每问带现状 / 建议 / 为什么需要你定（1.2）。
- **每条断言有命令**：写进文件的每个结论，都必须能用一条命令重跑复现；写「应该没问题」等于没做。

**默认策略（旧默认已作废）**：新客户的提示词不是「不写覆盖、全部继承基座」。正确默认是——**先推导需求集（底线 28 条必写），再对每条判「改写 / 沿用基座」**；该写的写，该沿用的登记依据；只有 6 条旁路/条件键可省，且必须登记（3.3、3.4）。理由：基座兜底会静默生效、不会报错，客户体例错在报告里，没有任何门禁拦得住。

## 一、交互协议（硬要求）

这五条的优先级高于本文件其它所有内容。与用户的每一次交互都按这五条走。

### 1.1 只提问不输出思考

- 不写「我先分析一下」「我理解你的意思是」「接下来我将」；不解释结论怎么来的，只给结论 + 证据。
- 不写思维链、不写方案草稿、不写「我准备改哪几条」的预告。
- 一条回复只做一件事：提问，或交付。

### 1.2 一次最多 4 问，每问带三样

- 判断类问题成批问，**一批最多 4 个**；按决策分组，不按 34 个 key 逐条刷问。
- 每问三样齐全：**现状**（我从材料读到的）、**我的建议**、**为什么需要你定**（材料里读不出来的理由）。缺一样就是不合格的问题。
- 可直接改写的模板见 5.4。材料缺口（2.6）不属于判断类，单独报告，不混进提问批次。

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

以上 5 条适用于**每个阶段的内部**。跨阶段时，agent 必须遵守新的两条：

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
  use: [sentiment, daily, platform, theme, locality]   # 只能是基座这 5 个图 id

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
- **`charts`**：`pack` 固定 `chart-core`；`use` 的值只能是基座 5 个图 id（`sentiment / daily / platform / theme / locality`），且必须与 `template.json` 的 `charts[].id` **同集合**（`tests/test_s3_chart_registry.py` 钉住）。
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
    {"id": "sentiment", "title": "舆情调性分布", "family": "pie", "style": "pie",
     "binding": {"source": "metrics.sentiment"}, "unit": "条",
     "scope": "all_records", "axis_label": "调性"}
  ]
}
```

判据：

- **顶层 5 键必备**：`package / version / data_contract / vocabulary / charts`；`writer_slots` **可选**（`scripts/check_package.py` 的 `TEMPLATE_TOP_KEYS`）。
- **`data_contract` 四键必备**：`sheet_index / required_columns / summary_columns / column_map`；`column_map` 必须含 `required_columns` 的每一列，否则报 `column_map 缺必需列映射`；`column_map` 的**键序就是 records 的字段序**（5.2 第 3 项）。`dedup` 四数不在价签上（TEMPLATE 段不校验），但运行期去重要用，骨架就按 5.2 第 8 项写全。
- **`vocabulary.localities` / `cluster_terms` 必须非空**；`cluster_terms` 的 label 不得重复（重复键单独报 `cluster_terms label 重复`）；label 顺序 = 模型枚举序。
- **`charts` 必须非空数组**；`charts[].id` 集合与 `manifest.charts.use` 同集合，id 只能是基座 5 个之一。
- **`writer_slots` 骨架阶段写 `[]`**：模板确认后才拿得到 `writer_schema` 里的真实槽位，阶段 3 再补齐（见 1.5.6）。包内没有 `templates/<新包>/` 时，check_package 对 `writer_slots` 只提示「未机械核对」，不判错。

#### ⑤ 建完自检

```powershell
& $py scripts\check_package.py --package <新包>
```

判据：退出码 `0`、末行 `PKG-OK <新包>`；七段里 `FILES / MANIFEST / TEMPLATE / PROMPTS / ROLES / LOAD` 必须是 `ok`，`AGENTS` 在未声明 `agents:` 时是 `skip`——**`skip` 不是失败**。实测两包（原样输出）：

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

`check_package` 末行拿到 `PKG-OK` 之后，**立即停止执行**，把下面这段原样发出（只允许替换 `<新包>`，其余一个字都不改）：

> 包骨架已建好并通过自检：`packages/<新包>/`
>
> 接下来需要你操作（我在这里等）：
>
> ① 确认 `GET /api/packages` 里有你的新包且 `usable: true`（不在列表里就是包还没建好：先跑 10.2 自查；坏包会 `usable:false` 并带 `error` 原因）。
> ② 去「02 模板确认」上传 2 份历史报告，走完模型研判（实测约 268 秒）。
> ③ 在「预览并确认模板」里确认。
>
> 确认完成后告诉我，我会读已确认模板继续写提示词。

**三条硬约束（红线）**：

- ❌ 不许 agent 自己继续往下走：不发完话术顺手写提示词、不顺手改 `template.json` 的槽位、不顺手跑第九章测试。
- ❌ 不许绕过模板确认直接写提示词：没有已确认模板就拿不到 `blocks` / `fields` / `rules` / `writer_schema`，写出来的是猜的，而且会静默回退基座、不报错。
- ✅ 必须明确说「我在这里等」，并且真的停：发完话术的同一个回合内不再有任何写盘动作。

### 1.5.4 阶段 2：人工做什么（agent 只等，不代办）

#### ① 新建任务时选客户（不需要切包、不需要重启）

「02 模板确认」页有 `#templatePackage` 选择器，「03 数据处理」页有 `#reportPackage` 选择器（`app/static/app.js` 的 `loadPackages`）。两处数据都来自 `GET /api/packages`，**只列 `usable:true`** 的包；只有一个可用包时默认选中并 `disabled`（不制造多余交互）。

- 上传与建任务请求都带 **`X-Report-Package: <包名>`** 头：`POST /api/files`、`POST /api/template-tasks`、`POST /api/report-tasks`（`app/static/app.js` 的 `packageHeaders`）。
- 服务端解析在 `app/packages_api.py` 的 `resolve_package`：包名未登记 → **404 `package_not_found:<包>`**；登记了但不可用 → **422 `package_unavailable:<包>:<原因>`**；**空 = 部署默认包**（`REPORT_PACKAGE`）。
- **没带这个头不会报错**：请求落到部署默认包，文件与任务一起落错客户——这是最常见的静默错误，比 404 难查（见 10.2 第 4 条）。
- 模板确认时会把**这个包的** features 快照进 `template_version`（`app/workflow.py` 的 `_template_features` / `task_feature_snapshot`）。选错客户 = 快照的是别的客户的开关，而报告里不会报错：所以选完客户先核一次 `TaskState.package`（10.2 第 2 条）。

#### ② 上传至少 2 份历史报告（docx）

「02 模板确认」页面传 2 份以上历史报告。**少于 2 份不能确认**：确认后的读模板门（`core/structured_template.py` 的 `load_confirmed_template`）要求 `source_reports` ≥ 2。

#### ③ 等模型研判

本机实测约 268 秒（与报告篇幅、模型端点有关，不是固定值）。

#### ④ 在「预览并确认模板」里确认

- 核对字段与占位符：字段 `owner`（`data` / `writer`）、`kind`、`semantic`、章节归属。
- 需要改的字段**可以编辑**（显示名称 / 字段语义 / 归属），但**必须在确认前改**：确认后的模板 `status=confirmed_by_human`，编辑接口会拒绝（`app/api_views/template_field.py` 给 `immutable_confirmed_template`）。
- 确认并保存：落盘两样物证——`template_version` 工件 `status=confirmed_by_human`，任务 `metadata.confirmed_template_ref` 非空。

### 1.5.5 交接点 B：agent 怎么判断「可以开始了」

不许靠「用户说可以了」：「模板好了」是口头话，不是判据。要检测到**已确认模板的物证**。

**方式一：HTTP（服务在跑）**

```powershell
$items = Invoke-RestMethod http://127.0.0.1:8765/api/templates
$items | Where-Object { $_.status -eq 'confirmed_by_human' } | Select-Object id, name
```

`GET /api/templates` 只把「`kind=template` + `metadata.confirmed_template_ref` 非空 + 非 simulation + 工件带 `writer_schema`」的任务映射成 `status='confirmed_by_human'`。返回里**恒有一条** `id=anshun-monthly-colored`、`status=candidate_requires_review` 的候选（实测当前只有这一条）——候选不是已确认，不许拿它当已确认模板用。

**方式二：直接读盘（服务没起也能查，判据最硬）**

```powershell
@'
import app  # 配好 paths.configure_data_root(DATA)
from app.storage import Store
from core.structured_template import load_confirmed_template
store = Store()
hits = []
for t in store.list_tasks():
    ref = t.metadata.get('confirmed_template_ref')
    if not ref: continue
    try: tpl = load_confirmed_template(store, ref)
    except ValueError: continue
    hits.append((t.id, ref, len(tpl.get('source_reports') or [])))
print('confirmed_templates', len(hits))
for h in hits: print(h)
'@ | & $py -
```

`load_confirmed_template` 就是应用自己的门（`core/structured_template.py`）：`status=='confirmed_by_human'`、`source_reports` ≥ 2、`comparison_ref` 与 `writer_schema` 非空，缺任一项抛 `ValueError`（`confirmed_two_report_template_required` / `structured_template_missing`）。本机实测输出 `confirmed_templates 0`（当前库里 5 个任务，没人确认过模板）——这就是「还没好，继续等」的样子。

**`GET /api/tasks` 不够用**：它的 `metadata` 是白名单，只回 `{'simulation': ...}`（`app/main.py` 的 `tasks()`），**拿不到 `confirmed_template_ref`**；要按任务查就打 `GET /api/tasks/{task_id}`（整份 state）。

**检测不到就继续等**：不进阶段 3、不写任何提示词文件、不「先写两条试试」。等待期间只允许读输入（第二章），不产出。

### 1.5.6 阶段 3：提示词撰写（本阶段只做触发与衔接）

阶段 3 的完整流程见「三、能力开关与需求集推导」+「四、34 条逐条差异分析」+「六、撰写规范」，本阶段只做三件事：

1. 用 2.2 的四类输入读已确认模板（`blocks` / `fields` / `rules` / `writer_schema`），先跑 2.6 输入自检；不通过就停在材料缺口，不猜。
2. 按 3.3 → 3.5 的顺序推需求集（28 条必写 + 最多 6 条可省），再按第四章逐条判、第六章写。
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
- **不需要重启**：包配置按需加载（键 = 包 + 指纹），改客户包文件（`manifest.yaml` / `template.json` / 提示词）后按需重读即生效；**只有改基座代码（`core/` / `app/`）才需要重启服务**。

## 二、输入准备（读什么、怎么读）

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
| 历史报告 | `*.docx`（本项目现有 2026 年 6/7/8/10 月四份） | `from core.tools.ooxml import read_docx` | `blocks`（段落/表格）、章节序列、字数、数字类型、句式、体例 |
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

`fields` 的常见键（以实际工件为准）：`id`、`display_name`、`owner`、`kind`、`semantic`、`block`、`binding`、`value_schema`、`sources`、`rule`、`format`。其中：

- `owner=data`：统计/任务元信息，由程序或数据工具填；
- `owner=writer`：需要按本期证据写的文字；
- `kind`：`number`、`text`、`analysis`、`paragraph_list`、`table_rows` 等，决定这条字段走哪条提示词；
- `binding`：取数绑定，只能来自 `available_bindings`，不明确的留 `null` 并写缺口。

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

### 2.3 现有包文件（两个现成参照）

- `packages/anshun_monthly/`：全量参照。34 个提示词键（全部继承基座、0 覆盖，`prompts/agent/` 目录存在但为空）、11 个角色、8 个区县（含 9 个别名）、12 个类目、5 张图、9 个 writer 槽位、显式 `agents:` 9 个。
- `packages/demo_b/`：最小参照。10 个提示词键（10 条全部覆盖）、3 个角色、2 个片区、2 个类目、3 张图、**没有** `agents:` 段。

一次看两个包的四个文件的结构（不要通读全部文本）：

```powershell
@'
import json, pathlib, yaml
for name in ('anshun_monthly', 'demo_b'):
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

要点（实测）：`manifest.yaml` 的键是 `package/report_type/version/template/prompts` + 可选 `agents/tools/charts/skills/capabilities/features`；`template.json` 的键是 `package/version/data_contract/vocabulary/charts` + 可选 `writer_slots`；两个 `index.yaml` 都恰好四个顶层键；`roles.yaml` 是 `角色 id → {responsibility, boundary, output}`。

### 2.4 历史报告

`read_docx` 的返回结构（`core/tools/ooxml.py` 的 `read_docx`）：

```python
{'path': str(path), 'blocks': [
    {'index': 3, 'kind': 'paragraph', 'text': '...', 'style': ''},
    {'index': 34, 'kind': 'table', 'rows': [['序号','事件','热度'], ...], 'text': '...'},
]}
```

- `paragraph` 有 `text`、`style`；空段落会被跳过，所以 `index` 是原文档 body 的序号，不连续。
- `table` 有 `rows`（二维数组）和拼好的 `text`；TOP10 表就是 `kind='table'`。
- **不要用 `style` 判断章节**：这四份报告的章节标题 `style` 多为空，`（一）` 段反而可能是 `style='5'`。按 `text` 正则判断。

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

### 2.6 输入自检（不通过就停，不要猜）

- [ ] 四份历史报告都能 `read_docx`，`blocks` 非空，章节标题能按正则找到。
- [ ] `template_version.status == 'confirmed_by_human'`；`version` / `name` 与客户对应。
- [ ] `fields` 的 `id` 不重复；每个字段都有 `owner`、`kind`、`semantic`；`owner=writer` 的字段能对应到章节。
- [ ] `rules.features` 四个键都在；`rules.event_threshold` 在 `(0,1]`。
- [ ] `packages/<pkg>/template.json` 有 `vocabulary.localities`、`vocabulary.cluster_terms`、`writer_slots`、`data_contract`。
- [ ] `manifest.agents` 里的角色都在 `roles.yaml` 里；`manifest.features` 的五个键 `locality` / `dedup` / `event_classification` / `first_warning` / `top10` 都是合法键，值形态 `{enabled: true|false}`（见 3.1）。
- [ ] `prompts/index.yaml` 的 `agent_prompts` 覆盖 34 个 key；`provenance()` 能跑通。

任一项不满足：把它当作**材料缺口**报告给维护者，不要用推断补。材料缺口不是「判断类问题」，不要混进 5.4 的提问批次。

### 2.7 维护者确认模板之后的第一步

不要先写 `manifest.yaml`。先跑这三条命令看现状，把输出贴进 `接入记录.md` 的「输入」段：

```powershell
cd D:\智能分析报告重构版V5
$env:PYTHONIOENCODING = 'utf-8'
$py = 'D:\智能分析报告重构版V5\.conda\JJDreport\python.exe'

# 1 基座提示词此刻必须仍然客户无关（新包的地名/类目名会让词数变大，判据是 RESULT: PASS）
& $py scripts\gate_prompt_neutral.py

# 2 记下基座与宿主的字节身份（建完包后四行必须逐字符不变）
& $py -c "import sys;sys.path.insert(0,'scripts');import gate_core_iso as g;o=g.observe(g.REPO/'core',g.REPO/'app');print('CORE-FILES',o['core_files']);print('CORE-DEP',o['core_dep']['sites'],'sites /',o['core_dep']['files'],'files');print('CORE-HASH',o['core_hash']);print('APP-HASH',o['app_hash'])"

# 3 现有包的契约必须全绿（三条用例遍历 packages/*/）
& $py -m pytest tests\test_s7_package_contract.py -q
```

三条都符合预期才动手：第 1 条不是 `RESULT: PASS` → 基座已经脏了，先报给维护者；第 2 条的四行写进记录，建完包后重跑对比；第 3 条不是 `3 passed` → 现有包已经坏了，新包会继承同一个问题。

然后按顺序做：第二章读输入 → 第五章判缺口并成批提问 → 第七章定 `agents:` → 第三章推需求集、第四章逐条判、第六章写提示词 → 第八章落文件 → 第九章测试对比 → 第十章六条自检 → 把证据贴回 `接入记录.md`。

## 三、能力开关与需求集推导（先定底线，再逐条判断）

### 3.1 三层开关，别混

| 层 | 位置 | 决定 | 谁改 | 对提示词需求集的影响 |
|---|---|---|---|---|
| ① 客户包能力 | `manifest.agents` + `manifest.features` | 这个客户**有没有**这项能力 | 建包时定 | **决定节点是否被裁**（`core/agent_steps.py` 的 `prune_spec`）：裁掉的节点驱动的 key 才可能不写；这是文件集下限的来源之一 |
| ② 模板开关 | `rules.features`（`dedup` / `classification` / `first_warning` / `top10`） | **这一次建模板**要不要用 | 每次建模板 | **不缩小文件集**：只决定这一次调不调，真实影响见 3.6.1 |
| ③ 提示词覆盖 | `packages/<pkg>/prompts/` | 这个客户**怎么写**这段话 | 建包时写 | 28 条必写键按「改写 / 沿用基座」落文件 |

**包级 `manifest.features` 实际只消费三个键**（`core/tools/registry.py` 的 `FEATURE_TOOLS`）：

- `locality`（控制 `resolve_locality`）
- `dedup`（控制 `group_events`、`propose_keyword_event_candidates`、`propose_vector_event_neighbors`）
- `event_classification`（控制 `classify_records`、`cluster_event_themes`、`discover_topics`）

`first_warning` / `top10` **有包级开关**（`manifest.features` 五键之一），但它们**没有专属工具白名单**：`FEATURE_TOOLS['first_warning']` 映射为空组，`top10` 只映射 `select_materials`。所以关掉它们时「给模型的工具清单」几乎不变，真正被停掉的是**口径产物与冻结事实**（不再写 `first_section_warning_event_count`、不再产 TOP10 梗概与榜单），以及模板侧对应段落不再生成。

两层开关的相与发生在 `app/workflow.py` 的 `_template_features`：**生效值 = 包级 AND 模板级**。注意 `resolve_tools` 不认识 `first_warning` / `top10` 这两个键名的模板侧写法（模板级用 `top10`，包级映射到 `select_materials`），所以判断「这次跑不跑」要看生效值，不要只看模板里的 `template_rules.features`。

### 3.2 两条不同的推导：文件集 vs 本次调用集

| 问题 | 能否静态推导 | 结果 |
|---|---|---|
| 「这个客户要交付哪些提示词文件」 | **能**，机械推导 | 34 − 可省 6 = **28 条必写**；指纹读的 17 条与包级 `agents` 无关 |
| 「这个客户这一轮实际会发哪些提示词给模型」 | **不能**，只能给上界 + 逐条条件 | 由 `manifest.agents` + 模板级 `rules.features` + 入口 + **运行时数据/模型返回** 共同决定 |

为什么模板级开关不缩小文件集：

- 模板级开关的语义是「这次建模板用不用」，不是「这个客户永远不用」。
- 同一个客户可以建多个模板：A 模板关掉 TOP10，B 模板可能开。若按 A 模板把 `event_judge.top10` 判成可省不写，B 模板一开就会**静默回退基座**，产出不符合客户体例的结果。
- 包级开关才是能力边界：`manifest.agents` 不声明某角色，图里对应节点会被 `prune_spec` 裁掉；`manifest.features.dedup=false`，`group_events` 等工具直接退出白名单。**但即使节点被裁，指纹读的 17 条照读**——这就是底线 28 的来源（3.3）。

**一致性规则**：包级关了的能力，模板级也要关；否则模板会要求一个产不出来的产物。例：包级 `dedup=false`，模板 `rules.features.dedup` 必须也是 `false`，否则分析门禁 `_analysis_refs()` 仍恒要求 `group_events`，而工具已被扣掉。

### 3.3 需求集 = 必写 28 / 可省 6（外加一个正交标签「待定」）

| 清单 | 判定 | 条数 | 动作 |
|---|---|---|---|
| **必写** | 不管客户声明什么角色、开哪些 `features`，文件必须存在且非空。其中 **17 条**被 `prompt_fingerprint` 无条件读，**11 条**由节点可达性决定 | **28** | 写；基座够用也要写一条「沿用基座」+ 一句依据 |
| **可省** | 旁路/条件键，客户真的不用时可以不出文件 | **6** | 不出文件，登记到 `NOT_USED.md`（3.7） |
| **待定**（正交标签，不是第四张清单） | 文件**仍必须存在**，但「这一次调不调」由运行时数据 / 模型返回决定 | 标在必写内部 | 照写；触发条件看该行判据 |

**为什么底线是 28 而不是 15~25**：`core/agent.py` 的 `prompt_fingerprint(prefix=('writer.', 'historical_researcher.'))` 在每次结构化写作开头，把已声明的 13 个 `writer.*` + 4 个 `historical_researcher.*` 一次性全读一遍，不管这个客户声明了哪些角色。实测：客户包**不声明** `historical_researcher` 时，4 个历史键**仍被 `_write_draft` 路径取用**（`app/structured_writer.py` 的 `_write_draft` 调 `prepare_history`），读不到直接 `ValueError: invalid_agent_prompt` → **整个写作入口 500**。

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
| 26 | `event_judge.repair` | 可省·条件 | 只在 TOP10 结构化校验失败的重试轮读 | `core/event_analysis.py` 的 `analyse_events` |
| 27 | `template_analyst.batch` | 必写·节点 | 整份结构审查必读 | `app/template_execution.py` |
| 28 | `template_analyst.repair` | 可省·条件 | 只在前一轮 invalid 时读 | 同上 |
| 29 | `data_processor.next_tool` | 可省·条件 | 只在任务 `metadata['mode']=='dynamic'` 时读；`fallback` 模式从不读 | `app/workflow.py` 的 `_process_records` |
| 30 | `template_analyst.charts` | 必写·节点 | `make_input` 拼提示词必读 | `app/template_review.py` |
| 31 | `template_analyst.advice` | 可省·旁路 | 只在模板修审接口；不在任何图节点里 | `app/template_advice.py` |
| 32 | `model.json_output` | 必写·节点 | 拼进每条真实模型请求的 system prompt | `core/model_client.py` |
| 33 | `model.tool_budget_exhausted` | 可省·条件 | 只在带 tools 且工具回合到第 7 轮 | `core/model_client.py` |
| 34 | `hotspot_collector.collect` | 可省·旁路 | 只在首页热点采集接口；独立宿主任务，不在报告图里 | `app/hotspot.py` |

合计数：必写 = 1~25、27、30、32（共 **28**）；可省 = 26、28、29、31、33、34（共 **6**）。

### 3.4 「可省」的唯一安全边界

**只能省 3.3 表里这 6 条，且各自有前提；前提不成立就要写。**

| 可省 key | 不出的前提 |
|---|---|
| `template_analyst.advice` | 客户不用模板修审接口 |
| `hotspot_collector.collect` | 客户不要首页「今日热点」 |
| `data_processor.next_tool` | 该客户所有任务走 `fallback` 模式（不开动态规划） |
| `model.tool_budget_exhausted` | 该客户所有调用都不带 tools，或已确认到不了第 7 轮 |
| `template_analyst.repair` | 客户永不重建模板；**只要跑模板图就写** |
| `event_judge.repair` | 客户永不开 `top10`。保守做法：随 `event_judge.top10` 一起写 |

**绝对不可省**（省了会 500）：

- 13 个 `writer.*`，包括 4 个 `writer.slot.*`（legacy 路径虽然跑不通，但指纹照读）；
- 4 个 `historical_researcher.*`——「客户不做历史调研」**不是**不写的理由；
- `model.json_output`、`style.application`、两条 reviewer 键、3 个 `template_analyst` 结构键、4 条事件键（`event_judge.pairs` / `event_judge.top10` / `event_classifier.classify` / `event_summarizer.summary`）。

**一个已知例外（仍按必写处理）**：包级 `dedup=false` 且模板级对齐时，`analyse_events` 根本不进 → 5 条事件键这一次不被读。但它们仍按必写处理，理由有二：带旧 `group_events` 产物重跑（`reprocess_events` 分支）会让门禁重新满足，`analyse_events` 仍会跑；客户后建的模板可能把 `dedup` 打开。

**拿不准时一律写**，哪怕只写「沿用基座」+ 一句依据。

**声明面口径（已核实，不再存疑）**：加载器**不校验条数**。`core/prompts/registry.py` 的 `_bundle` 对 `agent_prompts` 只有两项校验——非空映射、逐 key 路径可解析；`scripts/check_package.py` 的 `check_prompts` 也只逐 key 校验，PROMPTS 段打印 `N keys: base + overrides` 而不判 `N==34`。实测 `packages/demo_b/` 只声明 10 条，`PKG-CHECK` 输出 `PROMPTS ok (10 keys: 0 base + 10 overrides)`、`LOAD ok`。但**少声明不是安全动作**：任何被 `get_prompt` 取用而未声明的键都会抛 `KeyError: 'unknown_agent_prompt:<key>'`，而且 `core/agent.py` 顶部有 5 个键是**模块级硬依赖**（`AGENT_PROMPTS[...]`，见 6.4）。所以操作口径固定为：**34 条全部声明**；「可省」只表示「不写覆盖、按基座继承」，`NOT_USED.md` 记录前提与证据，不改变声明面。

### 3.5 建包顺序（不能反）

```
① 先定包级能力（manifest.agents 声明哪些角色 + manifest.features 开关）
② 由 ① 定可省清单：默认空 —— 28 条全要
③ 对 28 条必写逐条判断：改写 / 沿用基座
④ 确要省时，只省 3.3 那 6 条，并在 NOT_USED.md 写明前提与证据
```

先写提示词再定能力，会写一堆永远不会被调用的文件；更糟的是，能力后来打开时，没写的条目会静默回退基座。反过来「先省后写」更危险：省错一条不在那 6 条之内的键，写作入口直接 500。

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
  前提：客户不要首页「今日热点」。证据：Q7 客户确认只用月报，不用首页。
- template_analyst.advice
  前提：客户不用模板修审接口。证据：建包范围说明（接入记录.md）。
- data_processor.next_tool
  前提：该客户所有任务走 fallback 模式，不开动态规划。证据：manifest / 任务参数。
```

写法要求：

- 一条一行：**key + 不出的前提 + 证据**；前提必须是 3.4 表里那一条。
- **只登记那 6 条可省键**。下列 key 写进这个文件就是错误：13 个 `writer.*`、4 个 `historical_researcher.*`、`model.json_output`、`style.application`、`format_reviewer.review`、`content_reviewer.review`、`template_analyst.template` / `.charts` / `.batch`、`event_judge.pairs` / `.top10`、`event_classifier.classify`、`event_summarizer.summary`。
- 不要写「暂时不用」。暂时不用 = 这次不调但文件仍要存在 → 按必写处理，状态写「沿用基座」+ 依据。
- 半年后有人问「为什么这个客户没有首页热点」，翻这一个文件就有答案；反过来，有人问「为什么客户不用历史调研还得写 4 条历史提示词」，答案在 3.3，不在这个文件。

### 3.8 两条硬约束（反向比正向更要紧）

```
❌ 某功能启用了，但对应提示词没写
```

这时系统会**静默回退到基座提示词**，产出「语法正确但不符合该客户体例」的结果——**而且不报错**。`provenance()` 只会显示 `base`，不会告诉你「这里本该有覆盖」。

```
❌ 某功能没启用（角色没声明 / 开关关着），提示词也没写
```

这不一定安全，**可能直接 500**：`prompt_fingerprint` 不看角色是否声明，每次结构化写作开头无条件读 17 条（13 个 `writer.*` + 4 个 `historical_researcher.*`）。实测「不声明 `historical_researcher`」的包，4 个历史键仍被读，读不到直接 `ValueError: invalid_agent_prompt` → 写作入口 500。所以「省」只能省 3.3 那 6 个确认安全的键。

规则只能是二选一：

```
要么按 3.3 那 6 条的口径省（并登记）
要么写（哪怕只写「沿用基座」+ 一句依据）
不存在「不在 6 条之内、但可以不写」
```

为什么：基座兜底是分层查找的正常行为，不是错误；它不会区分「客户确实想用基座」和「客户忘了写」。把「开着但没写」当成合法状态，等于把判断责任推给运行时，而运行时只会静默选基座；把「关着也没写」当成安全，等于把 500 留给客户第一次点「起草」。

### 3.9 角色 → 提示词映射（已按调研填入）

| 角色 | (graph, node) | 该动作内实际读的 key |
|---|---|---|
| `template_analyst` | `template` / `local_compare_and_analysis` | `template_analyst.template` + `template_analyst.charts`（`app/template_review.py` 的 `make_input`）→ `template_analyst.batch`（`app/template_execution.py` 的 `review_batches`）→（某轮不合法时）`template_analyst.repair` |
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
| `template_analyst.template` / `.charts` / `.batch` | 建模板时必跑 |
| `data_processor.next_tool` | 动态规划模式必跑 |
| `format_reviewer.review` / `content_reviewer.review` | `review_policy` 会把 `role + '.review'` 当 hash 材料读，**即使审核节点被裁**；不能靠「不声明角色」降级 |
| `event_judge.pairs` / `.top10` / `.repair`、`event_classifier.classify`、`event_summarizer.summary` | 三个角色共用一个节点（3.10）：声明任一角色，5 条全用 |
| 任何「角色**已声明**」的情况 | 已声明 = 会被调用，写空壳就是静默减配 |

注：「可省」（3.3）与「可降级」是两回事。可省的键要么不出文件；**一旦决定保留文件，就必须按正文标准写**，不能写成空壳。

#### 3.11.4 违反后果（最难发现的失败）

把**会调用**的键写成空壳 → 报告该段**直接缺失或质量塌陷，而且不报错**。运行时只看到「有文件、有内容、能跑通」，不会告诉你「这一条本来是正文」。这比 `prompt_missing` 难查得多：报错至少说得出哪一条缺，空壳什么信号都不给。

#### 3.11.5 与「可省」的区别（别混）

| | 可省（3.3 那 6 条） | 可降级（3.11.2 这 4 条） |
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

**四个全关也能走通完整流程**（建任务 → 数据审核 → 确认 → 写作 → 出报告，实测出 37~38 KB docx）。

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

**引用纪律（全文适用）**：引用代码位置一律用「**文件 + 函数名 + key 字面量**」，**不写行号**。理由不是洁癖：调研期间 `app/workflow.py` 正在被并行修改，同一个 `get_prompt('data_processor.next_tool')` 调用点在三个不同版本里落在不同位置，`app/workflow.py` 本身也被读到过两个长度不同的版本。位置一漂，文档里的「证据」就变成假的。写不出函数名时退一步写「文件 + 符号字面量」（如 `app/hotspot.py` 的常量 `ITEM_COUNT=30`），也不要写行号。

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
| `template_analyst.batch` | 一次性输出全部 `target_blocks`；程序不再分批汇总（`app/template_execution.py` 的 `FULL_TEMPLATE_KEY` 单批）；逐项修复错误不改正确字段 | 看模板块总数；看 S1~S4 报告长度（3.4k~3.9k 字） | 通常不改 |
| `template_analyst.repair` | 一轮研判失败后的整体修复；owner 冲突时重判用途 | 看校验错误；看模板候选 | 通常不改 |
| `data_processor.next_tool` | 每轮只选一个工具：导入→筛选→属地→候选→去重→分类→聚类→选材 | 看 `manifest.tools.allow`/`capabilities.require`/`features`；看 S1~S4 需要的图/表/TOP10/属地产物；看 T.rules | 客户关能力时白名单裁剪；prompt 步骤描述可能要同步（**措辞**），但不要用 prompt 绕过白名单（**取数/工具**） |
| `template_analyst.charts` | 图表规则：调性/平台饼图、分类纵向柱状、日趋势折线 | 看 `P.charts` 的 `family`/`style`（A 包 5 张）；看 S1~S4 图1~5 类型；看客户是否要不同图 | 客户图表类型不同才改规则/模板 charts（**取数/样式**）；prompt 通常不改 |
| `template_analyst.advice` | 确认后只读审核：只提修改意见，不改模板 | 看 T.fields 边界/owner；看 S1~S4 原文；看是否要审核 | 通常不改 |
| `model.json_output` | 强制只输出符合给定 JSON Schema 的对象，不解释不加 Markdown | 看所有模型调用都带 `response_schema`；客户无例外 | 不改 |
| `model.tool_budget_exhausted` | 预算用完只依据已读资料总结；证据不足写缺口，不编造/不再调工具 | 看 `manifest.tools.budgets`（A 包 `default: 40`、`writing: 80`）；看客户数据量 | 通常不改；预算在 manifest 改 |
| `hotspot_collector.collect` | 从检索结果挑 30 条要闻，排序/归类/链接，只输出 JSON | 看 `payload.categories`；看 `app/hotspot.py` 的常量 `ITEM_COUNT=30` 与同一文件的硬校验；看 S1~S4 月报没有首页热点（它是独立开关）；看客户是否要首页热点 | 若要 20 条，**不能只改 prompt**（会 `hotspot_items_incomplete`），必须改代码/配置并立项；类别来自 payload，不要硬编码 |

**本表两条读法**：

1. 「通常改什么」栏说的是**判断**（改写 / 沿用基座）；「这条属于必写还是可省」看 3.3 的分类表，不要从这里推。
2. 4 条 `writer.slot.*` 标注「legacy 路径当前不可用，勿承诺」的确切含义：用 `template_ref='anshun-monthly-colored'` 建的任务跑 preview-draft，写作图 `validate_input` 就抛 `KeyError`（`app/reviewers.py` 的 `begin_run` 把哨兵当 artifact id → `core/storage.py` 的 `get_artifact` 对未知 ref `raise KeyError(ref)`），根本走不到槽位写作。所以这 4 条**只能按「必然存在、本次不会调」处理**：写文件（可从基座继承），但不要在任何交付物里承诺 legacy 写作可用。

### 4.3 填表方法（避免把「判断」写成「感觉」）

每行按四步填：

1. **找产物**：这条提示词被哪个阶段、哪个字段/工具消费？看 B 的正文和调用点；不确定就写「需实测」。
2. **找证据**：在 S1~S4 的哪个位置能看到这个产物的「客户体例」？在 T/P 的哪个字段能看到「客户口径」？证据必须能指到文件 + 段落/字段，不写「历史报告风格如此」。
3. **判性质**：是**措辞**问题（字数、句式、称谓、语气、编号）还是**取数/结构**问题（字段、词表、binding、工具、模板）？前者改 prompt；后者改 `template.json` / 模板 / manifest，或登记为缺口。
4. **写结论**：`改写` 或 `沿用基座`。只有 3.3 的 6 条可省键才可能「不出文件」，且必须先核 3.4 的前提；其余 28 条一律写。

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

判定方法：先在第二章的材料里找；找得到就是事实，找不到或材料互相矛盾才是判断。**不要把自己没读全的东西包装成判断类问题。**

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
3. **材料缺失且影响结构**：如模板没有 TOP10 字段、客户却提到 TOP10；需要确认要不要补。
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
| 1 | package 名、report_type | 🔶 | 包名 = 目录名 = `manifest.package` = `template.json.package`（两个现成包都同值；不一致不会启动失败，但审计行与目录对不上）。`report_type` 取客户报告名称 | 客户同时出多种报告、本期只做一种 → 问做哪一种 |
| 2 | 必需列 `required_columns` | 🔶 | 导入器只校验这个清单，缺列抛 `missing_required_columns`（`core/tools/records.py` 的 `import_records`，常量 `REQUIRED_COLUMNS`）。现成两包都是 `['标题','舆情调性']` | 首行里没有能判调性的列 → 问用哪列判调性 |
| 3 | 列映射 `column_map` | 🔶 | 首行中文列名 → records 英文字段；**键序就是 records 的字段序**（`tests/test_s2_manifest_vocabulary.py` 的 column_map 顺序用例钉住，哈希门禁看不见这层） | 首行有映射表之外、但客户要求进报告的列 → 问映到哪个字段 |
| 4 | 摘要列 `summary_columns` | 🔶 | `[0]` 优先，缺失时取 `[1]` 并截 1200 字（`core/tools/records.py` 的 `import_records`，常量 `SUMMARY_COLUMNS`）；某列不存在不会报错，取空串 | 首选列与兜底列都在首行里 → 问哪一列是正文摘要 |
| 5 | 工作表序号 `sheet_index` | 🔶 | 记在 `data_contract.sheet_index`。**该键目前无消费者**：实际 sheet 来自任务参数，缺省 3（`app/main.py` 的请求参数 `sheet_index:int=3`；`app/workflow.py` 里取 `state.metadata.get('sheet_index',3)`） | 目标表不是第 3 个、且客户会每期换位置 → 问固定哪一个 |
| 6 | 区县清单 `localities` | 🔶 候选 / ❓ 范围 | 候选 = 2.5 数据里出现的行政区写法（噪声很大，见 5.3）；`resolve_locality` 只做词表子串匹配，要求**恰好命中 1 个**（`core/tools/locality.py`） | **辖区范围一律必须问**（见 5.3） |
| 7 | 类目词典 `cluster_terms` | 🔶 候选 / ❓ 口径 | 候选 = 模板图注字段名 + 数据 `事件分类` 列取值分布；键序 = 枚举序（`core/tools/vocabulary.py` 的 `cluster_terms()`）；词典打分 = 词表成员在 `title + 摘要前300字` 的出现次数求和取最大（`core/classify/dictionary.py` 的 `DictionaryStage`） | **分类体系/类目口径一律必须问**（见 5.3） |
| 8 | 去重参数（4 个） | 🔶 | `data_contract.dedup`：`threshold`、`candidate_floor_ratio` 必填无默认；`merge_rounds` 缺省 1、`merge_threshold` 缺省 0.5（`core/tools/vocabulary.py` 的 `dedup_threshold` / `dedup_candidate_floor` / `dedup_merge_rounds` / `dedup_merge_threshold`）。现成两包都是 0.65 / 0.6 / 2 / 0.5 | 客户对「什么算同一事件」有明确口径且与 0.65 冲突 → 问 |
| 9 | 图表清单 `charts` | 🔶 | 从模板图注推导 `id/family/style/binding/unit/scope/axis_label`；`manifest.charts.use` 必须与 `template.json` 的 `charts[].id` 同集合（`tests/test_s3_chart_registry.py` 钉住） | 模板里有图的位置但看不出画什么 → 问 |
| 10 | `agents:` 声明 | ❓ | 无证据可推 | **一律必须问**（见 5.3 与第七章） |
| 11 | 提示词覆盖面 | 🔶/❓ | 先按 3.3 推导需求集：必写 28 条逐条判「改写 / 沿用基座」，6 条可省须按 3.4 前提登记。基座够用 = 「沿用基座 + 依据」，不是「不判断」 | 客户口径/口吻与基座冲突、且材料裁决不了 → 问（模板见 5.4 Q1/Q5/Q6） |
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
- **问法（三样齐）**：
  > 这份报告的辖区范围是哪几个行政区？我给不出默认值——词表外的地名不会进属地统计，命中 0 或 ≥2 都落人工确认。候选是数据里扫出来的这批（含 `其余地区` 这类非地名噪声，已标出）。请给 ①辖区全名单 ②每个辖区的**数据写法**（全称/简称/别名，例如 `西秀区` 在数据里还写成 `安顺市西秀区`）③跨区与不明怎么记。影响面：属地表、属地图、属地未解项数量。

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
- **问法**：
  > 分类体系用哪一套、几个类目？默认值没有——词表与类目不匹配时分类会静默落空（本月数据源分类列实测全空，候选推不出来）。候选可从模板图注与摘要高频词里列给你核对。请给 ①类目名全名单（写入顺序即模型枚举序）②每个类目下的**数据里真实出现**的说法（做词表成员）③不确定的怎么处理。影响面：事件分类、主题聚类、分类图、事件清单呈现。

#### 5.3.3 ❓ agents 声明（要做哪些步骤）

- **为什么需要**：这一段直接决定哪些流程步骤跑、哪些整段跳过（第七章）。
- **不给会怎样**：不写 = 9 个角色全启用，历史调研会联网检索、两位审核员会各跑一轮。
- **默认值**：不写 `agents:`（全部启用）。这也是老包兼容语义。
- **候选从哪推导**：没有。没有任何输入能证明客户要不要历史调研/双审/事件研判。
- **影响面**：图结构（节点被裁 + 前驱改接）、耗时、外部请求、审核轮数、人工确认点。
- **问法**：
  > 这份报告要不要历史调研（会联网检索并核实地方事实）？要不要格式与内容两位审核员？事件研判（同事件判定/分类/梗概）要不要？默认是不写 `agents:`、9 个角色全启用。你的回答会直接决定图里哪些节点被裁掉，以及本次任务是否产生外部请求。

### 5.4 判断类问题库（按需选，一次最多 4 个）

若客户对提示词口径有硬要求，下面六问覆盖了 34 条里所有真实冲突。**一次只问一批（≤4 个）**。

**Q1 工作建议条数**

> 现状：历史四期报告的工作建议是 3 条（6/7 月）或 4 条（8/10 月），每条 315~448 字；基座提示词要求 4~5 类、每类 250~400 字。
> 我的建议：按历史体例取 3~4 条，把基座的「4~5 类」下调为「3~4 类」；如果客户希望更全面，保留 4~5 类。
> 为什么需要你定：这是历史体例与基座默认的直接冲突，改哪边会改变报告结构和篇幅，材料里没有第三份证据能裁决。

**Q2 历史调研角色要不要**

> 现状：`manifest.agents` 如果声明 `historical_researcher`，会联网核对未来 1~2 个月选题；不声明则 `prepare_history` 不跑，**整段「工作建议」不生成**（`monthly_recommendations` 缺失，`historical_evidence_insufficient`），不是只少环比句。注意：**不管声明与否，4 条 `historical_researcher.*` 提示词都必须写**（指纹无条件读，缺了写作入口 500）。
> 我的建议：要工作建议就保留该角色；如果客户明确不要工作建议，再关。
> 为什么需要你定：关掉的代价比字面大，必须让客户知道「关历史调研 = 没有工作建议」。

**Q3 TOP10 要不要 / 几条**

> 现状：模板 `rules.features.top10` 当前是开/关；历史表1 是 10 行，按「负面且预警、按事件去重、按事件内条数排序」。
> 我的建议：保留 10 行、沿用历史口径。若客户明确不要 TOP10，关模板开关即可；`event_judge.top10` 文件仍要写（可从基座继承），**不要**登记成可省。
> 为什么需要你定：TOP10 是报告结构的一部分；模板级开关只决定这一次跑不跑，不决定提示词文件要不要存在。

**Q4 首页热点要不要 / 几条**

> 现状：首页热点是独立于月报的采集，代码硬校验恰好 30 条（`app/hotspot.py` 的常量 `ITEM_COUNT=30`）；历史四期月报没有这个段落。
> 我的建议：如果客户要首页热点，按 30 条走；如果要 20 条，需要改代码/配置并立项，不能只改提示词。
> 为什么需要你定：条数是代码契约，不是 prompt 文案；改错会直接 `hotspot_items_incomplete`。

**Q5 文风 / 章节称谓**

> 现状：S1~S4 都是公文分析体，章节用「一、」「（一）」，建议用「1.」；如果客户有其他报告使用「（一）」作一级或简报风，材料会互相矛盾。
> 我的建议：沿用历史体例；只有客户明确要求换体例时才改。
> 为什么需要你定：文风/称谓影响全篇，且一旦改就要同步 `style.application`、`format_reviewer.review`、`template_analyst.template` 三处，不能只改一条。

**Q6 季节条件预警允不允许**

> 现状：基座允许「无本地历史、仅季节机制」的预警（`historical_researcher.research` / `writer.outlook`）；历史报告里有「较去年同期」但没有逐条本地案例。
> 我的建议：允许季节条件预警，但要求标注「案例参考/季节条件」；如果客户要求每条都有本地历史，就要收紧并可能写不满 4 类。
> 为什么需要你定：这是证据标准与可写篇幅的取舍，材料里读不出客户的合规要求。

### 5.5 问法纪律

- **一次最多问 4 个**；按决策分组，不要按 34 个 key 逐条刷问。
- **每个问题三样齐全**：现状 / 我的建议 / 为什么需要你定。缺一样就是不合格的问题。
- **不许输出思考过程**：不写「我先分析一下」「我理解你的意思是」「接下来我将」；不解释你如何得出结论，只给结论和证据。
- **不许预告**：不写「我准备改哪几条」「稍后我会……」。用户没答完前，不动任何文件。
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
（28 条必写逐条 `key | 状态 | 依据`；状态 = 改写 / 沿用基座 / 仅说明（占位））
（6 条可省：`key | 可省 | 前提 + 证据`，与 NOT_USED.md 一致）

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
- **不写 = 继承基座**（`base`）。但「不写」现在是一条**判断结论**，不是默认动作：28 条必写都要判一次并登记依据（3.3、6.5）。两个现成包的实测：`packages/anshun_monthly/prompts/agent/` 目录存在但为空（34 条全部继承基座），`packages/demo_b/prompts/agent/` 有 10 个文件（10 条全覆盖）。
- `index.yaml` 四个顶层键必须齐：`agent_prompts` / `template_policy` / `report_prompt_profiles` / `default_prompt_profile`，缺一个就 `prompt_index_missing_keys:<键>`（`core/prompts/registry.py` 的 `_INDEX_KEYS` 与 `_bundle`）。
- 五个键是 **import 期硬依赖**（`core/agent.py` 在模块级取 `AGENT_PROMPTS[...]`）：`historical_researcher.plan`、`historical_researcher.research`、`writer.analysis`、`writer.outlook`、`template_analyst.template`。`index.yaml` 不声明它们，`import app` 直接 `KeyError: 'unknown_agent_prompt:<key>'`。
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

复核覆盖面（未覆盖时应当是 `34` 与 `[]`）：

```powershell
@'
from app import agent
print(len(agent.AGENT_PROMPTS))
p = agent.provenance()
print(sorted(k for k, v in p.items() if v == 'package'))
'@ | & $py -
```

### 6.5 四种状态的写法

- `改写`：包内有文件 + `index.yaml` 声明 + 依据 + 与基座差异。
- `沿用基座`：包内无文件；在 `接入记录.md` 的「提示词清单」里写一行 `key | 沿用基座 | 依据`；不要为了「看起来完整」复制一份基座正文（复制会制造第二份真相）。
- `仅说明（占位）`：包内有文件，正文只有 3.11.2 那三行说明；**只允许 `historical_researcher.*` 4 条且角色未声明时使用**；在 `接入记录.md` 写 `key | 仅说明（占位）| 条件`。别把它当选省事的选项（3.11.4 的后果）。
- `可省`：包内无文件；只允许 3.3 那 6 条；在 `NOT_USED.md` 写一行前提 + 证据；不要写进 `index.yaml` 的 `agent_prompts`。

> 五个硬依赖键（6.4）即使在 `可省` 情形下也必须声明并从基座继承——它们不是「文件可以缺席」的候选。

### 6.6 包内目录结构

```text
packages/<pkg>/prompts/
  index.yaml          # 34 个 key 全部声明；template_policy / report_prompt_profiles / default_prompt_profile
  roles.yaml          # 角色 id → {responsibility, boundary, output}
  agent/<key>.md      # 只放「改写」的 key；其余从基座继承
  NOT_USED.md         # 仅在确要省 3.3 那 6 条时创建；登记前提 + 证据
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

`exit 0` 且**无任何输出** = 声明合法；否则异常里带具体错误码（`manifest_unknown_agent:` / `manifest_agents_unverifiable:` / `manifest_missing_keys:` / `prompt_index_missing_keys:` …）。

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
| 图表清单 | `template.json` + `manifest.yaml` | `charts[]`（`id/family/style/binding/unit/scope/axis_label`）+ `charts.use`（与前者同集合） |
| 步骤声明 | `manifest.yaml` | `agents:` |
| 角色定义 | `prompts/roles.yaml` | `角色 id → {responsibility, boundary, output}`（恰好三键，多一个少一个都 `prompt_role_invalid:<id>`） |
| 提示词覆盖 | `prompts/agent/<key>.md` + `prompts/index.yaml` | 同名文件 + `agent_prompts` 里声明该 key |
| 提示词取舍 | `packages/<新包>/接入记录.md` | 「提示词清单」段：`key | 改写/沿用基座/仅说明（占位）| 依据` |
| 模板策略/画像 | `prompts/index.yaml` | `template_policy`、`report_prompt_profiles`、`default_prompt_profile` |
| 工具白名单 | `manifest.yaml` | `tools.allow` / `tools.phases` / `tools.budgets`；`capabilities.require`（产物 → 反推可达工具）；`features.<能力>.enabled`（能力开关） |
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
- 提示词：必写 28 条 → 改写 <n> / 沿用基座 <n> / 仅说明（占位）<n>；可省 <n> 条（见 `NOT_USED.md`）
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
  建议改：template_analyst.template（把「（已去重）」固定为 block 文本）
          或 writer.general（若该短语落在动态字段内）
  备注：任务示例里的 b5_amber 是模板字段 id，不是提示词 key；不要照抄成 prompt 名
```

注意：不要写「差 0.66%」这种把「条数相对差」和「占比百分点差」混在一起的数。要么写「条数差 12 条（相对 0.64%）」，要么写「占比差 0.07 个百分点」。

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

六条全绿、原始输出贴进 `接入记录.md`，才算建完。**建包之后先跑 10.2 的包归属四条**（新包可用、任务绑对包、产物落对根），再回来跑这六条。

**1. 基座提示词是否仍然客户无关**

```powershell
& $py scripts\gate_prompt_neutral.py
```

期望：`RESULT: PASS`，首行形如 `G-PROMPT-NEUTRAL  (34 files scanned, 37 terms: 5 static + 18 localities + 14 labels)`。括号里是 `5 + 地名去重数 + 类目名去重数`；现成两包实测 37。新包加进去后这个数字**必须变大**（你的地名/类目名进词表了）；判据仍是 `RESULT: PASS`。

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

期望：`exit 0` 且**无输出**。这一步会一次性跑完四个注册表的 configure，报错码直接指向包里的错处。

**4. 加包前后 `core/` 与 `app/` 逐字符不变**

```powershell
& $py -c "import sys;sys.path.insert(0,'scripts');import gate_core_iso as g;o=g.observe(g.REPO/'core',g.REPO/'app');print('CORE-FILES',o['core_files']);print('CORE-DEP',o['core_dep']['sites'],'sites /',o['core_dep']['files'],'files');print('CORE-HASH',o['core_hash']);print('APP-HASH',o['app_hash'])"
```

加包前跑一次、加包后再跑一次，**四行逐字符相同**。这条不依赖任何基线文件，只做纯观测（`scripts/gate_core_iso.py` 的 `observe`）。包在 `packages/` 下，`core/` 与 `app/` 一个字节都不该动。

**5. 最小冒烟（包契约三连）**

```powershell
& $py -m pytest tests\test_s7_package_contract.py -q
```

期望 `3 passed`。这三条用例遍历 `packages/*/`（不是手写清单），新包自动进入判据：①子进程 `import app` 能加载 ②提示词提到的已注册技能都已在 `manifest.skills.use` 声明 ③提示词文件字节口径（至多一个结尾 LF）。输出恒为 `3 passed`——每个用例内部对**所有**包逐个断言。

更完整的一轮用 `& $py -m pytest -q`（本机约 3–4 分钟）：新包加进去后**条数不变**——这些用例遍历 `packages/*/`，不会逐包展开成新用例；全绿即可。

**6. 覆盖可见性（改写的 key 才是 `package`）**

```powershell
@'
from app import agent
print(len(agent.AGENT_PROMPTS))
print(sorted(k for k, v in agent.provenance().items() if v == 'package'))
'@ | & $py -
```

期望：第一行 `34`；第二行恰好是「改写」的 key 集合，不多不少。没改写任何一条时第二行是 `[]`。注意 `provenance()` 只说明来源，不说明内容是否合适（6.4）。

### 10.1 门禁边界（改哪里会动哪个基线）

| 动作 | `docs/team/baseline/prompts-S5.json` | `docs/team/baseline/core-S10-*.json` | `gate_prompt_neutral` |
|---|---|---|---|
| 只写 `.conda/docs/` | 不动 | 不动 | 不动 |
| 改本手册 `.dsh/skills/onboard-client-package/SKILL.md`（旧位置 `core/prompts/base/接入新客户.md` 已删除） | **不动**（不在 `agent_prompts` 里） | **不动**（不在 `core/` 或 `app/` 下） | 不动（不扫 `base/*.md`） |
| 改 34 条中任意一条 | 会动，需重录 | 会动 | 基座改动会扫；包内覆盖不扫 |

三条依据：

- `scripts/gate_prompts.py` 不哈希文件，哈希的是四个数据对象：`BASELINE`（`prompts-S5.json`）与 `BUNDLE_KEYS = ("AGENT_PROMPTS", "AGENT_DEFINITIONS", "TEMPLATE_POLICY", "REPORT_PROMPT_PROFILES")`，由同一文件的 `bundle()` 组装。`AGENT_PROMPTS` 来自 `core/agent.py` 的 `_registry.prompts()`，只遍历 `index.yaml` 的 `agent_prompts`。改部署默认包（`REPORT_PACKAGE`）会改变 `AGENT_PROMPTS`，所以 `prompts-S5.json` 只对默认包 `anshun_monthly` 有意义，不能给新客户当基线。
- `scripts/gate_prompt_neutral.py` 的扫描面是 `core/prompts/base/agent/**/*.md`（34 条提示词正文），docstring 明写不扫 `core/prompts/base/*.md`：那些是对照表（接入说明已移出 core，见本手册）。
- `scripts/gate_core_iso.py` 的 `observe()` 用 `tree_hash(core_root, "*")` 把 `core/` 下所有文件（含 `.md`）算进 `CORE-HASH`。本手册原来就放在 `core/prompts/base/` 下，移出到 `.dsh/skills/` 后 `CORE-FILES` 少一个、`CORE-HASH` 必变，`--baseline docs/team/baseline/core-S10-J.json` 会 FAIL；那是预期行为，按团队当前的 core 基线规则处理，**不要随手录基线**。

### 10.2 包归属自检（建包之后、写提示词之前跑）

```powershell
# 1 新包在列表里且 usable:true（坏包会 usable:false 且带 error 原因）
(Invoke-RestMethod http://127.0.0.1:8765/api/packages) | Where-Object { $_.package -eq '<新包>' } | Format-List package,usable,error
```

四条判据，每条都要看到证据，看不到就别往下写提示词：

1. `GET /api/packages` → 新包在列表里且 **`usable: true`**；`usable:false` 时 `error` 就是原因（多半是 manifest / template / 提示词某一环坏了，跑 `check_package.py` 定位）。
2. 建一个任务 → `TaskState.package` 等于新包名（看 `GET /api/tasks/{task_id}` 的整份 state；`GET /api/tasks` 的 `metadata` 是白名单，看不到）。
3. 看产物落在 `data/packages/<新包>/`（`artifacts/` / `uploads/`），**不是**默认包根。
4. 若请求没带 `X-Report-Package`：去默认包根看有没有多出来的任务或文件——这是最常见的静默错误（1.5.4 ①）。

## 十一、交接与定稿

### 11.1 人工改什么

- **措辞**：像不像客户/公文、判断强度、归因方式、称谓。
- **结构**：章节要不要、段落顺序、建议条数、TOP10 要不要。
- **取舍**：哪些差异可以接受、哪些必须改、哪些是本轮不修的已知问题。
- **定稿签字**：只有人能宣布「这版可以」。

agent 不改人已经确认的模板字段、固定文字、TOP10 梗概；需要改这些时，写进对比报告的「必须改/建议改」，由人决定。

### 11.2 定稿检查清单

- [ ] 需求集清单齐全：28 条必写全部有归属（改写 / 沿用基座 / 仅说明（占位）），6 条可省全部登记或全要。
- [ ] `NOT_USED.md` 存在（或确认不需要）；每条可省都有前提 + 证据；**里面没有 6 条之外的 key**。
- [ ] 每条「必写」都有：键 / 状态 / 正文 / 依据 / 与基座差异；依据不为空。
- [ ] 每条「沿用基座」都有一句依据；没有为了凑数复制基座正文。
- [ ] 「仅说明（占位）」只出现在 `historical_researcher.*` 的未声明角色场景，没有扩散到 `writer.*` 或其它键。
- [ ] prompt 正文没有客户特有事实（地名、类目、数字、期号、日期、事件标题、示例原句）。
- [ ] 字节口径：UTF-8 无 BOM、`\n`、正文 + 恰好一个结尾 LF。
- [ ] `index.yaml` 的 `agent_prompts` 覆盖 34 个 key；五个硬依赖键都在。
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
from app import agent
print(len(agent.AGENT_PROMPTS))
print(sorted(k for k, v in agent.provenance().items() if v == 'package'))
'@ | & $py -

# 4 基座提示词仍然客户无关（只扫 base/agent，不扫包内）
& $py scripts\gate_prompt_neutral.py

# 5 包契约三连（遍历 packages/*/）
& $py -m pytest tests\test_s7_package_contract.py -q
```

判据：

- 1 的 `PROMPTS` 段是 `34 keys: N base + M overrides`，`M` 等于你改写的条数；末行 `PKG-OK`。
- 2 `exit 0` 且无输出。
- 3 第一行 `34`；第二行是改写 key 的集合，不多不少。
- 4 `RESULT: PASS`；括号里的词数会随包增加，判据是 PASS。
- 5 `3 passed`。

## 十二、常见错误清单

| 现象 | 原因 | 修法 |
|---|---|---|
| 以为关了属地/分类/去重，模型仍能调对应工具 | `features` 开关写成 `enable: false`。判定是 `config.get("enabled") is False`（`core/tools/registry.py` 的 `resolve_tools`），键名写错 = 不生效，**不报错** | 统一写 `enabled:` |
| `prompt_index_missing_keys:template_policy`（或 `agent_prompts` / `report_prompt_profiles` / `default_prompt_profile`） | `index.yaml` 缺四个顶层键之一（`core/prompts/registry.py` 的 `_INDEX_KEYS`）。注意这是**顶层键**错，不是某条提示词缺项 | 补顶层键；`template_policy` 可以写 `{}`（demo_b 如此） |
| `prompt_missing:<key>` | `index.yaml` 声明了该 key，但包内与基座都没有对应 `.md`（`core/prompts/registry.py` 的 `_resolve`） | 补文件，或从 `agent_prompts` 删掉该行（后者仅当没有代码调用它） |
| `KeyError: 'unknown_agent_prompt:<key>'` | 代码要用的键没在 `agent_prompts` 里声明；五个 import 期硬依赖键尤其致命（`core/agent.py` 模块级 `AGENT_PROMPTS[...]`） | 照 A 包的 34 行声明补齐 |
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

## 附录 A：证据索引（排障时按图索骥）

**列口径：文件 + 函数/符号，不写行号**（理由见 4.1 引用纪律）。找不到函数名时按符号字面量搜。

| 主题 | 文件 · 函数/符号 |
|---|---|
| 34 条声明顺序 | `packages/anshun_monthly/prompts/index.yaml` 的 `agent_prompts` |
| 分层查找 / 来源 | `core/prompts/registry.py` 的 `prompts()` / `_resolve` |
| 字节口径 | `core/prompts/registry.py` 的 `_text`（UTF-8 无 BOM、`\n`、恰好一个结尾 LF） |
| 四个数据对象 | `core/agent.py` 的 `AGENT_PROMPTS` / `AGENT_DEFINITIONS` / `TEMPLATE_POLICY` / `REPORT_PROMPT_PROFILES` |
| 五个硬依赖键 | `core/agent.py` 顶部的 `AGENT_PROMPTS[...]` 模块级取值 |
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
| 模板修审旁路 | `app/template_advice.py`（`template_analyst.advice`）；`app/template_advice_api.py` |
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
from app import agent
print(len(agent.AGENT_PROMPTS))
print(sorted(k for k, v in agent.provenance().items() if v == 'package'))
'@ | & $py -
```

完成判据：三条命令都能跑；输出与本文的实测数字一致（不一致时以你的实际包为准，并把差异写进对比报告）。
