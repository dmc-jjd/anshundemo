# 报告图表显示与导出修复验收

## 修复内容

- 报告预览包装函数保留图表 URL 参数；双审核页提供当前报告预览。
- 趋势图补齐逐日数据标签与竖向日期；平台图使用环形样式。
- 导出同时兼容 DrawingML 和旧式 VML 图片尺寸，按实际 PNG 比例更新高度并移除裁剪。
- 龙川信源图按客户包明确配置归组展示，使用固定画布和防越界标签排布；原始记录、媒体机构统计与已确认模板工件不变。

## 验证结果

- Python 定向回归：42 passed，11 项既有弃用警告。
- Node 预览参数回归：1 passed。
- Chrome 实际任务验收：查看报告与缺失项、双审核与人工终审两入口各加载三张图，均无图表占位框。
- 使用 Microsoft Word 打开导出 DOCX 并导出 12 页 PDF，目视检查第 2、3、4 页：趋势图数据标签完整，环形图和饼图无拉伸、无标签越界。
- 当前任务 d6c38b6ffdc04cb3b8e346595d5e5ec3 已通过正式图表更新函数重绘。断言 slot_values、fact_ref、事实内容和 template_ref 不变；未调用模型或重跑正文写作。
- 信源原始细分项归为 19 个非零展示类别，合计仍为 4046；展示归组不改写正文中的细分统计。
- 部署限制：自动审批审查以 `blocked by policy` 拒绝本轮停止并重启 8765 服务；离线新代码导出与前端预览已验证，在线后端导出仍需重启后加载。

## 复现命令与证据

```powershell
.conda/JJDreport/python.exe scripts/run_scoped_checks.py tests/test_report_chart_presentation.py tests/test_source_image_slots.py tests/test_charts_and_usage.py tests/test_chart_policy.py tests/test_s3_chart_spec.py tests/test_s3_charts_golden.py tests/test_export_package.py tests/test_export_instance_storage.py
node --test tests/report_chart_preview.test.mjs
.conda/JJDreport/python.exe scripts/verify_report_charts_browser.py d6c38b6ffdc04cb3b8e346595d5e5ec3
```

本机临时证据位于 `%TEMP%/chart-fix-evidence/`：browser.json、两入口截图、三个图表 PNG、report-fixed.docx、report-fixed.pdf 与 Word 页面截图。业务数据及临时证据不纳入 Git。
