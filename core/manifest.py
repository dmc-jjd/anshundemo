"""客户包清单加载：基座读 manifest.yaml 与 template.json，不 import `app/`。

为什么不校验 `manifest.prompts` 指向的目录：S2 期该目录尚不存在也不需要存在，
`ports.REQUIRED_MANIFEST_KEYS` 只要求键非空；目录落地属 S5。

`agents:` 的校验放在这里（启动期）：声明里出现 `roles.yaml` 没有的角色必须立刻失败，
不能等到建图时才报。角色清单只有 `roles.yaml` 是权威，所以本模块只按 manifest 的
`prompts` 前缀去读它——不 import 提示词注册表（避免 core 内部多一条 import 环）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from core.ports import Manifest


class PackageError(RuntimeError):
    """客户包不可读（缺 manifest.yaml、YAML 损坏、模板不是合法 JSON）。"""


def load_manifest(package_dir: Path) -> Manifest:
    """读 `package_dir/manifest.yaml`。缺必需键时原样抛 `ValueError: manifest_missing_keys:...`。"""
    path = Path(package_dir) / 'manifest.yaml'
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8-sig'))
    except (OSError, yaml.YAMLError) as exc:
        raise PackageError(f'manifest_unreadable:{path.name}') from exc
    if not isinstance(data, dict):
        raise PackageError(f'manifest_unreadable:{path.name}')
    manifest = Manifest.from_mapping(data)
    _validate_agents(Path(package_dir), manifest)
    return manifest


def declared_roles(package_dir: Path, prompts: str) -> tuple[str, ...] | None:
    """读 `<prompts>/roles.yaml` 的角色键序；文件不存在返回 None（由提示词注册表负责报错）。"""
    path = Path(package_dir) / prompts / 'roles.yaml'
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8-sig'))
    except (OSError, yaml.YAMLError) as exc:
        raise PackageError(f'roles_unreadable:{path.name}') from exc
    if not isinstance(data, dict):
        raise PackageError(f'roles_unreadable:{path.name}')
    return tuple(str(key) for key in data)


def _validate_agents(package_dir: Path, manifest: Manifest) -> None:
    """`agents:` 非空时逐条对照 `roles.yaml`；未声明（空）无需校验。"""
    if not manifest.agents:
        return
    known = declared_roles(package_dir, manifest.prompts)
    if known is None:
        raise PackageError(f'manifest_agents_unverifiable:{manifest.package}')
    from core.agent_steps import validate_declared_agents

    validate_declared_agents(manifest.agents, known)


def load_template(package_dir: Path) -> dict[str, Any]:
    """读 manifest 的 `template` 字段指向的 JSON 模板。"""
    path = Path(package_dir) / load_manifest(package_dir).template
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageError(f'template_unreadable:{path.name}') from exc
