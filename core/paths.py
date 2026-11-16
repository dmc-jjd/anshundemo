"""三个「按包解析」的路径出口：数据根 / 包目录 / 客户模板目录。

三不变量（与 `core/packages/` 同一套，硬约束）：
    ① 模块级「包派生常量」必须为零——本模块只持**部署级**配置（数据基根、模板根），
       三个取值函数一律函数内解析当前包，绝不在 import 期求值；
    ② `configure_*()` 只许启动期 / 子进程初始化期调用，绝不许请求期切包；
    ③ `package` 不许进 artifact payload（M1 边界；进产物 = G-GRAPH 变）。

M2 的数据根分家（`data/packages/<包>/`，部署级价目表在 `data/shared/`）：
    基根（部署级）          `configure_data_root()` 注入，来自 `REPORT_DEMO_DATA`，缺省 `<repo>/data`
    包数据根（包派生）      `<基根>/packages/<包名>` = `demo.sqlite3` / `artifacts/` / `uploads/` / `hotspot/`
    共享数据根（部署级）    `<基根>/shared/`，例如 `token-pricing.json`（不按包分）

**未迁移旧数据根的回落（一次，且带 warning；绝不静默）**
    代码先合入、真实 `data/` 尚未迁移时，`<基根>/packages/<默认包>/` 里**没有非空的
    `demo.sqlite3`**、而 `<基根>/demo.sqlite3` 还在——这正是「旧单根布局」。此时默认包按
    旧根解析并 `logging.warning` 一次；迁移完成后包里有了库，自动走新布局。非默认包
    **永远不回落**（否则 B 会读到 A 的数据，那才是真正的串包）。

    判据必须是「包里有没有非空 db」，不能是「包目录在不在」：迁移脚本先建目标目录再搬文件，
    任何一次失败（哪怕第一步 db 被占用）都会留下空的 `packages/<包>/`；按目录判「已迁移」
    则应用读空包根 → 0 条任务，用户视角就是「数据全没了」。

取值口径（S 系列里程碑一直在用的三条错误语义，逐字保留）：
    - 未配置数据基根      → `data_root_not_configured`
    - 未配置模板目录      → `template_dir_not_configured`
    - 已配置但目录不存在  → `template_dir_missing:<包名>`（不静默回落到别的包）
    - 包目录不存在        → `package_not_found:<包名>`（`core.packages.registry.PackageError`）
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from pathlib import Path

from core.packages import context as _context
from core.packages import registry as _registry

_LOG = logging.getLogger(__name__)

#: 部署级数据基根（不是包派生值）：由宿主包在启动期配置一次。
#: 每个工具子进程也会自己配置一次（`_configure_package`）——那是在**新进程的主线程**里，
#: 所以下面这个 ContextVar 覆盖对它有效；而线程池里的工作线程拿不到主线程设的 ContextVar，
#: 于是必须保留进程级默认值（`_data_root_default`）作为回落。
_data_root_default: Path | None = None
_data_root_var: ContextVar[Path | None] = ContextVar('omd_data_root', default=None)

#: 显式模板目录覆盖（legacy 注入面）。缺省 `None` = 按包名解析到 `templates/<包名>`。
_template_dir_var: ContextVar[Path | None] = ContextVar('omd_template_dir', default=None)

#: 包数据根的有效性判据：目录里必须有**非空**的 `demo.sqlite3`。0 字节的库是坏数据，
#: 不算「已迁移」；空目录（迁移失败残留）更不算。
_PACKAGE_DB = 'demo.sqlite3'

#: 旧单根回落的 warning 只打一次（进程级）；包里一出现非空 db 就再也不会回落。
_legacy_root_warned = False


def configure_data_root(path) -> None:
    """配置**部署级数据基根**（`data/` 的父级布局，不是某个包的数据根）。

    子进程传进来的也是基根（`<repo>/data`），不是包的数据根——包根由包名派生。
    """
    global _data_root_default
    _data_root_default = Path(path)
    _data_root_var.set(_data_root_default)


def _configured_base() -> Path:
    override = _data_root_var.get()
    if override is not None:
        return override
    if _data_root_default is None:
        raise RuntimeError('data_root_not_configured')
    return _data_root_default


def data_root_base() -> Path:
    """部署级数据基根（`data/`）：共享价目表、迁移脚本都以它为准。"""
    return _configured_base()


def _package_root_ready(directory: Path) -> bool:
    """有效包根 = 里面有一个**非空** `demo.sqlite3`（`is_file()` 只看存在，0 字节不算）。"""
    database = directory / _PACKAGE_DB
    try:
        return database.is_file() and database.stat().st_size > 0
    except OSError:
        return False


def resolve_data_root(base, package=None) -> Path:
    """纯函数：`<基根>/packages/<包>`；默认包在旧单根布局下回落 `<基根>`（带一次 warning）。

    为什么单独抽成纯函数：宿主 `config.py` 的 `DATA` 是 import 期常量，必须与运行期
    `data_root()` 用**同一段判定**，否则「迁移前重启」时两处会指向不同的根（一个旧、一个新，
    现场表现是任务列表空但文件都在）。判定只看盘上事实，不缓存结果。

    为什么判据是 db 而不是目录：迁移脚本先建目录再搬文件，失败残留就是空目录；只认目录会
    把「迁移失败」误判成「已迁移」，应用随即读空包根（0 条任务 = 用户视角的数据全丢）。
    """
    global _legacy_root_warned
    base = Path(base)
    name = str(package) if package else _context.current_package()
    candidate = base / 'packages' / name
    if _package_root_ready(candidate):
        return candidate
    if name == _context.default_package() and (base / _PACKAGE_DB).is_file():
        if not _legacy_root_warned:
            _legacy_root_warned = True
            _LOG.warning(
                'legacy_data_root_in_use: %s 没有 %s，按默认包回落旧根 %s'
                '（迁移未完成或失败残留）',
                candidate, _PACKAGE_DB, base)
        return base
    return candidate


def data_root(package: str | None = None) -> Path:
    """**包数据根**：`<基根>/packages/<包名>`；`package=None` = 当前上下文的包。

    默认包在未迁移布局下回落旧根（见 `resolve_data_root`，一次 warning）；非默认包不回落。
    """
    return resolve_data_root(_configured_base(), package)


def shared_data_root() -> Path:
    """部署级共享数据根（`<基根>/shared/`）：价目表等**不按包分**的数据。"""
    return _configured_base() / 'shared'


def configure_package_dir(path) -> None:
    """把当前上下文绑定到某个包目录（legacy 注入面：宿主 `__init__` / 工具子进程各调一次）。

    等价于 `core.packages.context.bind(路径名, 路径)`——**不再写模块级单槽**，
    所以并发请求不会因为谁后 configure 谁生效而互相踩。
    """
    directory = Path(path)
    _context.bind(directory.name, directory)


def package_dir(package: str | None = None) -> Path:
    """包目录：`None` → 当前上下文的包；显式包名 → `packages/<包名>`。"""
    return _registry.package_dir(package)


def configure_template_dir(path) -> None:
    """显式绑定客户模板目录（legacy；缺省按包名解析）。只记路径、不碰盘。"""
    _template_dir_var.set(Path(path))


def template_dir(package: str | None = None) -> Path:
    """客户模板目录；**取用时**才校验存在性，import 期不碰盘。

    M3 起支持两种布局，按顺序取第一个存在的（都按包名分家，绝不回落别的包）：
        ① `<packages_root>/<包>/templates/` —— 模板随包发布（新增包只往包里放文件，
           不用再动宿主 `templates/` 目录；`REPORT_PACKAGES_ROOT` 指到外部时也成立）；
        ② `<templates_root>/<包>/` —— 宿主旧布局（A 包现网就在用，一字未搬）。
    两者都不存在（该包没有自己的版式模板）→ `template_dir_missing:<包>`。这不是错误回落，
    是**如实报缺**：B 类客户（无自有版式模板、只用上传的历史报告比对）本就不需要这个目录；
    需要出终稿 docx 的包必须自己提供 ① 或 ②。

    显式 `configure_template_dir()` 的覆盖只在 `package is None` 时生效（legacy 注入面）。
    """
    override = _template_dir_var.get() if package is None else None
    name = _context.current_package() if package is None else str(package)
    if override is not None:
        directory = Path(override)
    else:
        candidates = (_registry.packages_root() / name / 'templates',
                      _registry.templates_root() / name)
        directory = next((candidate for candidate in candidates if candidate.is_dir()),
                         candidates[-1])
    if not directory.is_dir():
        raise RuntimeError(
            f'template_dir_missing:{name}'
            f'（期望 packages/{name}/templates/ 或 templates/{name}/，两者都不存在）')
    return directory
