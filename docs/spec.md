# 任务轮询修复与可恢复暂停规格

## 目标

修复任务记录页反复出现“操作未完成，请稍后重试”，精简任务列表响应；为所有未结束任务提供暂停/继续操作，暂停后冻结计时且不再发起新的模型请求。部署时暂停所有创建超过 2 小时且未结束的任务。

## 已确认根因

- `app/main.py::templates` 直接读取每个 `confirmed_template_ref`，历史任务引用不存在的旧路径工件时抛出 `FileNotFoundError`，导致 `GET /api/templates` 500。
- `app/static/app.js::refresh` 每 7 秒执行任务刷新并重复调用 `loadTemplates`，统一错误提示因此反复出现。
- `GET /api/tasks` 返回完整任务快照，包含大型 `metadata`，当前约 4.3 MB；列表实际只需要 ID、类型、阶段、修订号、创建时间和模拟标记。

## 后端改动

### 模板与任务列表

- `app/main.py::templates`：每个工件只读取一次；单项捕获 `KeyError`、`FileNotFoundError`、`ValueError`、`OSError` 并跳过，不影响其他模板。
- `app/main.py::tasks`：返回列表摘要，仅含 `id/kind/phase/revision/created_at` 和 `metadata.simulation`；单任务详情接口保持完整数据。
- `app/static/app.js::refresh`：移除每次轮询中的 `loadTemplates()`；模板仍在初始化及进入报告处理页时加载。

### 暂停状态与并发保护

- `app/main.py` 新增 `POST /api/tasks/{task_id}/pause`：终态（`approved/cancelled/template_confirmed`）返回 409；已暂停幂等返回；否则在 `metadata.paused_from_phase` 保存原阶段、`metadata.paused_at` 保存时间，将 `phase` 设为 `paused`，写入 `task_paused` 事件。
- `app/storage.py::Store.put_task` 新增 `allow_resume=False`：数据库前态为 `paused` 且调用方未明确恢复时，保留 `phase=paused` 及暂停元数据，防止后台旧状态写入覆盖暂停；版本冲突检查保持不变。
- `app/main.py::resume`：仅暂停恢复使用 `allow_resume=True`。恢复 `paused_from_phase` 并清除暂停元数据；模板活动阶段重新排队执行模板图，报告数据活动阶段重新排队执行报告图，写作活动阶段按 `writing_review_run.review_only` 重启相应写作流程；人工等待阶段只恢复原阶段，不重复启动后台任务。
- `app/model_client.py` 新增 `TaskPaused(BaseException)`，避免被现有 `except Exception` 吞掉。`invoke_agent` 在每次模拟适配器调用及每次真实请求/重试前检查数据库阶段；已暂停则抛出 `TaskPaused`。已发出的请求允许完成并照常记录 Token，之后不再发起新请求。
- `app/workflow.py::run_report_graph/run_template_graph/run_writing_graph` 捕获 `TaskPaused` 并正常返回当前任务，不将暂停记为失败。

### 计时

- `app/timing.py` 将 `paused` 作为独立停止段；`snapshot` 增加 `paused_ms`，当前暂停段在暂停入口即结束，因此暂停期间总耗时、处理耗时均冻结。
- 总耗时扣除所有暂停段；恢复后从原阶段新建计时段，不清空既有历史。

## 前端改动

- `app/static/app.js` 的 `phases` 增加 `paused: '已暂停'`。
- `app/static/app.js::detail`：所有非终态任务显示“暂停任务”；已暂停任务显示“继续任务”。按钮调用对应接口，刷新详情；终态不显示。
- `app/static/index.html` 更新 `app.js` 查询版本，避免浏览器继续使用旧缓存。

## 数据操作

服务停止后，通过现有 `Store` 逐任务执行暂停逻辑：仅处理 `created_at` 距当前超过 2 小时且不在终态、尚未暂停的任务。已确认当前有 24 个候选。操作后重启服务，不删除任务或日志。

## 验证

- 新增 `tests/test_pause_and_polling.py`，先运行并确认因功能缺失失败，再实现。
- 覆盖：坏工件不使模板接口 500；任务列表无大型快照字段；暂停幂等与终态拒绝；后台写入不覆盖暂停；恢复人工等待阶段不启动任务；暂停区间冻结且总时长扣除；暂停后模拟模型调用次数不增加。
- 运行相关测试及完整 `python -m pytest`。
- 重启后验证 `/api/templates`、`/` 为 200，`/api/tasks` 响应显著缩小；验证暂停/继续接口及前端按钮；核对 24 个超时任务已暂停。
