# Agent提示词的统一维护入口

所有角色定义、模型系统输出指令、静态任务指令、Writer各部分提示词和模板制定政策集中在 **`app/agent.py`**。执行模块通过 `get_prompt()` 引用，不再自行保存长提示词。

| 需要修改的内容 | agent.py中的入口 |
|---|---|
| 角色职责、边界与输出定位 | `AGENT_DEFINITIONS` |
| 第二部分研判分析 | `ANALYSIS_PROMPT` / `writer.analysis` |
| 第二部分工作建议 | `OUTLOOK_PROMPT` / `writer.outlook` |
| 历史检索与阅读要求 | `RESEARCH_PROMPT` / `historical_researcher.research` |
| 先用模型知识比较至少4类候选 | `RISK_COMPARISON_PROMPT` / `historical_researcher.plan` |
| 一般按字段写作 | `writer.general` |
| 数据计算计划 | `writer.data_planner` |
| 旧版单槽写作及主题/标题/概述 | `writer.slot.*` |
| 事件关系、TOP10再去重、分类、15—35字梗概 | `event_judge.*`、`event_classifier.classify`、`event_summarizer.summary` |
| 模板语义制定、图形要求、三轮纠正 | `TEMPLATE_INSTRUCTION`、`TEMPLATE_POLICY`、`template_analyst.*` |
| 工具预算结束后的总结要求、JSON输出要求 | `model.*` |

## 不同报告采用不同Writer要求

在同一文件的 `REPORT_PROMPT_PROFILES` 中增加报告配置，只覆盖差异项。例如以下为维护方式示例，不是已经启用的报告配置：

```python
REPORT_PROMPT_PROFILES = {
    'anshun_monthly': {},
    'another_monthly': {
        'writer.analysis': '这份报告研判分析的完整写作要求……',
        'writer.outlook': '这份报告工作建议的完整写作要求……',
        'writer.general': '这份报告其他文字字段的写作要求……',
    },
}
```

任务的 `metadata.writer_prompt_profile` 可以选择配置；其次读取确认模板的 `metadata.writer_prompt_profile`，未指定时使用同文件的 `DEFAULT_PROMPT_PROFILE`（当前为 `anshun_monthly`）。默认值也在此文件维护，修改后重启服务。当前没有新增页面上的配置选择器，不需要为这次整理重新确认模板或本期数据。

未覆盖的键继承默认提示词，配置名拼错会明确报错。当前编排已经在一般Writer、研判分析、工作建议、数据计划、旧版单槽写作和研究角色调用中实际读取配置，不是只增加一份未使用的说明。

程序记录所用配置与提示词指纹。完成一次新版写作后，后续修改配置或提示词会使相应机器文字缓存失效，避免继续复用旧稿；已人工修订文字始终保留，不回模型重新研判。旧任务首次兼容时保留既有机器稿，第二部分仍采用已有政策版本失效机制。

目前缓存已按字段依赖区分：工作建议依赖writer.outlook及研究提示词，研判分析依赖writer.analysis，一般字段依赖writer.general，修改建议不会连带重写第一部分。

## 文件分工

- `agent.py`：可维护的提示词和报告差异配置。
- `structured_writer.py` / `slot_writer.py`：选槽、供证、调用工具、纠错、保存正文。
- `section_two.py`：数据结构、来源/日期/地域/字数/条数等程序校验。
- `historical_research.py`：搜索阅读编排、证据缓存、重试和保存。
- `tool.py`、各工具实现：工具参数和接口描述。

模板中按字段确认的写作规则仍作为该模板的数据传给Writer；实际校验错误、原文和冻结事实是运行上下文，不移成静态提示词。只改措辞可集中修改 `agent.py`；如果新报告要改变JSON结构、字数硬上限、数据口径或地域，还需同步相应Schema/工具定义，不能靠一句提示词绕过程序校验。

本次只集中现有提示词，4段长政策及19条原有补充指令逐字一致。未采用“模型记忆替代检索”，未缩短或扩大历史范围，未新增模型请求。

验证：79项回归通过（206.77秒），其中新增测试检查提示词集中、不同报告配置的真实Writer路由、同配置缓存复用、配置变更时人工正文保留。8765服务已加载新代码，原真实任务修订号/冻结事实/草稿引用保持；没有重跑报告。接口检查记录在 `data/prompt-registry-verification-20261108.json`。


## 双审核扩展（2026-11-08）

格式、内容审核与Writer退修已实际接入写作图，提示词仍在agent.py：format_reviewer.review、content_reviewer.review、writer.revise、style.application。不同报告可按原有profile机制覆盖。lieflat-less-ai-tone作为固定版本的外部规则包保留原文；项目如何应用该skill由style.application维护。详见[真实图与双审核验证](真实LangGraph双审核与去AI表达-20261108.md)。
