"""Template engine type: slot_template vs structured_template, declared by package."""
from __future__ import annotations

SLOT_TEMPLATE='slot_template'
STRUCTURED_TEMPLATE='structured_template'

def _builtin_entries(package=None):
    from core.task_package import resolve_task_package
    package=resolve_task_package(package)
    from core.packages import load_package
    return tuple(getattr(load_package(package).manifest,'builtin_templates',()) or ())

def builtin_templates(package=None):
    """当前包声明的内置模板库条目（不含 engine 键，响应形状与原基线条目一致）。"""
    items=[]
    for raw in _builtin_entries(package):
        item={key:value for key,value in dict(raw).items() if key!='engine'}
        if item.get('id'):
            items.append(item)
    return items

def _declared_engine(template_ref,package=None):
    if not template_ref:
        return None
    for raw in _builtin_entries(package):
        if str(raw.get('id') or '')==str(template_ref):
            return str(raw.get('engine') or SLOT_TEMPLATE)
    return None

def template_engine(template_ref,package=None):
    """返回 `slot_template` 或 `structured_template`。未在包内声明为槽位引擎的引用走结构化路径。"""
    return _declared_engine(template_ref,package) or STRUCTURED_TEMPLATE

def is_slot_template(template_ref,package=None):
    return template_engine(template_ref,package)==SLOT_TEMPLATE



def report_store_for_package(store, package=None):
    """Validate the configured storage boundary before either template engine.

    Only the requested package is opened on a PackageStores host. A legacy
    unbound Store remains supported; an explicitly different owner is rejected.
    """
    from core.task_package import resolve_task_package
    package = resolve_task_package(package, store=store)
    target = store.store_for(package) if hasattr(store, 'store_for') else store
    owned = getattr(target, 'package', None)
    if isinstance(owned, str) and owned.strip() and owned.strip() != package:
        raise ValueError('template_package_mismatch')
    return target


def report_template(store, template_ref, package=None, *, allow_legacy_builtin=False):
    """Resolve only this package's declaration/artifact, never discovery as permission.

    HTTP creation retains its confirmed-template requirement. Existing internal
    legacy tasks may omit a reference when their package declares one default
    slot template; packages without such a declaration fail explicitly.
    """
    from core.task_package import resolve_task_package
    from .structured_template import load_confirmed_template, TemplateArtifactUnavailable
    package = resolve_task_package(package, store=store)
    target = report_store_for_package(store, package)
    ref = str(template_ref or "").strip()
    if not ref and allow_legacy_builtin:
        entries = [entry for entry in _builtin_entries(package)
                   if entry.get('engine', SLOT_TEMPLATE) == SLOT_TEMPLATE]
        if len(entries) == 1:
            ref = str(entries[0]['id'])
    if not ref:
        raise ValueError('confirmed_two_report_template_required')
    if is_slot_template(ref, package):
        return ref, None
    try:
        return ref, load_confirmed_template(target, ref)
    except TemplateArtifactUnavailable:
        raise
    except (KeyError, ValueError, OSError) as exc:
        raise ValueError('confirmed_two_report_template_required') from exc


def validate_task_template(store, state, *, managed_only=False):
    """Check before writes. Legacy generic approval checks managed references only.

    No-ref historic writing keeps its existing generic behavior. Unmarked
    generic approval is not reinterpreted as a new structured-template format,
    but a reference present in the management library must be readable.
    """
    from core.task_package import resolve_task_package
    ref = getattr(state, 'template_ref', None)
    if not ref:
        return None
    package = resolve_task_package(state=state, store=store)
    target = report_store_for_package(store, package)
    if managed_only and not any(
        task.kind == 'template' and ref in (
            task.metadata.get('confirmed_template_ref'), task.metadata.get('structured_template_ref'))
        for task in target.list_tasks()
    ):
        return None
    _, definition = report_template(store, ref, package)
    return definition
