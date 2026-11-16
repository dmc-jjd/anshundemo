"""技能包注册表：按 manifest 的 `skills.use` 加载技能定义、校验上游指纹、动态加载检测入口。

三层数据各自只有一个家：
  - 技能定义（kind / 资产清单 / 标签体系）→ `core/skills/<manifest.skills.pack>/<id>.json`
  - 上游指纹（name / upstream / commit / sha256）→ 技能资产目录的 `PROJECT-PROVENANCE.json`
  - 技能资产本体（SKILL.md / 判据 / detect.py）→ 由 `assets_root` 注入，本轮不移动

三不变量（`core/packages/` 同一套）：
    ① 模块级「包派生常量」必须为零。**M1 修掉的正是这一类最阴的一处**：
       旧 `@lru_cache(maxsize=4) def _style_id() -> str:` 是**零参数**缓存——第一个包的答案
       永久生效，切包后 `style_skill()` / `skill_context()` / `labels()` 仍返回旧包的技能。
       现在 `_style_id(package)` 带包，且 `_descriptor(skill_id, package, path)` 的键里带
       描述符文件戳（键只有 `skill_id` 时，路径由包决定而键不含包 → 命中旧包缓存）；
    ② `configure()` 只许启动期 / 子进程初始化期调用，绝不许请求期切包；
    ③ `package` 不许进 artifact payload。

`assets_root` 是**部署级**目录（`skills/`，所有包共用），不是包派生值；它只保留
「显式注入 / 缺省推导 / 显式未配置」三态，不再随包变化。

指纹口径（改一个字都会让已落盘的 policy_version / 字段提示词指纹集体失效）：
    sha256( SKILL.md + semantic-criteria.md + detect.py )，utf-8，**无分隔符**，按此顺序。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from core import config as _config
from core.packages import registry as _packages

SKILLS_DIR = Path(__file__).resolve().parent   # core/skills/

#: legacy 显式注入槽的「未注入」哨兵（`None` = 显式未配置 → `package_not_configured`）。
_UNSET = object()
_package_dir: object = _UNSET
_assets_root: object = _UNSET


def configure(package_dir: Path, assets_root: Path) -> None:
    """绑定客户包与技能资产根目录，并校验默认风格技能（含指纹校验，资产不对就启动期炸）。

    只许启动期 / 子进程初始化期调用。
    """
    from core.packages import context as _context

    directory = Path(package_dir)
    _context.bind(directory.name, directory)
    global _assets_root
    _assets_root = Path(assets_root)
    _packages.load_directory(directory).manifest
    # 按**已绑定的目录**校验默认风格技能（package=None → 走 ContextVar，不再按名字回落仓库根）
    skill_context()


def _load(package: str | None = None):
    """解析目标包：legacy 槽优先（仅当显式注入过），否则走包上下文。"""
    if package is None and _package_dir is not _UNSET:
        if _package_dir is None:
            raise RuntimeError('package_not_configured')
        return _packages.load_directory(Path(_package_dir))
    return _packages.load(package)


def _assets() -> Path:
    """技能资产根（部署级）：显式注入 → 缺省 `ROOT/skills`；显式 `None` = 未配置。"""
    if _assets_root is None:
        raise RuntimeError('package_not_configured')
    if _assets_root is _UNSET:
        return _config.ROOT / 'skills'
    return Path(_assets_root)


def _descriptor_path(skill_id: str, package: str | None = None) -> Path:
    """描述符路径：由**该包** manifest 的 `skills.pack` 决定（不是全局包）。"""
    pack = _load(package).manifest.skill_pack
    if not pack:
        raise ValueError('manifest_missing_skill_pack')
    return SKILLS_DIR / pack / f'{skill_id}.json'


@lru_cache(maxsize=8)
def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


@lru_cache(maxsize=8)
def _descriptor(skill_id: str, package: str | None, packed: str) -> dict[str, Any]:
    """描述符（键 = 技能 id + 包 + 描述符路径，路径里已含 pack；`packed` 让键含实际文件）。

    键里带 `packed`（绝对路径）是必须的：路径由**包**决定（`manifest.skills.pack`），
    若键只有 `skill_id`，先读 A 包（pack-core）再读 B 包（另一 pack）会命中 A 的事实真相。
    """
    path = Path(packed)
    if not path.is_file():
        raise KeyError('unknown_skill:' + skill_id)
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _descriptor_of(skill_id: str, package: str | None = None) -> dict[str, Any]:
    path = _descriptor_path(skill_id, package)
    return _descriptor(skill_id, package, str(path))


def use(package: str | None = None) -> tuple[str, ...]:
    """客户包声明的技能 id（= manifest.skills.use 的声明序）。"""
    return _load(package).manifest.skill_use


def ids(package: str | None = None) -> tuple[str, ...]:
    return use(package)


def resolvable(package: str | None = None) -> list[str]:
    """`use` 中真正带描述符（= 带资产）的技能。代码型技能（如 source-binding）会被跳过。

    `skills.use` 同时混装"有资产的技能"和"纯代码技能"（实测 F4），所以不能要求每个 id
    都有描述符，否则 `import app` 直接炸。
    """
    return [skill_id for skill_id in use(package) if _descriptor_path(skill_id, package).is_file()]


def descriptor(skill_id: str, package: str | None = None) -> dict[str, Any]:
    return json.loads(json.dumps(_descriptor_of(skill_id, package), ensure_ascii=False))


def _style_id(package: str | None = None) -> str:
    """唯一 `kind=='style'` 的技能 id（**带包**；零参数缓存正是 M1 要清的 bug）。"""
    found = [skill_id for skill_id in resolvable(package)
             if _descriptor_of(skill_id, package).get('kind') == 'style']
    if len(found) != 1:
        raise ValueError('style_skill_not_unique:' + ','.join(found))
    return found[0]


def style_skill(package: str | None = None) -> str:
    """唯一 `kind=='style'` 的技能 id。不是恰好一个就抛错——不猜。"""
    return _style_id(package)


def asset_dir(skill_id: str | None = None, package: str | None = None) -> Path:
    return _assets() / (skill_id or style_skill(package))


def labels(skill_id: str | None = None, package: str | None = None) -> dict[str, list[str]]:
    """判据标签体系（4 组，键序即候选排列序）。返回副本，防调用方就地改。"""
    raw = _descriptor_of(skill_id or style_skill(package), package)['labels']
    return {kind: list(values) for kind, values in raw.items()}


@lru_cache(maxsize=8)
def _fingerprint(skill_id: str, root: str, package: str | None = None) -> str:
    spec = _descriptor_of(skill_id, package)
    base = Path(root) / skill_id
    order = (spec['assets']['skill'], spec['assets']['criteria'], spec['assets']['entry'])
    digest = hashlib.sha256(''.join(_read(base / rel) for rel in order).encode()).hexdigest()
    declared = json.loads(_read(base / spec['provenance']))['sha256']
    if digest != declared:
        raise ValueError('skill_fingerprint_mismatch:' + skill_id)
    return digest


def fingerprint(skill_id: str | None = None, package: str | None = None) -> str:
    """上游指纹：计算值，且必须等于 PROVENANCE 声明的值（不等即抛错，不静默用计算值）。"""
    return _fingerprint(skill_id or style_skill(package), str(_assets()), package)


@lru_cache(maxsize=8)
def _context(skill_id: str, root: str, package: str | None = None) -> dict[str, Any]:
    spec = _descriptor_of(skill_id, package)
    base = Path(root) / skill_id
    text = _read(base / spec['assets']['skill'])
    criteria = _read(base / spec['assets']['criteria'])
    provenance = json.loads(_read(base / spec['provenance']))
    return {'name': provenance['name'], 'upstream': provenance['upstream'],
            'commit': provenance['commit'], 'sha256': _fingerprint(skill_id, root, package),
            'rules': text[text.index(spec['rules_anchor']):],
            'semantic_criteria': criteria}


def skill_context(skill_id: str | None = None, package: str | None = None) -> dict[str, Any]:
    """技能上下文。**键集与键序必须与 S4 之前的 `app/style_skill.skill_context()` 完全一致**。"""
    resolved = skill_id or style_skill(package)
    return _context(resolved, str(_assets()), package)


@lru_cache(maxsize=8)
def _detector_module(skill_id: str, root: str, package: str | None = None) -> Any:
    spec = _descriptor_of(skill_id, package)
    path = Path(root) / skill_id / spec['assets']['entry']
    module_spec = importlib.util.spec_from_file_location(spec['module'], path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def detector(skill_id: str | None = None, package: str | None = None) -> Any:
    """动态加载技能入口模块（不写入 sys.modules；模块名取自描述符，**禁止 `'__main__'`**）。"""
    return _detector_module(skill_id or style_skill(package), str(_assets()), package)
