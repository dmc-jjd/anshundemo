"""Package-configurable second-section policy. No client facts live here.

Packages may declare `section_two` in `template.json` and/or `manifest.yaml`.
When the block is absent, callers keep their built-in defaults.

Supported keys (all optional):

- `field_roles`: map of field id → `outlook` | `analysis` | `general`.
  An explicit entry wins over built-in heuristics. `general` means the field
  is not a second-section special path (use this to stop `paragraph_list`
  from being treated as outlook).
- `outlook_fields`: ordered field ids that together form one outlook set.
  When set, the writer validates `outlook_items` once and writes each item
  back to the corresponding field as a string.
- `outlook_item_count`: `{min, max}` for how many outlook items qualify
  (defaults stay with the caller, typically 4–5).
- `locality_evidence`:
  - `from_vocabulary` (bool): read evidence place names from this package's
    `vocabulary.localities` (keys and aliases). Does not enable the
    locality-statistics feature or `resolve_locality`.
  - `region`: region label for the forecast window and evidence-error text.
    If omitted while `from_vocabulary` is true, the first vocabulary key is used.
  - `names`: explicit evidence place names. Used as-is when present, so a
    package can keep a short-name list distinct from vocabulary keys.
  - `official_hosts`: hostname suffixes that may stand in for a local name
    in official-frequency citations. Omitted means no extra host exemption
    once vocabulary names are in use.
  - `evidence_label`: short label for evidence-error text. If omitted, `region` is used.
"""

from __future__ import annotations

from typing import Any, Mapping

_VALID_ROLES = frozenset({"outlook", "analysis", "general"})


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = _as_dict(base)
    extra = _as_dict(override)
    for key, value in extra.items():
        if key in {"field_roles", "locality_evidence", "outlook_item_count"} and isinstance(value, Mapping):
            merged[key] = {**_as_dict(merged.get(key)), **_as_dict(value)}
        else:
            merged[key] = value
    return merged


def load(package: str | None = None) -> dict[str, Any]:
    """Return optional policy; missing or unreadable packages are configuration errors."""
    from core.packages.registry import load as load_package
    from core.manifest import PackageError
    import yaml
    loaded = load_package(package)
    loaded.manifest  # Validate required manifest fields and declared agents first.
    def block(value):
        if value is None:return {}
        if not isinstance(value, Mapping):
            raise ValueError('section_two_must_be_mapping')
        return dict(value)
    template_cfg = block((loaded.template or {}).get("section_two"))
    try:
        raw = yaml.safe_load((loaded.directory / "manifest.yaml").read_text(encoding="utf-8-sig")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise PackageError('manifest_unreadable:manifest.yaml') from exc
    if not isinstance(raw, Mapping):raise PackageError('manifest_unreadable:manifest.yaml')
    return _merge(template_cfg, block(raw.get("section_two")))


def field_role(field: Mapping[str, Any], policy: Mapping[str, Any] | None, default_role: str | None = None) -> str | None:
    """Resolve a field's second-section role. Explicit `field_roles` win."""
    field_id = str(field.get("id") or "")
    declared = _as_dict((policy or {}).get("field_roles")).get(field_id)
    if declared is None and field_id:
        return default_role
    role = str(declared or "").strip()
    if not role or role == "general":
        return None
    if role not in _VALID_ROLES:
        raise ValueError(f"section_two.field_roles.{field_id} must be outlook, analysis, or general")
    return role


def outlook_field_ids(policy: Mapping[str, Any] | None) -> tuple[str, ...]:
    values = (policy or {}).get("outlook_fields") or ()
    return tuple(str(item) for item in values if item)


def outlook_item_bounds(policy: Mapping[str, Any] | None, default_min: int = 4, default_max: int = 5) -> tuple[int, int]:
    spec = _as_dict((policy or {}).get("outlook_item_count"))
    low = int(spec["min"]) if "min" in spec else default_min
    high = int(spec["max"]) if "max" in spec else default_max
    if low < 1 or high < low:
        raise ValueError("section_two.outlook_item_count must have min>=1 and max>=min")
    return low, high


def locality_evidence(policy: Mapping[str, Any] | None) -> dict[str, Any]:
    return _as_dict((policy or {}).get("locality_evidence"))


def uses_vocabulary_names(policy: Mapping[str, Any] | None) -> bool:
    return bool(locality_evidence(policy).get("from_vocabulary"))


def flatten_localities(vocab: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Preserve key-then-alias order; drop blanks and duplicates."""
    names: list[str] = []
    seen: set[str] = set()
    for key, aliases in (vocab or {}).items():
        sequence = [key, *(aliases or ())]
        for item in sequence:
            name = str(item).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
    return tuple(names)


def locality_names(policy: Mapping[str, Any] | None, *, package: str | None = None, fallback: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Place names for evidence checks. Vocabulary path does not start locality stats."""
    evidence = locality_evidence(policy)
    declared = evidence.get("names") or ()
    names = tuple(str(item).strip() for item in declared if str(item).strip())
    if names:
        return names
    if not uses_vocabulary_names(policy):
        return tuple(fallback)
    try:
        from core.tools import vocabulary
        vocab = vocabulary.localities(package)
    except Exception as exc:
        raise ValueError("section_two.locality_evidence.from_vocabulary requires vocabulary.localities") from exc
    names = flatten_localities(vocab)
    if not names:
        raise ValueError("section_two.locality_evidence.from_vocabulary found no locality names")
    return names


def region_name(policy: Mapping[str, Any] | None, *, package: str | None = None, fallback: str = "") -> str:
    evidence = locality_evidence(policy)
    if evidence.get("region"):
        return str(evidence["region"])
    if (policy or {}).get("region"):
        return str(policy["region"])
    if uses_vocabulary_names(policy):
        try:
            from core.tools import vocabulary
            keys = list(vocabulary.localities(package) or {})
        except Exception:
            keys = []
        if keys:
            return str(keys[0])
    return fallback


def evidence_label(policy: Mapping[str, Any] | None, *, package: str | None = None, fallback: str = "") -> str:
    evidence = locality_evidence(policy)
    if evidence.get("evidence_label"):
        return str(evidence["evidence_label"])
    return region_name(policy, package=package, fallback=fallback)


def official_hosts(policy: Mapping[str, Any] | None) -> tuple[str, ...]:
    evidence = locality_evidence(policy)
    hosts = evidence.get("official_hosts") or (policy or {}).get("official_hosts") or ()
    return tuple(str(item).strip().lower() for item in hosts if str(item).strip())


def host_matches(host: str, hosts: tuple[str, ...]) -> bool:
    value = (host or "").strip().lower()
    if not value or not hosts:
        return False
    for item in hosts:
        if value == item or value.endswith("." + item):
            return True
    return False
