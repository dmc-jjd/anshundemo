# 剩余优化收尾记录

2026-11-18；分支 codex/report-optimization-20261118。保留原工作树，不提交、不推送、不发布。此记录更新早先《实施报告》的后续事项与浏览器/依赖状态，历史结果不重写为新结果。

## 已完成

- Settings、应用工厂与请求上下文服务：导入不建数据目录；两实例数据、上传、线程池与后台任务隔离；兼容旧根及 app.main:app、52条路由、OpenAPI、main测试注入。模型凭据与客户包注册表仍是部署配置。
- 模板按包读取，报告选择及管理列表切包刷新并拒绝过期响应；健康 confirmed 模板保留可选，缺失/损坏行仍可管理但禁预览；直接访问错误返回409及清晰文案。
- 旧slot草稿导出贯穿实例Store，图表从传入存储读取。
- 68包完整哈希锁。全新 Windows x64 Python3.13 venv 从wheelhouse离线安装、pip check、真实Uvicorn factory启动成功；精确命令见README。
- 真实Chrome连接完整应用，使用临时合成数据，验证切包、缺/坏工件、慢响应竞态、人工补写及刷新恢复。截图与结果在browser目录。
- 星桥浏览器回归：已有会话中单选后进入KN·Aistudio，链接、材料及提示词进入待发送框，未自动发送。该验证使用隔离演示API，不能算真实内部数据接口验收。

8765已重启加载最新代码（PID39556），首页、status、tasks及两个最新JS脚本HTTP检查通过；证据restart-smoke.json。

## 验证

最终定向批次 **234 passed，0 failed，0 errors，0 skipped**（v5-scoped-hsb5mlv5），包含原交接节点、S6、S10、两包隔离、并发持久化、写作和新增修复；独立新环境19通过，终审修复批73通过。日志在 runs 目录；批次有重叠，不能相加冒充唯一覆盖。Node星桥4项通过；真实浏览器结果见 browser/result.json 与相邻星桥验收目录。

新环境：clean-install.json、clean-install.log、clean-pip-check.log、clean-startup.log、clean-uvicorn.log。离线包为 `.tmp/optimization-dependencies-win-py313.zip`，包含固定jieba构建wheel；换机需随锁文件保留包。其他OS/Python版本未验证。

性能：remaining-measurements.json，30次样本、两个合成包、100模板。目标包50模板列表中位51.219/P95 94.241ms；原全包100模板路径97.192/471.082ms。减少不相关包工作量，不宣称同规模普遍提速。热包加载1.219/2.216ms，未据此加TTL或更改分页。

## 仍需单独验收的边界

1. S5原有两项历史门禁仍红：test_prompts_match_baseline、test_gate_rejects_corrupted_bundle。AGENT_PROMPTS观察232c1bf7…、旧期望0eb8838f…；全bundle观察0b993fe7…、旧期望4132ccd2…。与交接记录一致。保留原基线、断言与客户提示词；新增4类当前bundle损坏探针通过，不能替代历史基线匹配。parity的指纹/审核策略测试通过不等于这两项消红。
2. BackgroundTasks仍不是跨重启任务队列；SQLite与工件文件不是跨介质原子事务。完整队列/outbox及全工具JSON Schema重写不是本计划承诺。
3. 未调用付费模型、未接真实内部热点接口、未运行客户正式出稿，未验证Word视觉版式或生产负载。正式业务验收继续由用户进行。

本次计划内剩余工程项已落实；上述边界保留为明确限制，不计入自动通过。
