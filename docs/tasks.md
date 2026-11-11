# 实施任务

- [x] 1. 在 `tests/test_pause_and_polling.py` 编写模板脏引用与任务摘要回归测试，运行确认失败。
- [x] 2. 修改 `app/main.py::templates/tasks` 和 `app/static/app.js::refresh/tab`，运行对应测试确认通过。
- [x] 3. 在测试中加入暂停状态保护、暂停/恢复接口和计时冻结用例，运行确认失败。
- [x] 4. 修改 `app/storage.py::put_task`、`app/main.py::pause/resume`、`app/timing.py::transition/snapshot`，运行对应测试确认通过。
- [x] 5. 在测试中加入暂停后不再调用模型、已发请求保持计量的用例，运行确认失败。
- [x] 6. 修改 `app/model_client.py` 与 `app/workflow.py` 的协作式暂停，运行对应测试确认通过。
- [x] 7. 修改 `app/static/app.js` 和 `app/static/index.html`，增加暂停/继续按钮与阶段文案。
- [x] 8. 运行相关测试和完整 `python -m pytest`，修复本次改动引起的回归。
- [x] 9. 停止服务，批量暂停超过 2 小时且未结束的任务，重启并验证接口、响应体积、按钮和任务状态。
