"""三个「按包解析」的路径出口：数据根 / 包目录 / 客户模板目录。

三不变量（与 `core/packages/` 同一套，硬约束）：
    ① 模块级「包派生常量」必须为零——本模块只持**部署级**配置（数据根、模板根），
       三个取值函数一律函数内解析当前包，绝不在 import 期求值；
    ② `configure_*()` 只许启动期 / 子进程初始化期调用，绝不许请求期切包；
    ③ `package` 不许进 artifact payload（M1 边界；进产物 = G-GRAPH 变）。

取值口径（S 系列里程碑一直在用的三条错误语义，逐字保留）：
    - 未配置数据根      → `data_root_not_configured`
    - 未配置模板目录    → `template_dir_not_configured`
    - 已配置但目录不存在 → `template_dir_missing:<包名>`（不静默回落到别的包）
    - 包目录不存在      → `package_not_found:<包名>`（`core.packages.registry.PackageError`）

与 `core/packages/` 的分工：
    包目录/模板目录**由包名解析**（`packages/<pkg>`、`templates/<pkg>`），唯一事实源是
    `core.packages.context` 的 ContextVar；本模块只做「这台机器上根目录在哪」这一层部署配置。
    数据根在 M1 **仍未按包隔离**（迁移脚本与 Store 改归属 M2），`data_root()` 因此保持
    「部署级单根」，只是把单槽换成「ContextVar 覆盖 + 进程默认值」，为 M2 留出接缝。
"""

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path

from core.packages import context as _context
from core.packages import registry as _registry

#: 部署级数据根（不是包派生值）：由宿主包在启动期配置一次。
#: 每个工具子进程也会自己配置一次（`_configure_package`）——那是在**新进程的主线程**里，
#: 所以下面这个 ContextVar 覆盖对它有效；而线程池里的工作线程拿不到主线程设的 ContextVar，
#: 于是必须保留进程级默认值（`_data_root_default`）作为回落。
_data_root_default: Path | None = None
_data_root_var: ContextVar[Path | None] = ContextVar('omd_data_root', default=None)

#: 显式模板目录覆盖（legacy 注入面）。缺省 `None` = 按包名解析到 `templates/<包名>`。
_template_dir_var: ContextVar[Path | None] = ContextVar('omd_template_dir', default=None)


def configure_data_root(path) -> None:
    """配置**部署级**数据根（M1 仍是单根；M2 才按包分家）。"""
    global _data_root_default
    _data_root_default = Path(path)
    _data_root_var.set(_data_root_default)


def data_root(package: str | None = None) -> Path:
    """数据根。`package` 参数在 M1 **不改变返回值**（数据根迁移属 M2），保留是为 M2 的调用面。"""
    override = _data_root_var.get()
    if override is not None:
        return override
    if _data_root_default is None:
        raise RuntimeError('data_root_not_configured')
    return _data_root_default


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

    两种错误必须区分：
    - 显式覆盖了但在另一个上下文里（如新起线程）→ 回落按包名解析，不让「没继承 context」变成错误；
    - 已解析但目录不存在（该包没有自己的模板）→ `template_dir_missing:<包名>`。
    """
    override = _template_dir_var.get() if package is None else None
    directory = override if override is not None else _registry.templates_root() / (
        _context.current_package() if package is None else str(package))
    if not directory.is_dir():
        raise RuntimeError(f'template_dir_missing:{directory.name}'
                           f'（期望 templates/{directory.name}/，该目录不存在）')
    return directory
