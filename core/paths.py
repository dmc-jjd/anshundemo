"""数据根注入点：`core/` 不反向依赖宿主包（S7 §1.1 CORE-DEP），由宿主在 import 期注入。

与四个 registry 同风格：module-global + `configure(...)`，未配置即 RuntimeError。
`data_root()` **只许函数内调用**——模块级求值会让「先 import core 渲染器、后 import 宿主包」的顺序炸。
"""

from __future__ import annotations

from pathlib import Path

_data_root: Path | None = None


def configure_data_root(path) -> None:
    global _data_root
    _data_root = Path(path)


def data_root() -> Path:
    if _data_root is None:
        raise RuntimeError('data_root_not_configured')
    return _data_root
