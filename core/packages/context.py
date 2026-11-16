"""当前包上下文：用 `ContextVar` 承载「这一次解析属于哪个包」。

三不变量（`core/packages/` 下所有文件共同遵守，别只写在 README 里）：
    ① 模块级「包派生常量」必须为零——漏一处就是静默串包，而且现有测试**永远绿**；
    ② `configure*()` 只许在启动期 / 子进程初始化期调用，绝不许在请求期「切包」；
    ③ `package` 不许进 artifact payload（否则 G-GRAPH 的 4 个分量全变）。

为什么是 `ContextVar` 而不是模块级全局：
    FastAPI 的同步端点跑在 anyio 线程池里，`BackgroundTasks` 与
    `asyncio.to_thread(...)` 也是并发的。模块级「当前包」会被并发请求互相踩：
    A 刚设完、线程被切走、B 设成 B、A 回来就用 B 的词表/列名/提示词——现场表现是
    「偶发、换机器不复现、日志里包名对得上但产物不对」。`ContextVar` 的值属于当前
    执行上下文，线程/协程各一份，天然隔离；新线程没继承 context 时回落到默认包。

未设置时回落到「默认包」：从 `REPORT_PACKAGE` 读（缺省 `anshun_monthly`），
于是现有单包部署零改动，且启动期不必为「当前包叫什么」写任何全局状态。
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

#: 默认包的环境变量名。与 `app/config.py:PACKAGE` 同一个事实源（宿主只读它，基座也只读它）。
ENV_PACKAGE = 'REPORT_PACKAGE'

#: 环境变量缺席时的默认包（= 现网唯一客户的包名；换部署只改环境变量，不改代码）。
FALLBACK_PACKAGE = 'anshun_monthly'


@dataclass(frozen=True, slots=True)
class PackageRef:
    """一次解析的目标：包名 + 可选的显式目录。

    `directory is None` 表示「按包名在 `packages/` 下解析」；显式目录只在两种场景出现：
    工具子进程自己配置（`_configure_package`）与测试里的临时包（`tmp_path`）。
    """

    name: str
    directory: Path | None = None


#: 默认 `None` = 未设置 → `current_ref()` 回落默认包。**不要在 import 期把它设成默认包**：
#: 那会让「启动期设了 A、请求期忘了设」这种漏改变成永远看不出来的静默行为。
_ref: ContextVar[PackageRef | None] = ContextVar('omd_package_ref', default=None)


def default_package() -> str:
    """部署默认包：`REPORT_PACKAGE`（缺省 `anshun_monthly`）。"""
    return os.getenv(ENV_PACKAGE) or FALLBACK_PACKAGE


def current_ref() -> PackageRef:
    return _ref.get() or PackageRef(default_package())


def current_package() -> str:
    """当前包名；未设置时回落默认包。"""
    return current_ref().name


def bind(package: str, directory: str | Path | None = None) -> Token:
    """把当前上下文绑定到某个包（返回 token，供 `unbind` 还原）。

    只在启动期 / 子进程初始化期 / 测试里用；请求期请用 `package_context(...)` 包住，
    不要在这里「设一下再改回来」——异步路径上中间任何一次 await 都可能被别人插队。
    """
    return _ref.set(PackageRef(str(package), None if directory is None else Path(directory)))


def unbind(token: Token) -> None:
    _ref.reset(token)


@contextmanager
def package_context(package: str, directory: str | Path | None = None) -> Iterator[PackageRef]:
    """`with package_context('demo_b'): ...`——离开作用域自动还原，异常路径也还原。"""
    token = bind(package, directory)
    try:
        yield current_ref()
    finally:
        unbind(token)
