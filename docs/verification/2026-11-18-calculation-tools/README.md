# 12 个缺失字段计算与绑定验收

目标：longchuan_yuebao / 龙川县舆情月报V3；2026-11-18。状态：技术验证通过，业务验收由用户执行。

6 个通用 metric 覆盖 12 个字段，配置见 packages/longchuan_yuebao/calculations.yaml。基座保存可复用算法，包内保存客户筛选、固定行和字段关联。有效绑定配置 35/35，新增 12 项使用合成冻结记录通过实际确认模板 schema 校验；原有 23 项并非本期业务取值验收。

## 物证

- audit.py：SQLite mode=ro，只读取确认工件并核对 SHA256；不创建 Store、不修改模板、任务或报告。计算仅使用 tests/test_extended_calculations.py 的合成数据。
- audit.json：12 项实际 schema 取值、35 项绑定配置计数、V2/V3 确认工件哈希。V3 ca19317b6428a92e3b5e3837b4e04fb7a2be3cdfd69e759e12448e6c22d88540；V2 e053b1277d8e9d4e48308b6ea3e5e17b99b913c13b9886db12486ade51d35f7b；均与原记录一致。
- 主回归：run_scoped_checks.py 指定 test_extended_calculations、test_frozen_writer、test_writing_pipeline、test_report_package_regressions、test_section_two，115 passed。日志保存在 regression.log / regression-run.json。
- 验证包含：媒体筛选/去重/身份缺失、峰值、信源、参数表格、同题传播数、选题一致性、旧 tool/path 不进入规划器、人工更改参数仍读取客户包绑定。
- skill 通过 quick_validate.py；references/tool-extension-handoff.md 提供可独立接手的缺口方案模板。
- 兼容检查：test_template_bindings_catalog、test_review_excerpt、test_s7_package_contract、test_structured_template，25 passed；日志 compatibility.log / compatibility-run.json。两批共 140 passed（有既有弃用告警）。
- 服务已加载当前代码并重启：PID 36908，8765 首页 HTTP 200；V3 定义接口仍返回原确认 ref、revision 19、53 字段。物证 service-check.json。

## 限制与输入要求

每次任务提供本期 publication_date 及已有字段要求的 issue_number；源记录需要日期、media_level、media_attribute、source_id 或可辨识的 source+author。缺输入显式列为写作问题。政务按完全相同标题归组，信源最多 20 项，这两项实现口径需用户业务验收。未调用付费模型、未生成业务报告；不将技术测试等同报告业务质量验收。

工具实现与建包回接须核对实际代码、目录可达性、参数/结果类型、测试物证和生效绑定；既有确认工件保持原样。
