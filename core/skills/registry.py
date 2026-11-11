"""技能包注册表：按 manifest 的 `skills.use` 加载技能定义、校验上游指纹、动态加载检测入口。

与 `core/charts/registry.py` 同构：`app/__init__.py` 在首次 `import app.*` 时 `configure` 一次；
未配置就调用一律 `RuntimeError('package_not_configured')`，不静默回落默认值。

三层数据各自只有一个家：
  - 技能定义（kind / 资产清单 / 标签体系）→ `core/skills/<manifest.skills.pack>/<id>.json`
  - 上游指纹（name / upstream / commit / sha256）→ 技能资产目录的 `PROJECT-PROVENANCE.json`
  - 技能资产本体（SKILL.md / 判据 / detect.py）→ 由 `skills_root` 注入，本轮不移动

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

from core.manifest import load_manifest

SKILLS_DIR = Path(__file__).resolve().parent   # core/skills/
_package_dir: Path | None = None
_assets_root: Path | None = None


def configure(package_dir: Path, assets_root: Path) -> None:
    """绑定客户包与技能资产根目录，并预热默认风格技能（含指纹校验，资产不对就 import 期就炸）。"""
    global _package_dir, _assets_root
    _package_dir = Path(package_dir)
    _assets_root = Path(assets_root)
    _manifest(_package_dir)
    skill_context()


@lru_cache(maxsize=4)
def _manifest(package_dir: Path):
    return load_manifest(package_dir)


def _require_configured() -> tuple[Path, Path]:
    if _package_dir is None or _assets_root is None:
        raise RuntimeError('package_not_configured')
    return _package_dir, _assets_root


def _descriptor_path(skill_id: str) -> Path:
    package_dir, _ = _require_configured()
    pack = _manifest(package_dir).skill_pack
    if not pack:
        raise ValueError('manifest_missing_skill_pack')
    return SKILLS_DIR / pack / f'{skill_id}.json'


@lru_cache(maxsize=8)
def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def use() -> tuple[str, ...]:
    """客户包声明的技能 id（= manifest.skills.use 的声明序）。"""
    package_dir, _ = _require_configured()
    return _manifest(package_dir).skill_use


def ids() -> tuple[str, ...]:
    return use()


def resolvable() -> list[str]:
    """`use` 中真正带描述符（= 带资产）的技能。代码型技能（如 source-binding）会被跳过。

    `skills.use` 同时混装"有资产的技能"和"纯代码技能"（实测 F4），所以不能要求每个 id
    都有描述符，否则 `import app` 直接炸。
    """
    return [skill_id for skill_id in use() if _descriptor_path(skill_id).is_file()]


@lru_cache(maxsize=8)
def _descriptor(skill_id: str) -> dict[str, Any]:
    path = _descriptor_path(skill_id)
    if not path.is_file():
        raise KeyError('unknown_skill:' + skill_id)
    return json.loads(path.read_text(encoding='utf-8-sig'))


def descriptor(skill_id: str) -> dict[str, Any]:
    return json.loads(json.dumps(_descriptor(skill_id), ensure_ascii=False))


@lru_cache(maxsize=4)
def _style_id() -> str:
    found = [skill_id for skill_id in resolvable()
             if _descriptor(skill_id).get('kind') == 'style']
    if len(found) != 1:
        raise ValueError('style_skill_not_unique:' + ','.join(found))
    return found[0]


def style_skill() -> str:
    """唯一 `kind=='style'` 的技能 id。不是恰好一个就抛错——不猜。"""
    return _style_id()


def asset_dir(skill_id: str | None = None) -> Path:
    _, root = _require_configured()
    return root / (skill_id or style_skill())


def labels(skill_id: str | None = None) -> dict[str, list[str]]:
    """判据标签体系（4 组，键序即候选排列序）。返回副本，防调用方就地改。"""
    raw = _descriptor(skill_id or style_skill())['labels']
    return {kind: list(values) for kind, values in raw.items()}


@lru_cache(maxsize=8)
def _fingerprint(skill_id: str, root: str) -> str:
    spec = _descriptor(skill_id)
    base = Path(root) / skill_id
    order = (spec['assets']['skill'], spec['assets']['criteria'], spec['assets']['entry'])
    digest = hashlib.sha256(''.join(_read(base / rel) for rel in order).encode()).hexdigest()
    declared = json.loads(_read(base / spec['provenance']))['sha256']
    if digest != declared:
        raise ValueError('skill_fingerprint_mismatch:' + skill_id)
    return digest


def fingerprint(skill_id: str | None = None) -> str:
    """上游指纹：计算值，且必须等于 PROVENANCE 声明的值（不等即抛错，不静默用计算值）。"""
    _, root = _require_configured()
    return _fingerprint(skill_id or style_skill(), str(root))


@lru_cache(maxsize=8)
def _context(skill_id: str, root: str) -> dict[str, Any]:
    spec = _descriptor(skill_id)
    base = Path(root) / skill_id
    text = _read(base / spec['assets']['skill'])
    criteria = _read(base / spec['assets']['criteria'])
    provenance = json.loads(_read(base / spec['provenance']))
    return {'name': provenance['name'], 'upstream': provenance['upstream'],
            'commit': provenance['commit'], 'sha256': _fingerprint(skill_id, root),
            'rules': text[text.index(spec['rules_anchor']):],
            'semantic_criteria': criteria}


def skill_context(skill_id: str | None = None) -> dict[str, Any]:
    """技能上下文。**键集与键序必须与 S4 之前的 `app/style_skill.skill_context()` 完全一致**。"""
    _, root = _require_configured()
    return _context(skill_id or style_skill(), str(root))


@lru_cache(maxsize=8)
def _detector_module(skill_id: str, root: str) -> Any:
    spec = _descriptor(skill_id)
    path = Path(root) / skill_id / spec['assets']['entry']
    module_spec = importlib.util.spec_from_file_location(spec['module'], path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def detector(skill_id: str | None = None) -> Any:
    """动态加载技能入口模块（不写入 sys.modules；模块名取自描述符，**禁止 `'__main__'`**）。"""
    _, root = _require_configured()
    return _detector_module(skill_id or style_skill(), str(root))
