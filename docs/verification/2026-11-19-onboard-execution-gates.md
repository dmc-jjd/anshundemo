# 建包skill执行闭环更新验证

## 观察基线

本次实际建包聊天中已发生：agent记录了分类数量、可选第五段等问题并添加待处理提示，但没有及时集中提问、落实决定；只保存四组案例关联便误以为覆盖充分；字段候选混列被误认成实际关联；一次服务命令被拒后未重新核实便反复报告持续限制。

只读skill压力复核定位到一处可误读路径：旧template-refinement允许“不支持时保持待处理”，随后交接话术又可带“未处理项”邀请确认。此基线来自实际聊天和文档，不伪称进行了无skill盲测。

## 修改

- 主入口增加阶段2必读执行闭环与确认前检查命令。
- 明确直接修复、集中提问、开发交接、有依据不采纳四个分支；每个开放问题有具体下一动作，部分回答不阻止独立已授权工作。
- 新增历史结构、列表、可选章节、绑定、关联、实际请求、预览导出、共享兼容八类覆盖证据。
- 同步结构编辑、处理状态、用户答案、可选段省略与动态类别校验等当前机制；清理旧的“未处理项已列出即可请用户确认”话术。
- 新增只读check_review_gate.py，核对任务/候选/草稿身份、四项选择、绑定状态、全部当前意见和额外发现、证据与覆盖项；--require-ready未通过时退出2。

## 验证结果

- 新增回归在脚本不存在时先失败；实现后tests/test_onboard_review_gate.py为6 passed。
- 覆盖：API已处理不能掩盖额外待问事项；版本过期/证据缺失/缺覆盖/缺绑定拒绝；已确认模板不能按候选修改；未回答业务问题拒绝；CLI只调用GET且就绪/未就绪退出码分别为0/2。
- writing-skills要求的只读agent复测：重复意见合并提问、复用已决事项、部分回答分别推进、额外历史缺口、过期版本、HTTP200但结构未变、未勾选候选混列、临时拒绝与正式服务加载等场景均给出正确下一动作，未发现剩余阻断性文档冲突。
- skill-creator quick_validate通过（Windows使用Python -X utf8读取中文）；所有本地Markdown链接目标存在；git diff --check通过。
- 实际服务只读检查发现乳源任务已由用户确认，脚本正确拒绝把它当作可编辑候选；本轮未修改任何客户模板、确认状态、提示词或业务报告，未调用业务模型。

## 复现

```powershell
.conda/JJDreport/python.exe scripts/run_scoped_checks.py tests/test_onboard_review_gate.py
.conda/JJDreport/python.exe -X utf8 C:/Users/knwl/.codex/skills/.system/skill-creator/scripts/quick_validate.py .dsh/skills/onboard-client-package
```

检查脚本不是服务端确认按钮的硬锁。它能验证所记录的状态、当前版本和证据文件存在，不能识别伪造证据或agent完全漏记的差异；逐节阅读历史与用户业务审阅仍不可省略。不承诺仅靠skill文字即可杜绝所有漏执行。
