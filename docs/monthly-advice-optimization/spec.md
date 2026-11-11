# 月度工作建议 4—5 条稳定生成优化规格

状态：待用户批准；本规格仅定义分析与实施方案，尚未修改业务代码。

## 1. 背景与已确认事实

目标任务：`d2511637eb694125a92616d2a276bd08`。

历史研究产物 `historical_research-1b4ab910e7855f93ccd6` 的状态为 `ready`，已经有交通管理、自然灾害、安全生产、社会治安 4 类合格选题，全部为 `seasonal`。因此本次不是“没有搜集到工作建议依据”。

Writer 在 block 42 连续三轮失败：

| 轮次 | 原始返回 | 允许值 | 直接结果 |
|---|---|---|---|
| 1 | 安全生产引用 `[5,18,20]`；自然灾害引用 `[13,22]`；社会治安引用 `[15,51]` | 安全生产仅 `[14]`；自然灾害仅 `[13]`；社会治安仅 `[15]` | 引用了其他选题或后续工具资料，触发“前瞻类别和历史来源未对应” |
| 2 | 四类引用分别为 `[12]、[14]、[13]、[15]`，均正确；未显式返回 `basis_type` | 四类均为 `seasonal` | Schema 默认填入 `historical`，触发“依据性质未对应选题” |
| 3 | 交通管理、自然灾害、社会治安正确；安全生产引用 `[19,20]` | 安全生产仅 `[14]` | 3 条合格仍被整组丢弃；`[19,20]` 是 Writer 后续查询得到的全局已登记资料，不是该研究选题的登记依据 |

`SourceCatalog` 已正确完成数字到真实来源的绑定；本次不是数字编号解码错误。问题发生在绑定后的“选题—来源”语义校验。

当前放大机制：

1. `render_outlook()` 在循环中遇到任一错误立即抛异常，无法保留同组其他合格条目。
2. `structured_writer.py` 仅在 `SourceBindingError` 时保存 `candidate`；上述校验异常不会保存已经生成的正文。
3. 三轮后整个 `monthly_recommendations` 进入 `writer_unfilled`。
4. `DraftVersion.mark_missing()` 只要看到 `recommendations=[]` 就设置 `missing_recommendation_evidence=true`，把写作/校验失败误标为“证据不足”。

## 2. 目标与边界

### 目标

- 最终交付口径统一为 4—5 条月度工作建议。
- 研究阶段目标形成 5 类合格选题，最低 4 类才允许进入自动写作，为单条退修留出余量。
- 证据不足时按等级放宽“依据类型”，不放宽事实真实性。
- 单条失败只退修该条，不再清空其他合格条目。
- 页面明确区分研究不足、引用待核对、正文校验未完成和正文未生成。
- 自动流程确实无法形成 4 条时，保留全部合格条目与失败条目，转人工补全；任务不得带着空白建议静默完成。

### 底线

- 不得为凑数编造本地案例、数量、同比、概率、活动日期或“历史高发”结论。
- 不得把全局已登记但未经该选题核对的引用自动挂到该选题下。
- 不得把模型季节知识写成本地已发生事实。
- “必须 4—5 条”是最终交付要求，不是允许模型伪造第 4 条；自动不足时由人工兜底完成。

### 非目标

- 本次不修改此前讨论的格式审核、内容审核图结构。
- 本次不恢复无限制联网或十年历史普查。

## 3. 统一业务口径

1. 候选比较：5—8 类，优先形成 5 类合格选题。
2. 研究就绪：至少 4 类合格选题才为 `ready`。
3. Writer 输出：4—5 类，类别不得重复，且必须来自合格选题。
4. 自动退修后仍不足 4 类：保存部分结果和逐项错误，进入人工补全，不宣称自动生成成功。

## 4. 分级证据策略

按以下顺序补足选题，每一类记录实际使用的证据等级：

1. **A 级：本地历史依据**。近 3 年优先，必要时扩至 5 年；单案只称案例参考，跨年才称复现，官方明确说明才称高发。
2. **B 级：官方季节资料或已核实地方活动**。不要求发表于历史同月，但必须说明与未来窗口的关系；具体活动必须核实。
3. **C 级：明确标注的模型季节机制**。允许全部选题使用条件性季节推演；采用“若出现……可能……”表述，不附虚构本地事实。

只有 A/B 不足时才使用 C 级补足到目标数量。放宽的是可接受的依据类型，不是引用、措辞和真实性校验。

## 5. 具体实施设计

### 5.1 统一 4—5 条规则和研究门槛

涉及文件：

- `app/section_two.py`
  - `CandidateComparison.candidates` 改为 `min_length=5, max_length=8`。
  - `validate_history()` 的合格类别门槛由 3 改为 4，错误文案同步修改。
  - `render_outlook()` 的条数改为 4—5。
- `app/historical_research.py`
  - 三轮研究的提前成功条件由至少 3 类改为至少 4 类。
  - 季节候选兜底在不足 4 类时启动，目标补足到 5 类；不新增模型调用、不虚构历史引用。
  - `status='ready'` 的门槛同步改为至少 4 类。
- `app/structured_writer.py`
  - `StructuredAnswers.outlook_items` 改为 `min_length=4, max_length=5`。
  - Writer 必填提示和候选正文预览条数同步改为 4—5。
- `app/source_binding.py`
  - `NumberedAnswers.outlook_items` 同步改为 4—5；其余数字绑定协议不变。
- `app/agent.py`
  - 研究提示词、Writer 提示词、`writer.outlook_field` 和 `TEMPLATE_POLICY['recommendations']` 全部统一为“比较 5—8 类、目标 5 类合格选题、输出 4—5 条”。
