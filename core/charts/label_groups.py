"""Optional chart label grouping declared on a chart instance, not in core defaults."""
from __future__ import annotations

def apply_label_groups(values, spec):
    if not spec:
        return values
    groups = list(spec.get("groups") or [])
    if not groups:
        return values
    leftover = dict(values)
    ordered = []
    seen = set()
    for item in groups:
        label = str(item.get("label") or "").strip()
        platforms = list(item.get("platforms") or [])
        if not label:
            raise ValueError("label_group_missing_label")
        if label in seen:
            raise ValueError("label_group_duplicate_label")
        seen.add(label)
        total = 0
        for name in platforms:
            total += int(leftover.pop(name, 0) or 0)
        ordered.append((label, total))
    other_label = str(spec.get("other_label") or "").strip()
    if other_label:
        rest = sum(int(n or 0) for n in leftover.values())
        if rest:
            ordered.append((other_label, rest))
    elif leftover:
        for name, count in leftover.items():
            ordered.append((name, int(count or 0)))
    return {label: count for label, count in ordered if count}
