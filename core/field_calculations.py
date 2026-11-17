"""Package-declared calculation bindings for data fields.

A package may bind template field ids to catalog `Calculation` specs in
`calculations.yaml`, `template.json` (`field_calculations`), or
`manifest.yaml` (`field_calculations`). Later sources override earlier ones.

Bindings belong in the package, not in the hardcoded `KNOWN` map, so a new
client package can declare field calculations without changing the base.
"""
from __future__ import annotations

from typing import Any, Mapping


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def load(package: str | None = None) -> dict[str, dict]:
    """Return field-id → calculation spec for a package, or `{}`."""
    if not package:
        return {}
    try:
        from core.packages.registry import load as load_package
        loaded = load_package(package)
    except Exception:
        return {}
    data: dict[str, dict] = {}
    template = _as_dict(getattr(loaded, "template", None))
    for key in ("field_calculations", "calculations"):
        extra = template.get(key)
        if isinstance(extra, Mapping):
            data.update({str(k): dict(v) for k, v in extra.items() if isinstance(v, Mapping)})
    for name in ("calculations.yaml", "calculations.yml"):
        path = loaded.directory / name
        if not path.exists():
            continue
        try:
            import yaml
            raw = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
        except Exception:
            raw = {}
        if isinstance(raw, Mapping):
            data.update({str(k): dict(v) for k, v in raw.items() if isinstance(v, Mapping)})
        break
    try:
        import yaml
        manifest = yaml.safe_load((loaded.directory / "manifest.yaml").read_text(encoding="utf-8-sig")) or {}
        extra = _as_dict(manifest).get("field_calculations")
        if isinstance(extra, Mapping):
            data.update({str(k): dict(v) for k, v in extra.items() if isinstance(v, Mapping)})
    except Exception:
        pass
    return data
