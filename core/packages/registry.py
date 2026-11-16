"""包解析的唯一入口：发现（`scandir`）+ 按需加载 + 有界 LRU（8 个包）。

三不变量（同 `core/packages/context.py` 文件头，逐条都是硬约束）：
    ① 模块级「包派生常量」必须为零——本模块只持有**缓存**，缓存键一律含包名 + 指纹；
    ② `configure*()` / `preload()` 只许启动期或子进程初始化期调用，绝不许请求期切包；
    ③ `package` 不许进 artifact payload（否则 G-GRAPH 的 4 个分量全变）。

**启动策略（实测数据支撑，别「优化」回去）**
    100 包全量 configure = 7.69 s（3400 次提示词文件打开）← **禁止在启动时做**
    只 scandir            = 0.11 ms                            ← 启动就做这个
    首次使用单包加载      = 约 77 ms / 包                       ← 按需

**缓存键为什么必须含指纹**
    键只有包目录时，「改了包内文件但服务没重启」会继续用旧文本（现网之所以没暴露，
    是因为四个注册表只在 import 期预热一次）。指纹 = 参与解析的文件
    `(相对路径, mtime_ns, size)` 元组，覆盖：`manifest.yaml`、包内 `*.json`（`template.json`）、
    `dict.txt`、包内 `prompts/**`、以及基座 `core/prompts/base/**`（兜底层；改基座提示词
    同样必须让所有包的缓存失效）。

**容量为什么是 8**
    8 个包的对象约 0.56 MB（实测 bundle 49 KB/包 + template 20.6 KB/包），
    真正的约束是首用延迟（38 ms/包）而不是内存。缺失时最坏代价 = 一次冷读。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from core import config as _config
from core.packages import context

ENV_PACKAGES_ROOT = 'REPORT_PACKAGES_ROOT'
ENV_TEMPLATES_ROOT = 'REPORT_TEMPLATES_ROOT'

#: 常驻包的容量。**必须 ≥ 同时活跃的包数**，否则轮转时命中率 ≈ 0（每次 38 ms 冷读）。
MAX_CACHED_PACKAGES = 8

#: 基座提示词兜底目录：包内没有的键从这里读，所以它也必须进指纹。
BASE_PROMPTS_DIR = Path(__file__).resolve().parents[1] / 'prompts' / 'base'

#: 扫描时跳过的条目（缓存目录/隐藏目录不是包）。
_SKIP_NAMES = frozenset({'__pycache__'})


class PackageError(RuntimeError):
    """包不可读：目录不存在、manifest 缺失、模板不是合法 JSON 等（错误码可归因，不静默回落）。"""


# --------------------------------------------------------------------------- #
# 根目录（部署级常量，不是包派生常量）
# --------------------------------------------------------------------------- #


def packages_root() -> Path:
    """`packages/` 根：`REPORT_PACKAGES_ROOT` 优先，缺省是仓库根下 `packages/`。"""
    override = os.getenv(ENV_PACKAGES_ROOT)
    return Path(override) if override else _config.ROOT / 'packages'


def templates_root() -> Path:
    """`templates/` 根：客户模板目录（占位符清单 + 带占位符 docx）按包名分家。

    M1 只「按包名解析」，不搬目录（`templates/<pkg>/` 仍是宿主侧布局；合并进
    `packages/<pkg>/` 留给后续里程碑，见 `.conda/research/multi-package.md` §2）。
    """
    override = os.getenv(ENV_TEMPLATES_ROOT)
    return Path(override) if override else _config.ROOT / 'templates'


# --------------------------------------------------------------------------- #
# 发现（廉价面：只 scandir，不读任何包内文件）
# --------------------------------------------------------------------------- #


def discover() -> tuple[str, ...]:
    """包名清单：扫 `packages/*/manifest.yaml`，**不解析 YAML**（0.11 ms / 100 包）。

    目录名即包名（`manifest.package` 与目录名不一致由加载期报错，不在发现期猜）。
    忽略 `.` / `_` 前缀（临时目录/禁用包）与没有 manifest 的目录。
    """
    root = packages_root()
    try:
        with os.scandir(root) as scan:
            candidates = [(entry.name, entry.is_dir(),
                           os.path.isfile(os.path.join(entry.path, 'manifest.yaml')))
                          for entry in scan]
    except OSError:
        return ()
    return tuple(name for name, is_dir, has_manifest in sorted(candidates)
                 if is_dir and has_manifest and not name.startswith(('.', '_')))


# --------------------------------------------------------------------------- #
# 目录解析
# --------------------------------------------------------------------------- #


def package_dir(package: str | None = None) -> Path:
    """包目录：显式包名 → `packages/<包名>`；`None` → 当前上下文的包（可能是显式绑定的临时目录）。"""
    if package is None:
        ref = context.current_ref()
        directory = ref.directory if ref.directory is not None else packages_root() / ref.name
        name = ref.name
    else:
        directory = packages_root() / str(package)
        name = str(package)
    if not directory.is_dir():
        raise PackageError(f'package_not_found:{name}（期望目录 {directory}）')
    return directory


# --------------------------------------------------------------------------- #
# 指纹
# --------------------------------------------------------------------------- #


def _tree_stamp(root: Path) -> tuple[tuple[str, int, int], ...]:
    """`root` 下全部文件的 `(相对路径, mtime_ns, size)`，按相对路径排序（不含缓存目录）。

    用 `os.scandir` 递归：`DirEntry.stat()` 在 Windows 上复用目录枚举时拿到的时间戳，
    比逐个 `Path.stat()` 便宜；包目录规模是个位数十来个文件（34 个提示词 + manifest/template）。
    """
    rows: list[tuple[str, int, int]] = []

    def walk(directory: Path, prefix: str) -> None:
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return
        for entry in entries:
            name = entry.name
            if name in _SKIP_NAMES or name.endswith('.pyc') or name.startswith('.'):
                continue
            rel = f'{prefix}{name}'
            if entry.is_dir():
                walk(Path(entry.path), rel + '/')
                continue
            try:
                stat = entry.stat()
            except OSError:
                continue
            rows.append((rel, stat.st_mtime_ns, stat.st_size))

    walk(root, '')
    rows.sort()
    return tuple(rows)


def fingerprint(directory: str | Path) -> tuple[tuple[tuple[str, int, int], ...], tuple[tuple[str, int, int], ...]]:
    """缓存指纹：`(包目录戳, 基座兜底目录戳)`。任何一边的文件改动都会让该包缓存失效。"""
    return _tree_stamp(Path(directory)), _tree_stamp(BASE_PROMPTS_DIR)


# --------------------------------------------------------------------------- #
# 按需加载（唯一缓存层：prompts / template / manifest / charts / skills 共用一份）
# --------------------------------------------------------------------------- #


class PackageLoad:
    """一个包的一次完整加载结果；每个派生资源都是**按需**求值且在本对象内只算一次。

    为什么把 prompts / template / manifest 放在同一个对象里：
    原先 `core/tools/vocabulary.py` 与 `core/charts/registry.py` 各持一份
    `@lru_cache(maxsize=4) _template(package_dir)`——同一份 `template.json` 被读两遍、
    缓存两份。现在只有这里一份，两个注册表都从 `template` 取。
    """

    def __init__(self, name: str, directory: Path, stamp) -> None:
        self.name = str(name)
        self.directory = Path(directory)
        self.fingerprint = stamp
        self._memo: dict[str, Any] = {}

    def __repr__(self) -> str:  # pragma: no cover - 仅排障用
        return f'PackageLoad({self.name!r}, {self.directory.as_posix()!r})'

    def _once(self, key: str, factory):
        if key not in self._memo:
            self._memo[key] = factory()
        return self._memo[key]

    # -- 包内文件 ---------------------------------------------------------- #
    @property
    def manifest(self):
        """`Manifest`（含 agents 校验）。每个包一次，不再每次调用重读 YAML。"""
        from core.manifest import load_manifest

        return self._once('manifest', lambda: load_manifest(self.directory))

    @property
    def template(self) -> dict[str, Any]:
        """`template.json` 解析结果。**全仓唯一一份**（vocabulary 与 charts 共用）。"""
        from core.manifest import load_template

        return self._once('template', lambda: load_template(self.directory))

    @property
    def prompt_bundle(self) -> dict[str, Any]:
        """提示词 bundle（prompts/roles/policy/profiles/default/sources）。"""
        from core.prompts import registry as prompts_registry

        return self._once('prompt_bundle', lambda: prompts_registry.read_bundle(self.directory))

    # -- 提示词派生对象（`core/agent.py` 的公开名背后的真身） ---------------- #
    @property
    def agent_prompts(self) -> dict[str, str]:
        return self.prompt_bundle['prompts']

    @property
    def prompt_sources(self) -> dict[str, str]:
        return self.prompt_bundle['sources']

    @property
    def roles(self) -> dict[str, dict[str, str]]:
        return self.prompt_bundle['roles']

    @property
    def template_policy(self) -> dict[str, Any]:
        return self.prompt_bundle['template_policy']

    @property
    def report_profiles(self) -> dict[str, dict[str, str]]:
        return self.prompt_bundle['report_profiles']

    @property
    def default_profile(self) -> str:
        return self.prompt_bundle['default_profile']

    @property
    def agent_definitions(self) -> dict[str, Any]:
        """角色 id → `AgentDefinition`（frozen dataclass；`model_client` 用属性访问）。"""
        from core.agent import AgentDefinition

        def build():
            return {role_id: AgentDefinition(role_id, spec['responsibility'], spec['boundary'], spec['output'])
                    for role_id, spec in self.roles.items()}

        return self._once('agent_definitions', build)

    # -- 图表 / 技能 -------------------------------------------------------- #
    @property
    def chart_items(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.template.get('charts') or ())

    @property
    def skill_use(self) -> tuple[str, ...]:
        return self.manifest.skill_use

    # -- 工具策略 ----------------------------------------------------------- #
    @property
    def tool_policy(self):
        """`capabilities.require` 剪枝 + `features.*` 开关叠加后的 `ToolPolicy`。"""
        return self._once('tool_policy', self._build_tool_policy)

    def _build_tool_policy(self):
        from core.ports import ToolPolicy

        manifest = self.manifest
        policy = manifest.policy
        required, features = manifest.required_capabilities, manifest.features
        if not (required or features):
            return policy
        from core.tools.registry import resolve_tools

        narrowed = resolve_tools(required, features)
        base = set(policy.allow) if policy.allow else narrowed
        return ToolPolicy(allow=frozenset(base & narrowed),
                          phases=policy.phases, budgets=policy.budgets)


@lru_cache(maxsize=MAX_CACHED_PACKAGES)
def _load(name: str, directory: str, stamp) -> PackageLoad:
    """有界 LRU：键 = (包名, 绝对目录, 指纹)。`cache_info()` 可观测，便于钉住容量与淘汰。"""
    return PackageLoad(name, Path(directory), stamp)


def load(package: str | None = None) -> PackageLoad:
    """取当前包（或指定包）的加载结果；命中缓存时只付一次指纹扫描。"""
    ref = context.current_ref() if package is None else context.PackageRef(str(package))
    directory = ref.directory if (package is None and ref.directory is not None) else packages_root() / ref.name
    if not directory.is_dir():
        raise PackageError(f'package_not_found:{ref.name}（期望目录 {directory}）')
    stamp = fingerprint(directory)
    return _load(ref.name, str(directory.resolve()), stamp)


def load_directory(directory: str | Path, package: str | None = None) -> PackageLoad:
    """按**显式目录**加载（工具子进程 / 临时包）：包名缺省取目录名。"""
    path = Path(directory)
    if not path.is_dir():
        raise PackageError(f'package_not_found:{package or path.name}（期望目录 {path}）')
    return _load(str(package or path.name), str(path.resolve()), fingerprint(path))


def preload(package_or_dir: str | Path | None = None) -> PackageLoad:
    """启动期/子进程初始化期的**单包**预热：解析 + 结构校验，包不对就在这里炸。

    只预热一个包（默认包）。**禁止**在这里遍历 `discover()`——100 包 = 7.69 s。
    """
    if package_or_dir is None:
        return load()
    candidate = Path(package_or_dir)
    if candidate.is_dir():
        return load_directory(candidate)
    return load(str(package_or_dir))


def invalidate(package: str | None = None) -> None:
    """显式失效（测试/运维用）。指纹机制已覆盖正常场景，这里是逃生门。"""
    _load.cache_clear()


def bootstrap() -> tuple[str, ...]:
    """启动期引导：**只做发现**（scandir，100 包 0.11 ms），不解析任何包内文件。

    宿主 `app/__init__.py` 在 import 期调它一次（M2 起）——`GET /api/packages` 与按需加载
    都建立在同一份「目录名清单」上。默认包的 fail-fast 仍由四个注册表的 `configure()` 负责
    （**单包**，不是 N 包全量 configure——后者实测 7.69 s）。
    """
    return discover()


def catalog() -> tuple[dict, ...]:
    """客户包注册表：`GET /api/packages` 的唯一数据面（发现 + 按需加载 + 健康判定）。

    **坏包仍在列表里，但 `usable=False` 且 `error` 说明原因**——不静默剔除、不回落默认包：
    前者会让运维看不见坏包，后者会让「建任务」假装成功。

    加载策略：逐包 `load()`（指纹缓存命中只付一次扫描）+ 解析 manifest/template/提示词
    bundle。启动期**不调用**本函数（100 包全量 configure = 7.69 s）；它只在注册表端点
    被请求时执行，结果对象进 LRU，改包内文件即因指纹失效。
    """
    entries: list[dict] = []
    for name in discover():
        entry = {'package': name, 'name': '', 'report_type': '', 'version': '',
                 'usable': False, 'status': 'unavailable', 'error': None}
        try:
            loaded = load(name)
            manifest = loaded.manifest
            loaded.template
            loaded.prompt_bundle       # prompts/index.yaml + roles + 角色校验
            entry.update(name=manifest.report_type, report_type=manifest.report_type,
                         version=manifest.version, usable=True, status='ok')
        except Exception as exc:       # noqa: BLE001  注册表要能描述任何坏包
            entry['error'] = f'{type(exc).__name__}: {exc}'
        entries.append(entry)
    return tuple(entries)


def cache_info():
    """观测面：`maxsize` / `currsize` / 命中率（容量契约测试用它）。"""
    return _load.cache_info()
