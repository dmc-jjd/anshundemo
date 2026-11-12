"""数据根注入点：`core/` 不反向依赖宿主包（S7 §1.1 CORE-DEP），由宿主在 import 期注入。

与四个 registry 同风格：module-global + `configure(...)`，未配置即 RuntimeError。
两个取值函数 **只许函数内调用**——模块级求值会让「先 import core 渲染器、后 import 宿主包」的顺序炸。

`package_dir` 是 S8-L3 新增的第二个注入点：`tool_executor` 读客户包 manifest 需要它，
而基座不许 import 宿主的 `config`；宿主在首个 import 时 configure 一次，
与 `data_root` 同一个注入面、同一条纪律（`docs/team/任务分解-S8.md` §6 D2）。

`template_dir` 是 S8-L4 新增的第三个注入点：`slot_writer` 读客户模板目录（占位符清单 +
带占位符的 docx）需要它。模板目录名是宿主绑定（换包即换模板），留在基座就是客户数据
进基座；注入面与 `package_dir` 完全同构（§6 D7 选 (a) `paths.template_dir()`）。
"""

from __future__ import annotations

from pathlib import Path

_data_root: Path | None = None
_package_dir: Path | None = None
_template_dir: Path | None = None


def configure_data_root(path) -> None:
    global _data_root
    _data_root = Path(path)


def data_root() -> Path:
    if _data_root is None:
        raise RuntimeError('data_root_not_configured')
    return _data_root


def configure_package_dir(path) -> None:
    global _package_dir
    _package_dir = Path(path)


def package_dir() -> Path:
    if _package_dir is None:
        raise RuntimeError('package_dir_not_configured')
    return _package_dir


def configure_template_dir(path) -> None:
    global _template_dir
    _template_dir = Path(path)


def template_dir() -> Path:
    if _template_dir is None:
        raise RuntimeError('template_dir_not_configured')
    return _template_dir
