"""客户包清单加载：基座读 manifest.yaml 与 template.json，不 import `app/`。

为什么不校验 `manifest.prompts` 指向的目录：S2 期该目录尚不存在也不需要存在，
`ports.REQUIRED_MANIFEST_KEYS` 只要求键非空；目录落地属 S5。
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
    return Manifest.from_mapping(data)


def load_template(package_dir: Path) -> dict[str, Any]:
    """读 manifest 的 `template` 字段指向的 JSON 模板。"""
    path = Path(package_dir) / load_manifest(package_dir).template
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageError(f'template_unreadable:{path.name}') from exc
