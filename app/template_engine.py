"""Template engine type: slot_template vs structured_template, declared by package."""
from __future__ import annotations

SLOT_TEMPLATE='slot_template'
STRUCTURED_TEMPLATE='structured_template'

def _builtin_entries(package=None):
    try:
        from core.packages import load_package
        return tuple(getattr(load_package(package).manifest,'builtin_templates',()) or ())
    except Exception:
        return ()

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
    declared=_declared_engine(template_ref,package)
    if declared:
        return declared
    try:
        from core.packages.registry import discover
        for name in discover():
            if package and name==package:
                continue
            declared=_declared_engine(template_ref,name)
            if declared:
                return declared
    except Exception:
        pass
    return STRUCTURED_TEMPLATE

def is_slot_template(template_ref,package=None):
    return template_engine(template_ref,package)==SLOT_TEMPLATE
