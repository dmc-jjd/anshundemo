"""按包路由的 Store 集合：`task_id` 属于哪个包，就落到哪个包的 `Store`。

为什么需要这一层（M2 的数据隔离）：
    数据按包分家后（`data/packages/<包>/{demo.sqlite3,artifacts,uploads,hotspot}`），宿主 35+
    处 `store.*` 调用点拿到的仍是**一个**对象。把所有调用点改成「先查包再取 store」会同时
    改 20 个模块，而且每漏一处就是静默串包；这里给一个同 API 的**路由器**，调用点零改动：
        - 按 `task_id` 路由：get_task / put_task / events / apply_decision / review_draft ...
        - 按 artifact 引用路由：get_artifact / artifact_belongs_to_task（内容寻址 id 不可变，
          解析成功即缓存）
        - 无 task 上下文的旧面（`.root` / `.files` / `.db` / `.connect()` / `.package`）落到
          **默认包**——那是单包部署里唯一有数据的包，保持旧行为。
    `Store` 本身一字未改口径（`db`/`files` 仍是 `root/demo.sqlite3` 与 `root/artifacts`）。

三不变量（`core/packages/` 同一套）：
    ① 模块级「包派生常量」必须为零——本模块只有缓存，键一律带包名，绝不缓存「当前包」；
    ② `configure*()` 只许启动期 / 子进程初始化期调用——本模块只建 Store（不 configure）；
    ③ `package` 不许进 artifact payload——它只活在 `TaskState` 与这个路由表里。

旧任务（M2 之前落盘、`TaskState.package == ''`）：物理上在哪个包的库里就按哪个包读；
    `put_task` 不篡改它的 `package` 字段（读旧值→写回仍是旧值），`get_task` 走扫描结果。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

from . import paths
from .packages import context
from .storage import ConflictError, Store  # noqa: F401  再导出：`from core.package_store import Store` 也成立

#: 候选扫描时容忍的「这个包没有这个 artifact」类错误；坏包不该让别人的读取失败。
_MISS = (KeyError, OSError, ValueError, sqlite3.Error)


class PackageStores:
    """多包 Store 路由（对调用方呈现为单个 Store）。"""

    def __init__(self, base=None):
        self._base = Path(base) if base is not None else None
        self._stores: dict[str, Store] = {}
        self._task_package: dict[str, str] = {}
        self._artifact_package: dict[str, str] = {}
        self._scan_done = False
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    # 根与包
    # ------------------------------------------------------------------ #
    def data_base(self) -> Path:
        """部署级数据基根（`data/`）：工具子进程需要它来配置自己的数据根。"""
        return self._base if self._base is not None else paths.data_root_base()

    @property
    def default_package(self) -> str:
        return context.default_package()

    def package_root(self, package: str | None = None) -> Path:
        """某个包的数据根；不建目录（Store 首次使用时才建）。"""
        name = str(package or self.default_package)
        if self._base is None:
            return paths.data_root(name)
        return self._base / 'packages' / name

    def store_for(self, package: str | None = None) -> Store:
        """取（必要时建）某个包的 Store。"""
        return self._store(package or self.default_package)

    def _store(self, package: str | None) -> Store:
        name = str(package or self.default_package)
        with self._lock:
            store = self._stores.get(name)
            if store is None:
                store = Store(self.package_root(name), package=name)
                self._stores[name] = store
            return store

    def _packages_with_data(self) -> list[str]:
        """磁盘上真有 `demo.sqlite3` 的包（只 scandir；不读 manifest）。"""
        root = self.data_base() / 'packages'
        try:
            with os.scandir(root) as scan:
                return sorted(entry.name for entry in scan
                              if entry.is_dir()
                              and os.path.isfile(os.path.join(entry.path, 'demo.sqlite3')))
        except OSError:
            return []

    # ------------------------------------------------------------------ #
    # task_id → 包
    # ------------------------------------------------------------------ #
    def _scan(self) -> None:
        with self._lock:
            if self._scan_done:
                return
            for name in self._packages_with_data():
                try:
                    store = self._store(name)
                    with store.connect() as conn:
                        for row in conn.execute('SELECT id FROM tasks'):
                            self._task_package.setdefault(row['id'], name)
                except Exception:  # noqa: BLE001  坏库不该让路由整体不可用
                    continue
            self._scan_done = True

    def package_of(self, task_id: str) -> str:
        """任务所属包：路由缓存 → 扫描各包库 → 部署默认包（= 旧任务语义）。"""
        package = self._task_package.get(str(task_id))
        if package:
            return package
        self._scan()
        return self._task_package.get(str(task_id)) or self.default_package

    def root_for(self, task_id: str) -> Path:
        return self.package_root(self.package_of(task_id))

    def files_for(self, task_id: str) -> Path:
        return self.root_for(task_id) / 'artifacts'

    def uploads_for(self, package: str | None = None) -> Path:
        return self.package_root(package) / 'uploads'

    # ------------------------------------------------------------------ #
    # artifact → 包（内容寻址 id 不可变，命中即缓存）
    # ------------------------------------------------------------------ #
    def _candidates(self) -> list[str]:
        names = [self.default_package, *self._packages_with_data(), *self._stores]
        return list(dict.fromkeys(names))

    def get_artifact(self, ref: str):
        package = self._artifact_package.get(str(ref))
        if package:
            return self._store(package).get_artifact(ref)
        for name in self._candidates():
            try:
                data = self._store(name).get_artifact(ref)
            except _MISS:
                continue
            self._artifact_package[str(ref)] = name
            return data
        raise KeyError(ref)

    def artifact_file(self, ref: str, suffix: str = '.docx') -> Path:
        """`{ref}{suffix}` 在哪个包的 artifacts 目录里；找不到时给默认包路径（调用方 404）。"""
        package = self._artifact_package.get(str(ref))
        for name in ([package] if package else self._candidates()):
            path = self._store(name).files / f'{ref}{suffix}'
            if path.exists():
                self._artifact_package[str(ref)] = name
                return path
        return self._store(package or self.default_package).files / f'{ref}{suffix}'

    # ------------------------------------------------------------------ #
    # Store 同名 API（按 task_id 路由）
    # ------------------------------------------------------------------ #
    def get_task(self, task_id: str):
        package = self.package_of(task_id)
        return self._store(package).get_task(task_id)

    def put_task(self, state, expected_revision=None, allow_resume: bool = False):
        package = str(getattr(state, 'package', '') or '') or self.package_of(state.id)
        stored = self._store(package).put_task(state, expected_revision, allow_resume)
        with self._lock:
            self._task_package[state.id] = package
        return stored

    def list_tasks(self):
        tasks = []
        for name in self._candidates():
            try:
                tasks.extend(self._store(name).list_tasks())
            except _MISS:
                continue
        tasks.sort(key=lambda task: (task.created_at, task.id), reverse=True)
        return tasks

    def put_artifact(self, task_id: str, kind: str, payload):
        package = self.package_of(task_id)
        ref = self._store(package).put_artifact(task_id, kind, payload)
        with self._lock:
            self._artifact_package[str(ref)] = package
        return ref

    def artifact_belongs_to_task(self, ref: str, task_id: str) -> bool:
        return self._store(self.package_of(task_id)).artifact_belongs_to_task(ref, task_id)

    def get_review_draft(self, task_id, analysis_ref=None):
        return self._store(self.package_of(task_id)).get_review_draft(task_id, analysis_ref)

    def put_review_draft(self, task_id, analysis_ref, data, expected_version=None):
        return self._store(self.package_of(task_id)).put_review_draft(
            task_id, analysis_ref, data, expected_version)

    def append_event(self, task_id: str, event: dict):
        self._store(self.package_of(task_id)).append_event(task_id, event)

    def events(self, task_id: str, after: int = 0, limit: int | None = None):
        return self._store(self.package_of(task_id)).events(task_id, after, limit)

    def idempotent(self, key: str, value: str, package: str | None = None) -> str:
        return self._store(package or self.default_package).idempotent(key, value)

    def apply_decision(self, task_id: str, decision):
        return self._store(self.package_of(task_id)).apply_decision(task_id, decision)

    # ------------------------------------------------------------------ #
    # 旧的无 task 上下文面：默认包（单包部署零改动）
    # ------------------------------------------------------------------ #
    @property
    def package(self) -> str:
        """本路由的「部署默认包」——`core.usage` 用它决定价目表放共享根。"""
        return self.default_package

    @property
    def root(self) -> Path:
        return self.package_root(self.default_package)

    @property
    def files(self) -> Path:
        return self.root / 'artifacts'

    @property
    def db(self) -> Path:
        return self.root / 'demo.sqlite3'

    def connect(self):
        """旧面：默认包连接（`editor_api` / `section_two` 的裸 SQL 调用点保持可用）。"""
        return self._store(self.default_package).connect()