- `app/template_review.py`
  - 默认字段显示名称和执行说明统一为 4—5 条。

### 5.2 消除 `basis_type` 默认值误伤

涉及文件：`app/section_two.py`、`app/structured_writer.py`、`app/agent.py`。

- `category` 仍由模型从合格选题中选择。
- `basis_type` 是研究产物已经确定的元数据，不再依赖模型抄写；程序按 `category` 找到选题后覆盖/补齐 `item.basis_type`。
- 正文仍按该选题真实的 `basis_type` 接受高发、复现、季节条件等措辞校验，避免通过改元数据绕过内容审核。
- 提示词改为“选择类别，依据性质由程序继承”，避免继续要求模型重复填写确定性字段。

本次第 2 轮在采用该设计后可直接通过，不再因缺省值变成 `historical`。

### 5.3 单条校验、锁定合格项、只退修失败项

涉及文件：`app/section_two.py`、`app/structured_writer.py`。

- 从 `render_outlook()` 抽取单条校验/渲染 helper，例如 `render_outlook_item(item, topics, window)`；保留 `render_outlook()` 作为整组 4—5 条最终入口。
- 每轮 Writer 返回后按 `category` 逐条校验，形成：
  - `valid_items`：正文、引用及措辞均合格；
  - `invalid_items`：保留原始正文，并记录条目序号、类别、错误码、错误信息和该类别允许的引用。
- 已合格条目在后续轮次锁定，不被模型改写；后续返回只用于补齐或替换失败类别。
- 纠错 payload 只描述失败条目，明确给出该类别允许的数字资料编号，不再只返回整组一句“未对应”。
- Writer 后续工具查询得到的新资料不能自动加入原选题。若正文依赖这些新事实，纠错时必须改用该选题已登记依据并删除无支持事实；如确需新增依据，应重新进入研究核对，不在 Writer 中自动放宽。
- 任一轮达到 4—5 条合格即保存整个字段。

本次第 1、3 轮的安全生产条目会单独退修，其他合格条目不再被清空。

### 5.4 保留候选正文和逐项状态

涉及文件：`app/structured_writer.py`。

- 每次成功解析出 `outlook_items` 后立即保存候选，不限于 `SourceBindingError`。
- 三轮后仍不足 4 条时：
  - 合格条目单独保存；
  - 失败条目的正文、审计字段和逐项错误保存到 `writer_pending_sources` 工件；
  - 有人工可核对正文时使用 `writer_source_pending`（纯引用问题）或 `writer_validation_pending`（其他校验问题）；
  - 只有完全没有可用正文时才使用 `writer_unfilled`。
- 部分结果不得被包装成“已自动完成 4—5 条”；人工补全至少 4 条后才允许最终完成。

### 5.5 修正“证据不足”误标

涉及文件：`app/schemas.py`、`app/structured_writer.py`、`app/report_validation.py`。

- 不再由 `recommendations=[]` 自动推断 `missing_recommendation_evidence=true`。
- 在生成草稿时根据实际 issue 显式设置：只有 `historical_evidence_insufficient` 才标记为证据不足。
- Writer 引用或正文校验失败保留为空建议列表时，页面展示真实 `writer_issues`，不得显示为研究证据不足。
- `report_validation.py` 按实际状态分别提示“研究依据不足”或“建议写作/校验未完成，转人工”。

## 6. 验证方案

### 自动化回归

更新 `tests/test_section_two.py`、`tests/test_seasonal_review_fallback.py`，并在现有结构化 Writer 测试中增加以下场景：

1. 4 条和 5 条均可通过，3 条和 6 条均被拒绝。
2. 无本地历史网页时可用季节机制补足到至少 4 类，目标 5 类，且无新增虚构引用。
3. 模型省略 `basis_type` 时程序继承 `seasonal`，正文校验仍生效。
4. 使用全局已登记但不属于该类别的编号时，仅该条失败，错误包含类别和允许编号。
5. 同组 3 条合格、1 条失败时，3 条被锁定，只退修失败条。
6. 最终仍不足 4 条时保留候选正文与逐项错误，不再整节空白，不误标证据不足。
7. 交叉类别引用、编造数字、虚构高发、重复类别仍必须拒绝。
8. 自动流程不足 4 条时不得直接进入最终完成状态。

### 本次任务回放

使用三份现有交换工件作为固定输入：

- `model_exchange-f99ce0c4d4c33f87688b`
- `model_exchange-5c31307cb95b9732fd35`
- `model_exchange-ab56a2481bdb93453bd8`

验收结果：

- 第 2 轮缺失 `basis_type` 不再造成失败。
- 第 1、3 轮仅错误类别进入退修，其他条目保留。
- 若最终安全生产仍不合格，页面至少保留其他合格项和安全生产候选正文，并显示具体引用错误。
- `missing_recommendation_evidence` 不再被误设为 `true`。

### 建议执行命令

```powershell
python -m pytest tests/test_section_two.py tests/test_seasonal_review_fallback.py tests/test_frozen_writer.py -q
python -m pytest tests/test_pause_and_polling.py -q
```

完成代码后还需运行完整 `python -m pytest -q`，确认无其他写作链路回归。

## 7. 实施顺序与批准点

1. 统一 4—5 条口径与分级补足规则。
2. 程序继承 `basis_type`，实现单条校验、锁定和退修。
3. 保存部分结果并修正页面错误分类。
4. 增加回归测试并回放本次三轮输出。

以上全部通过后才更新任务策略版本并用于新任务。现有历史草稿不自动改写；需要时由用户重新生成对应任务。

本规格需用户明确批准后才能修改业务代码。
