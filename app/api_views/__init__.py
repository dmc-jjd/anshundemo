"""路由函数体里的领域组装逻辑，下沉为纯函数（接参数、返数据）。

契约：本包不引入 web 框架、不抛 HTTP 异常、不新建存储连接。
`app/main.py` 的路由函数在**运行期**求值 store/deps/UPLOADS/run_report_graph/
export_docx/validate_draft 后**作为参数传进来**——本包永不从 main 模块导入这些名字，
否则注入面在 import 期被绑死，monkeypatch 静默失效（15 个测试文件依赖该柔性）。
"""
