# 缺失数据字段的通用计算与包绑定

用户已授权补齐龙川 V3 的 12 个缺失字段；保持确认工件不变，业务测试由用户执行。媒体范围/身份去重、呈发固定内容已按用户回复落实。

设计：基座新增 peak_count、source_statistics、filtered_record_count、distinct_source_count、selected_material_count、parameterized_table；媒体属性/级别与字段 id 仅出现在客户包。政务选题按配置筛选后以相同标题归组计数，并向 Writer 提供选题与计数上下文，校验绑定标题一致。不能把模糊相似标题当同一事件。

1. `tests/test_extended_calculations.py`：构造合成冻结数据，验证峰值、信源排序、媒体筛选和唯一身份、政务同标题计数、日期表格、参数错误/缺值、包绑定链路，先运行观察失败。
2. `core/frozen_report.py`：扩充 Calculation 参数和组合校验、目录、统一执行分派；`core/calculation_extensions.py` 保存通用实现，禁止客户专名、固定数据、客户字段 id。
3. `packages/longchuan_yuebao/calculations.yaml`：仅补 12 个字段配置；复杂业务口径由用户确认。模板固定内容沿用须有用户同意，不能默默引用历史名单。
4. 写作载荷提供程序选出的标题/计数依据；仅在包声明需要时验证标题与计数一致，不改变其它客户报告写作行为。核查确认阶段新参数与写作工具 schema 可达。
5. 跑定向离线回归，验证旧计算、确认工具箱、返回 schema 和来源引用；用本机确认模板只读校验 12 个绑定与类型，不创建真实报告或调用付费模型。
6. 更新接入记录和缺口状态；重启 8765 并验证服务。已确认工件/hash 保持不变；缺必要本期输入时明确报缺失，不默认为 0 或沿用历史日期。

实施记录：1～5 已完成，主回归 115 passed；实际 V3 schema 的 12 项合成计算通过，V2/V3 确认工件哈希与原始基准一致。人工改日期路径补客户包解析，标题人工纠正也执行计数一致性检查。交接文档及 skill 已更新；最终服务检查见 docs/verification/2026-11-18-calculation-tools/README.md。
