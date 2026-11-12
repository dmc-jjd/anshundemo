"""子进程 configure 验证：显式 package_dir 是否真的能让子进程独立工作。

这是 S8 迁移的硬前置——`tool_executor` 搬进 core 后，子进程 import 的是 `core.*`，
`core/__init__.py` 是空文件，不会再触发 app 的 configure。若这里不成立，
迁移后表现为「工具调用全超时 + 工件全空 + 门禁仍绿」（S6 F5 陷阱的镜像）。
"""

from __future__ import annotations

import multiprocessing
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]


def _child_probe(conn, package_dir):
    """裸子进程：不 import app，只走 _configure_package。"""
    import sys as _sys

    _sys.path.insert(0, str(REPO))
    try:
        from app.tool_executor import _configure_package

        _configure_package(package_dir)
        from core.tools import vocabulary

        # 这三项是工具模块级/函数级真正依赖的客户数据
        payload = {
            "columns": vocabulary.required_columns(),
            "localities": len(vocabulary.localities()),
            "clusters": len(vocabulary.cluster_terms()),
            "app_imported": "app" in _sys.modules,
        }
        conn.send(("ok", payload))
    except Exception as exc:  # noqa: BLE001
        conn.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        conn.close()


def test_child_process_can_configure_package_without_app_side_effects():
    parent, child = multiprocessing.Pipe(duplex=False)
    proc = multiprocessing.get_context("spawn").Process(
        target=_child_probe, args=(child, str(REPO / "packages" / "anshun_monthly"))
    )
    proc.start()
    child.close()
    assert parent.poll(60), "子进程 60 秒内没有回报"
    status, payload = parent.recv()
    parent.close()
    proc.join(10)

    assert status == "ok", f"子进程配置失败：{payload}"
    assert payload["columns"] == ["标题", "舆情调性"]
    assert payload["localities"] == 8
    assert payload["clusters"] == 12


def test_configure_is_idempotent_in_same_process():
    """重复 configure 不该炸（父进程可能已配过，子进程再配一次）。"""
    from app.tool_executor import _configure_package
    from core.tools import vocabulary

    package_dir = str(REPO / "packages" / "anshun_monthly")
    _configure_package(package_dir)
    first = vocabulary.required_columns()
    _configure_package(package_dir)

    assert vocabulary.required_columns() == first
