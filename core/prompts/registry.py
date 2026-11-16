"""提示词包注册表：从客户包 `manifest.prompts` 指向的目录读角色、提示词与结构化策略。

分层（S10-E 起）：
    - 索引与结构化策略 → `<prompts>/index.yaml`
    - 角色职责与边界   → `<prompts>/roles.yaml`
    - 各阶段提示词     → `<prompts>/agent/<key>.md`（一个键一个文件）

三不变量（`core/packages/` 同一套）：
    ① 模块级「包派生常量」必须为零——本模块的 `_package_dir` 只作 **legacy 显式注入槽**
       （`_UNSET` = 未注入，走包解析；`None` = 显式「未配置」，调 getter 即
       `package_not_configured`；`Path` = 显式目录），**从不**保存任何包的数据；
    ② `configure()` 只许启动期 / 子进程初始化期调用，绝不许请求期切包；
    ③ `package` 不许进 artifact payload。

**M1 起「解析」不再依赖 `configure()`**：每个 getter 都带 `package=None`，`None` 时解析
当前上下文（`core.packages.context`，ContextVar；未设置回落默认包）。`configure()` 保留，
因为它是**启动期 fail-fast 的唯一入口**（`scripts/check_package.py` 的 LOAD 段依赖它：
坏包必须在 `import app` 期就炸），但它的语义收窄为「绑定 + 校验**这一个**包」。

缓存：bundle 的缓存已上移到 `core/packages/registry.PackageLoad`（键 = 包名 + 目录 + 指纹，
容量 8）。本模块的 `read_bundle()` 是**纯函数**，不做缓存——同一份 bundle 只有一个家。

提示词正文分层查找：客户包优先，基座 `core/prompts/base/agent/` 兜底。
客户包 `index.yaml` 照旧声明**全部键**（契约不变），但文件可以只在基座里——
通用方法论只留一份，客户包只放客户专属文本。来源由 `provenance()` 暴露。

字节口径（改任何一条都会让已落盘的 writer_prompt_fingerprint / policy_version 集体失效）：
  1 读文件一律 `read_bytes().decode('utf-8')`。**不用** `read_text`：它默认做通用换行翻译，
    会把 CRLF 静默改成 LF，从而把"文件已被 Windows 工具写成 CRLF"这个事实掩盖掉；
    **也不用** `utf-8-sig`：它会静默吃掉 BOM。
  2 提示词文件正文 = 提示词全文 + 恰好一个结尾 LF；加载时剥掉一个（没有则不剥）。
  3 提示词本身不允许以 LF 结尾（否则第 2 条有歧义），由
    `tests/test_s5_prompt_registry.py::test_no_prompt_ends_with_newline` 钉住。

失败一律 fail fast（缺文件/编码错/结构不符都抛 `PromptBundleError`），**不回落任何内置默认值**：
回落等于把刚拆掉的"第二份真相"再装回去，而且会让 G-PROMPTS 在一份残缺的包上照样变绿。
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from core.packages import context as _context
from core.packages import registry as _packages


class PromptBundleError(RuntimeError):
    """提示词包不可读或缺项（缺 index.yaml/roles.yaml/*.md、编码错、结构不符）。"""


_INDEX_KEYS = ('agent_prompts', 'template_policy', 'report_prompt_profiles', 'default_prompt_profile')
_ROLE_FIELDS = ('responsibility', 'boundary', 'output')

#: legacy 显式注入槽的「未注入」哨兵。用哨兵而不是 `None`，是为了保留旧语义：
#: 旧用例把 `_package_dir` 置成 `None` 时要求 `package_not_configured`（显式未配置 ≠ 走包解析）。
_UNSET = object()
_package_dir: object = _UNSET

#: 基座提示词根：仓库内 `core/prompts/base/`（与包内 `<prompts>/` 同构，`agent/<key>.md` 相对路径一致）
BASE_DIR = Path(__file__).resolve().parent / 'base'


def configure(package_dir: Path) -> None:
    """绑定客户包并校验**这一个**包（读盘 + 结构校验），包不对就在启动期炸。

    只许启动期 / 子进程初始化期调用。**不要**在循环里对 N 个包调用它
    （100 包 ≈ 7.69 s；别的包等首次使用时按需加载）。
    """
    _context.bind(Path(package_dir).name, Path(package_dir))
    read_bundle(Path(package_dir))


def _load(package: str | None = None):
    """解析目标包：legacy 槽优先（仅当显式注入过），否则走包上下文。"""
    if package is None and _package_dir is not _UNSET:
        if _package_dir is None:
            raise RuntimeError('package_not_configured')
        return _packages.load_directory(Path(_package_dir))
    return _packages.load(package)


def _text(path: Path, label: str) -> str:
    """按字节读再解码：禁通用换行翻译、禁 BOM 消化（见模块 docstring 口径 1）。"""
    try:
        return path.read_bytes().decode('utf-8')
    except OSError as exc:
        raise PromptBundleError('prompt_unreadable:' + label) from exc
    except UnicodeDecodeError as exc:
        raise PromptBundleError('prompt_not_utf8:' + label) from exc


def _yaml(path: Path, label: str) -> Any:
    try:
        return yaml.safe_load(_text(path, label))
    except yaml.YAMLError as exc:
        raise PromptBundleError('prompt_yaml_invalid:' + label) from exc


def _resolve(base: Path, rel: str, key: str) -> tuple[str, str]:
    """分层解析：客户包优先，基座兜底；返回 (全文, 来源)，来源 ∈ {'package', 'base'}。

    两级都缺才 `prompt_missing`——**不回落任何内置默认值**（口径同上）。
    `rel` 是 index.yaml 里的相对路径（当前均为 `agent/<key>.md`），两级用同一相对路径，
    基座目录因此与包内 `<prompts>/` 同构。
    """
    pkg_file = base / rel
    if pkg_file.is_file():
        return _text(pkg_file, key), 'package'
    base_file = BASE_DIR / rel
    if base_file.is_file():
        return _text(base_file, key), 'base'
    raise PromptBundleError('prompt_missing:' + key)


def read_bundle(package_dir: Path) -> dict[str, Any]:
    """纯函数：读并校验一个包的提示词 bundle（**不缓存**，缓存归 `PackageLoad`）。"""
    package_dir = Path(package_dir)
    from core.manifest import load_manifest

    base = package_dir / load_manifest(package_dir).prompts
    index = _yaml(base / 'index.yaml', 'index.yaml')
    if not isinstance(index, dict):
        raise PromptBundleError('prompt_yaml_invalid:index.yaml')
    missing = [key for key in _INDEX_KEYS if key not in index]
    if missing:
        raise PromptBundleError('prompt_index_missing_keys:' + ','.join(missing))
    declared = index['agent_prompts']
    if not isinstance(declared, dict) or not declared:
        raise PromptBundleError('prompt_index_invalid:agent_prompts')
    prompts: dict[str, str] = {}
    sources: dict[str, str] = {}
    for key, rel in declared.items():
        if not isinstance(key, str) or not isinstance(rel, str):
            raise PromptBundleError('prompt_index_invalid:agent_prompts')
        text, source = _resolve(base, rel, key)
        prompts[key] = text[:-1] if text.endswith('\n') else text
        sources[key] = source
    roles = _yaml(base / 'roles.yaml', 'roles.yaml')
    if not isinstance(roles, dict) or not roles:
        raise PromptBundleError('prompt_roles_invalid:roles.yaml')
    for role_id, spec in roles.items():
        if not isinstance(spec, dict) or set(spec) != set(_ROLE_FIELDS):
            raise PromptBundleError('prompt_role_invalid:' + str(role_id))
        if not all(isinstance(spec[field], str) for field in _ROLE_FIELDS):
            raise PromptBundleError('prompt_role_invalid:' + str(role_id))
    policy = index['template_policy']
    if not isinstance(policy, dict):
        raise PromptBundleError('prompt_index_invalid:template_policy')
    profiles = index['report_prompt_profiles']
    if not isinstance(profiles, dict) or not profiles:
        raise PromptBundleError('prompt_index_invalid:report_prompt_profiles')
    for name, overrides in profiles.items():
        if not isinstance(overrides, dict):
            raise PromptBundleError('prompt_profile_invalid:' + str(name))
    default = index['default_prompt_profile']
    if not isinstance(default, str) or default not in profiles:
        raise PromptBundleError('prompt_profile_invalid:default_prompt_profile')
    return {'prompts': prompts, 'sources': sources, 'roles': roles,
            'template_policy': policy, 'report_profiles': profiles,
            'default_profile': default}


def prompts(package: str | None = None) -> dict[str, str]:
    """键 → 提示词全文（副本；键序 = index.yaml 声明序）。"""
    return dict(_load(package).agent_prompts)


def provenance(package: str | None = None) -> dict[str, str]:
    """键 → 实际来源：'package'（客户包文件）或 'base'（基座兜底；顺序 = 声明序）。"""
    return dict(_load(package).prompt_sources)


def roles(package: str | None = None) -> dict[str, dict[str, str]]:
    """角色 id → {responsibility, boundary, output}（副本；顺序 = roles.yaml 声明序）。"""
    return {role_id: dict(spec) for role_id, spec in _load(package).roles.items()}


def template_policy(package: str | None = None) -> dict[str, Any]:
    """模板分析策略（深拷贝：键序即语义，见 app/model_client.py 的非排序 json.dumps）。"""
    return deepcopy(_load(package).template_policy)


def report_profiles(package: str | None = None) -> dict[str, dict[str, str]]:
    """报告提示词 profile → 覆盖项（深拷贝；空 profile 保持 `{}` 而不是 `None`）。"""
    return deepcopy(_load(package).report_profiles)


def default_profile(package: str | None = None) -> str:
    """默认 profile 名（必须 ∈ report_profiles()，加载期已校验）。"""
    return _load(package).default_profile
