# 建包与当前基座的兼容操作

此说明适用于纯客户包接入。保留主手册的材料、人工确认和 30 条必写 + 4 条条件提示词要求；不因框架优化降低业务验收标准。路径与行为以当前源码为准。

## 初始化与存储边界

- `app/settings.py`、`app/factory.py`、`app/runtime.py` 管理实例数据根、服务与请求上下文。兼容 `app.main:app`；不要求接客户时改启动入口。模型凭据和包注册表仍是部署级配置，不宣称凭据也按实例隔离。
- 包级配置缺失、未知包和配置损坏应区分，不修改配置来强行回落默认包。显式 `PackageStores(base=...)` 也通过 `core.paths.resolve_data_root` 兼容默认包旧根；非默认包不回落他包。
- 不用 `Store()` 做只读检查：构造会创建目录/表。也不用路由 Store 全包扫描查损坏工件；先定位任务所属包的本地存储，再校验引用。
- 状态更新有 revision 冲突检查，写接口应使用最新 revision；收到 409 时重新读取并判断，不盲目重试旧请求或重新提交模型任务。幂等键在同一操作重试时保持稳定。
- `BackgroundTasks` 仍不能保证跨服务重启恢复；不要为刷新包配置中断正在运行的任务，不能承诺重启后自动续跑。

## 服务未起时：本次模板的只读物证

在仓库根目录设置 `$py` 为项目解释器。以下三项必须来自本次客户任务与服务启动配置；`ONBOARD_DATA_BASE` 是**数据基根**，不是 `packages/<包>`，工厂实例指定根时以实例值为准。变量为此脚本使用，不会修改服务配置。

```powershell
$env:PYTHONIOENCODING = 'utf-8'
$env:ONBOARD_PACKAGE = '<新包>'
$env:ONBOARD_TASK_ID = '<本次模板任务ID>'
$env:ONBOARD_DATA_BASE = '<服务实际数据基根绝对路径>'
@'
import json, os, sqlite3
from contextlib import closing
from pathlib import Path
import app  # 仅初始化读取上下文；导入成功不等于业务健康
from core import paths
from core.storage import Store
from core.structured_template import load_confirmed_template
from core.packages.context import package_context, default_package
from core.packages import load_package

pkg = os.environ['ONBOARD_PACKAGE']
task_id = os.environ['ONBOARD_TASK_ID']
base = Path(os.environ['ONBOARD_DATA_BASE'])
if not base.is_absolute():
    raise ValueError('服务数据基根须为绝对路径')
load_package(pkg)  # 未知包/坏配置显式失败
root = paths.resolve_data_root(base, pkg)
db = root / 'demo.sqlite3'
if not db.is_file() or db.stat().st_size == 0:
    raise FileNotFoundError(f'目标客户数据库不存在或为空: {db}')

class ReadOnlyStore:
    # 复用应用的工件读取/哈希校验，不复制另一份解析规则
    get_artifact = Store.get_artifact
    files = root / 'artifacts'
    def connect(self):
        conn = sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        return closing(conn)

local = ReadOnlyStore()
with local.connect() as conn:
    row = conn.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
if row is None:
    raise KeyError(f'本次任务不在目标客户库: {task_id}')
state = json.loads(row['state'])
# 仅无历史 package 标记的默认包允许兼容归属；不能把空归属推断为任意新包
owner = state.get('package') or default_package()
meta = state.get('metadata') or {}
if owner != pkg or state.get('kind') != 'template' or meta.get('template_deleted_at') or meta.get('simulation'):
    raise ValueError('任务归属、类型或状态不符合要求')
ref = meta.get('confirmed_template_ref')
if not ref:
    raise ValueError('本次模板尚未人工确认')
with package_context(pkg):
    template = load_confirmed_template(local, ref)
print(json.dumps({'package': pkg, 'task_id': task_id, 'template_ref': ref,
                  'root': str(root), 'source_reports': len(template['source_reports']),
                  'artifact_status': 'available'}, ensure_ascii=False))
'@ | & $py -B -
if ($LASTEXITCODE -ne 0) { throw '模板只读物证检查失败，按原始错误定位' }
```

无数据库不补建库；缺失/坏工件不改状态、不跳过哈希、不伪造 source_reports。输出原样放进接入记录。HTTP 与离线结果不一致时先核对实例根、包和 task_id，不能以任意一份成功掩盖差异。

## 定向回归

仓库根目录执行；启动器打印仓库外 Evidence 目录。最小包契约与扩展回归按需分别运行，批次覆盖重叠，不相加冒充唯一用例数。

```powershell
& $py scripts\run_scoped_checks.py tests/test_s7_package_contract.py
if ($LASTEXITCODE -ne 0) { throw '包契约失败' }
& $py scripts\run_scoped_checks.py tests/test_application_factory.py tests/test_template_artifact_availability.py tests/test_report_package_regressions.py tests/test_prompt_corruption_detection.py
if ($LASTEXITCODE -ne 0) { throw '基座兼容回归失败' }
```

启动器会清空模型/搜索凭据并使用临时数据，只能证明所选用例。不要用它验证真实客户数据或模型质量。纯包接入仍需 `check_package.py --package <包>`、提示词集合/来源检查与实际模板物证；业务试稿按用户已授权范围进行。

历史 S5 基线问题按主手册 10.1 单列；不得自动重录基线或放宽断言。要复核这两项时，显式指定 `tests/test_s5_prompt_gate.py::test_prompts_match_baseline` 与 `tests/test_s5_prompt_gate.py::test_gate_rejects_corrupted_bundle`，保留实际失败输出。

## 依赖与代码定位

- 已有可用环境不因建包而升级依赖。新环境的直接依赖以 `requirements.txt` 为准；`requirements.lock` 是 Windows x64 / CPython 3.13 的完整哈希锁，其他平台尚无同等验证。
- 锁文件单独带走不足以保证可安装：本批验证使用包含固定 jieba wheel 的离线 wheelhouse。复制或解压 `.tmp/optimization-dependencies-win-py313.zip` 后，确认 wheelhouse 实际目录，使用 `python -m pip install --no-index --find-links <wheelhouse目录> -r requirements.lock`；随后 `python -m pip check`。不要在接客户过程中自行重建锁或升级版本。归档不存在则报告缺少安装材料，不宣称离线可用。
- Writer 公共入口仍在 `app/structured_writer.py`；计算、补写、展望修复实现已分到 `app/writing_pipeline/calculations.py`、`completion.py`、`outlook_repair.py`。定位依据是当前调用链，不能据文件搬迁改变客户提示词数量。旧 slot 草稿导出已贯穿实例 Store，不代表旧 slot 写作流程的历史问题一并解决。
- 星桥与社媒截图数据属于演示；模拟链接、列表、提示词待发送框跳转均不能作为内部数据接口已接通或客户建包成功的证据。
