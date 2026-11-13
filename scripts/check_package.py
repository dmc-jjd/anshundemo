#!/usr/bin/env python
"""PKG-CHECK 客户包接入自检：把「新客户包能不能跑」变成机械判定。

为什么需要：
    `core/prompts/base/接入新客户.md` 第七章的自检命令此前是「check_package.py 待建」，
    新客户接入的最后一步只能靠人看。本脚本用七段判据
    （FILES / MANIFEST / TEMPLATE / PROMPTS / ROLES / AGENTS / LOAD）逐项判定，
    失败给可定位的句子，通过给一行 PKG-OK。

为什么不 import app/core（自举污染）：
    自检工具若 import app，就会在「同一个进程里已经被 configure 过的注册表」上判定包，
    坏包也可能因为旧状态而通过。所以本脚本只读文件；「真能加载吗」交给子进程里的
    `import app` 回答（LOAD 段）。

常量从源码读，不抄第二份（抄一份 = 第二个真相 = 必然漂移）：
    REQUIRED_MANIFEST_KEYS  core/ports.py              ast 读模块级赋值
    _ROLE_FIELDS            core/prompts/registry.py   ast 读模块级赋值
    CAPABILITY_TOOLS 键集   core/tools/registry.py     ast 读模块级赋值（键）
    FEATURE_TOOLS 键集      core/tools/registry.py     ast 读模块级赋值（键）
    图表可用名              core/charts/spec.py        ast 读 ChartStyles 的字段名
    features 允许键          core/tools/registry.py + core/classify/assemble.py
                            扫描 `<receiver>.get("字面量")`（receiver = config / raw）：
                            「哪个键真被读」只有调用点知道，所以只能从调用点取。
                            receiver=config → feature 级键（enabled / stages）
                            receiver=raw    → stage 级键（kind / enabled / confidence_threshold / options）
                            新增消费者时把文件加进 FEATURE_SOURCES / STAGE_SOURCES。
    读不到一律 fail-closed（报「无法从基座源码读取常量」并退出 1），绝不静默用内置副本。

YAML 用 PyYAML 解析（仓库既有依赖 requirements.txt: pyyaml==6.0.3，脚本跑同一个解释器）：
锚点 `&` / 别名 `*`、标签、跨行 flow、多行纯量续写都是**合法** YAML，客户包用了就必须照读，
所以不自己写子集解析器（子集会把合法写法误判成坏包，还要跟着 YAML 规范长期维护）。
`safe_load` 会静默让重复键的后者覆盖前者，故解析后另走一遍节点树把重复键的带路径清单
收集出来，交给 MANIFEST / PROMPTS / ROLES 段既有的重复键判据报错（不新增判据）。

用法：
    python scripts/check_package.py --package anshun_monthly
    python scripts/check_package.py --package demo_b
    python scripts/check_package.py --all
    python scripts/check_package.py --package .conda/neg1/anshun_monthly   # 造错包自测

退出码：0 = 全部 PKG-OK；1 = 有 PKG-FAIL（含包目录不存在）。
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
PACKAGES = REPO / 'packages'
TEMPLATES = REPO / 'templates'
BASE_PROMPTS = REPO / 'core' / 'prompts' / 'base'

#: features 键的读取点（见 docstring「常量从源码读」）。新增消费者时在此追加。
FEATURE_SOURCES = ('core/tools/registry.py', 'core/classify/assemble.py')
STAGE_SOURCES = ('core/classify/assemble.py',)

LOAD_TIMEOUT_S = 120

TEMPLATE_TOP_KEYS = ('package', 'version', 'data_contract', 'vocabulary', 'charts')
DATA_CONTRACT_KEYS = ('sheet_index', 'required_columns', 'summary_columns', 'column_map')


# --------------------------------------------------------------------------- #
# 基座常量：从源码读（fail-closed）
# --------------------------------------------------------------------------- #


class SpecError(RuntimeError):
    """基座源码里读不到权威常量（不允许用内置副本顶替）。"""


def _module_ast(rel: str) -> ast.Module:
    path = REPO / rel
    try:
        source = path.read_text(encoding='utf-8')
    except OSError as exc:
        raise SpecError(f'读不到 {rel}: {exc}') from exc
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise SpecError(f'{rel} 语法错误: {exc}') from exc


def _module_literal(rel: str, name: str) -> Any:
    """模块级 `NAME = <字面量>` 的值（不扫函数内部，避免同名局部量顶替）。"""
    for node in _module_ast(rel).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
        elif (isinstance(node, ast.AnnAssign)
              and isinstance(node.target, ast.Name)
              and node.target.id == name
              and node.value is not None):
            return ast.literal_eval(node.value)
    raise SpecError(f'{rel} 里找不到模块级常量 {name}')


def _get_literal_keys(rel: str, receivers: frozenset[str]) -> tuple[str, ...]:
    """扫 `<receiver>.get("字面量")`，取 receiver 恰好是已知变量名的调用键。"""
    keys: list[str] = []
    for node in ast.walk(_module_ast(rel)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        func = node.func
        if func.attr != 'get' or not isinstance(func.value, ast.Name):
            continue
        if func.value.id not in receivers:
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        key = node.args[0].value
        if isinstance(key, str) and key not in keys:
            keys.append(key)
    return tuple(keys)


def load_constants() -> dict[str, tuple[str, ...]]:
    """一次读齐六份权威常量；任何一份读不到都抛 SpecError。"""
    manifest_keys = tuple(str(k) for k in _module_literal('core/ports.py', 'REQUIRED_MANIFEST_KEYS'))
    role_fields = tuple(str(k) for k in _module_literal('core/prompts/registry.py', '_ROLE_FIELDS'))
    capability_tools = _module_literal('core/tools/registry.py', 'CAPABILITY_TOOLS')
    feature_tools = _module_literal('core/tools/registry.py', 'FEATURE_TOOLS')

    feature_keys: list[str] = []
    for rel in FEATURE_SOURCES:
        for key in _get_literal_keys(rel, frozenset({'config'})):
            if key not in feature_keys:
                feature_keys.append(key)
    stage_keys: list[str] = []
    for rel in STAGE_SOURCES:
        for key in _get_literal_keys(rel, frozenset({'raw'})):
            if key not in stage_keys:
                stage_keys.append(key)
    if not feature_keys:
        raise SpecError('读不到 features 允许键（' + ' / '.join(FEATURE_SOURCES) +
                        ' 里没有 `config.get("…")`）')
    if not stage_keys:
        raise SpecError('读不到 stages 允许键（' + ' / '.join(STAGE_SOURCES) +
                        ' 里没有 `raw.get("…")`）')

    chart_names: tuple[str, ...] = ()
    for node in _module_ast('core/charts/spec.py').body:
        if isinstance(node, ast.ClassDef) and node.name == 'ChartStyles':
            chart_names = tuple(
                t.target.id for t in node.body
                if isinstance(t, ast.AnnAssign) and isinstance(t.target, ast.Name)
            )
            break
    if not chart_names:
        raise SpecError('core/charts/spec.py 里找不到 ChartStyles 的字段名')

    return {
        'manifest_keys': manifest_keys,
        'role_fields': role_fields,
        'capabilities': tuple(str(k) for k in capability_tools),
        'feature_names': tuple(str(k) for k in feature_tools),
        'feature_keys': tuple(feature_keys),
        'stage_keys': tuple(stage_keys),
        'charts': chart_names,
    }


# --------------------------------------------------------------------------- #
# YAML（PyYAML）：读不到 / 语法错 = 解析失败；重复键另行收集
# --------------------------------------------------------------------------- #


class YamlError(ValueError):
    """YAML 读不到或语法错误（由各段报 FAIL，不猜内容）。"""


def _yaml_first_line(exc: yaml.YAMLError) -> str:
    """异常首行（MarkedYAMLError 的 str 是多行：context / 位置 / problem）。"""
    for line in str(exc).strip().splitlines():
        if line.strip():
            return line.strip()
    return type(exc).__name__


def _yaml_duplicate_keys(root: yaml.Node | None) -> list[str]:
    """重复键的带路径清单。

    PyYAML 的 safe_load 静默让后者覆盖前者，等于把配置错误变成静默错值；
    节点树里两侧键都还在，所以走一遍节点树就能把重复键找回来（判据不变）。
    """
    dups: list[str] = []
    seen: set[int] = set()

    def walk(node: yaml.Node, path: str) -> None:
        if id(node) in seen:          # 别名可能指向同一节点：只走一次
            return
        seen.add(id(node))
        if isinstance(node, yaml.MappingNode):
            keys: set[str] = set()
            for key_node, value_node in node.value:
                key = str(key_node.value) if isinstance(key_node, yaml.ScalarNode) else '?'
                child = f'{path}.{key}' if path else key
                if key in keys:
                    dups.append(child)
                keys.add(key)
                walk(value_node, child)
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                walk(item, path)

    if root is not None:
        walk(root, '')
    return dups


def load_yaml(path: Path) -> tuple[Any, list[str]]:
    """读并解析一份 YAML；失败一律抛 YamlError（消息自带文件名与 YAML 异常首行）。"""
    try:
        text = path.read_text(encoding='utf-8-sig')   # BOM 容忍：Windows 编辑器常写 BOM
    except OSError as exc:
        raise YamlError(f'YAML 解析失败 {path.name}: 读不到文件: {exc}') from exc
    loader = yaml.SafeLoader(text)
    try:
        root = loader.get_single_node()
        data = loader.construct_document(root) if root is not None else None
    except yaml.YAMLError as exc:
        raise YamlError(f'YAML 解析失败 {path.name}: {_yaml_first_line(exc)}') from exc
    finally:
        loader.dispose()
    return data, _yaml_duplicate_keys(root)


# --------------------------------------------------------------------------- #
# JSON（重复键必须可见：json.loads 会静默吃掉重复键，等于把配置错误变成静默错值）
# --------------------------------------------------------------------------- #


class _JsonObj(dict):
    def __init__(self) -> None:
        super().__init__()
        self.dups: list[str] = []


def _json_child_dups(value: Any) -> list[str]:
    if isinstance(value, _JsonObj):
        return list(value.dups)
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_json_child_dups(item))
        return out
    return []


def _json_hook(pairs: list[tuple[str, Any]]) -> _JsonObj:
    obj = _JsonObj()
    for key, value in pairs:
        if key in obj:
            obj.dups.append(key)
        obj[key] = value
    for key, value in pairs:
        for child in _json_child_dups(value):
            obj.dups.append(f'{key}.{child}')
    return obj


class JsonError(ValueError):
    """template.json（或其他 JSON）不可读。"""


def load_json_strict(path: Path) -> tuple[Any, list[str]]:
    try:
        raw = path.read_text(encoding='utf-8-sig')
    except OSError as exc:
        raise JsonError(f'读不到 {path.name}: {exc}') from exc
    try:
        data = json.loads(raw, object_pairs_hook=_json_hook)
    except json.JSONDecodeError as exc:
        raise JsonError(f'{path.name} JSON 语法错误: 第 {exc.lineno} 行第 {exc.colno} 列: {exc.msg}') from exc
    dups = _json_child_dups(data)
    return data, dups


# --------------------------------------------------------------------------- #
# 报告结构
# --------------------------------------------------------------------------- #


@dataclass
class Section:
    name: str
    status: str                      # ok / FAIL / skip
    detail: str = ''
    display: str | None = None       # 整行右侧文本（FILES 的 "4/4 ok" 用）
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _ok(name: str, detail: str = '', notes: list[str] | None = None,
        display: str | None = None) -> Section:
    return Section(name, 'ok', detail=detail, display=display, notes=list(notes or ()))


def _skip(name: str, detail: str = '') -> Section:
    return Section(name, 'skip', detail=detail)


def _fail(name: str, errors: list[str], notes: list[str] | None = None) -> Section:
    if not errors:
        errors = ['未知错误（内部断言）']
    return Section(name, 'FAIL', errors=list(errors), notes=list(notes or ()))


def print_report(name: str, sections: list[Section]) -> int:
    print(f'PKG-CHECK {name}')
    total = 0
    for sec in sections:
        label = f'  {sec.name:<13}'
        if sec.display is not None:
            print(label + sec.display)
        elif sec.status == 'ok':
            print(label + 'ok' + (f'  ({sec.detail})' if sec.detail else ''))
        elif sec.status == 'skip':
            print(label + 'skip' + (f'  ({sec.detail})' if sec.detail else ''))
        else:
            print(label + 'FAIL')
            for err in sec.errors:
                print(f'    - {err}')
            total += len(sec.errors)
        for note in sec.notes:
            print(f'    {note}')
    if total:
        print(f'PKG-FAIL {name}  ({total} errors)')
    else:
        print(f'PKG-OK {name}')
    return total


# --------------------------------------------------------------------------- #
# 单项检查
# --------------------------------------------------------------------------- #


class PackageCheck:
    """一个客户包的检查上下文：manifest 只读一次，各段共用。"""

    def __init__(self, pkg_dir: Path, consts: dict[str, tuple[str, ...]]):
        self.dir = pkg_dir
        self.name = pkg_dir.name
        self.consts = consts
        self.manifest_data: Any = None
        self.manifest_error: str | None = None
        self.manifest_dups: list[str] = []
        self.template_path = pkg_dir / 'template.json'
        self.prompts_dir = pkg_dir / 'prompts'
        self.roles: list[str] | None = None
        self._read_manifest()

    def _read_manifest(self) -> None:
        path = self.dir / 'manifest.yaml'
        if not path.is_file():
            self.manifest_error = 'manifest.yaml 缺失'
            return
        try:
            data, dups = load_yaml(path)
        except YamlError as exc:
            self.manifest_error = str(exc)
            return
        self.manifest_data = data
        self.manifest_dups = dups


def _inside(root: Path, rel: str) -> Path | None:
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def check_files(c: PackageCheck) -> Section:
    if not c.dir.is_dir():
        return _fail('FILES', [f'包目录不存在: {c.dir}'])
    template_rel = 'template.json'
    prompts_rel = 'prompts'
    problems: list[str] = []
    data = c.manifest_data
    if isinstance(data, dict):
        if isinstance(data.get('template'), str) and data['template'].strip():
            template_rel = data['template'].strip().replace('\\', '/').lstrip('/')
        if isinstance(data.get('prompts'), str) and data['prompts'].strip():
            prompts_rel = data['prompts'].strip().replace('\\', '/').strip('/') or 'prompts'

    template_path = _inside(c.dir, template_rel)
    if template_path is None:
        problems.append(f'manifest.template 指向包外: {template_rel}')
        template_path = c.dir / 'template.json'
        template_rel = 'template.json'
    prompts_path = _inside(c.dir, prompts_rel)
    if prompts_path is None:
        problems.append(f'manifest.prompts 指向包外: {prompts_rel}')
        prompts_path = c.dir / 'prompts'
        prompts_rel = 'prompts'
    c.template_path = template_path
    c.prompts_dir = prompts_path

    files = [
        ('manifest.yaml', c.dir / 'manifest.yaml'),
        (template_rel, c.template_path),
        (f'{prompts_rel}/index.yaml', c.prompts_dir / 'index.yaml'),
        (f'{prompts_rel}/roles.yaml', c.prompts_dir / 'roles.yaml'),
    ]
    present = 0
    for label, path in files:
        if path.is_file():
            present += 1
        else:
            problems.append(f'缺少 {label}')
    if problems:
        return _fail('FILES', problems)
    return _ok('FILES', display=f'{present}/{len(files)} ok')


def check_manifest(c: PackageCheck) -> Section:
    errs: list[str] = []
    if c.manifest_error is not None:
        if c.manifest_error == 'manifest.yaml 缺失':
            return _skip('MANIFEST', 'manifest.yaml 缺失（见 FILES）')
        return _fail('MANIFEST', [c.manifest_error])
    data = c.manifest_data
    if not isinstance(data, dict):
        return _fail('MANIFEST', ['manifest.yaml 顶层必须是映射（键: 值）'])

    for path in c.manifest_dups:
        errs.append(f'manifest.yaml 重复键: {path}')

    missing = [key for key in c.consts['manifest_keys'] if not data.get(key)]
    if missing:
        errs.append('缺少必需键: ' + ','.join(missing) +
                    f'（core/ports.py:REQUIRED_MANIFEST_KEYS 要求 {",".join(c.consts["manifest_keys"])}）')

    declared_package = data.get('package')
    if declared_package is not None and str(declared_package) != c.name:
        errs.append(f'package 值与目录名不一致: manifest={declared_package!r}, 目录={c.name!r}'
                    '（REPORT_PACKAGE 按目录名找包）')

    features = data.get('features')
    feature_order: list[str] = []
    if features is not None:
        if not isinstance(features, dict):
            errs.append('features 必须是映射（feature 名 → 配置）')
        else:
            allowed_feature = set(c.consts['feature_keys'])
            allowed_stage = set(c.consts['stage_keys'])
            for fname, fcfg in features.items():
                feature_order.append(str(fname))
                if fname not in c.consts['feature_names']:
                    errs.append(f'features.{fname} 没有代码消费者'
                                f'（已登记的 feature: {",".join(c.consts["feature_names"])}）')
                if not isinstance(fcfg, dict):
                    errs.append(f'features.{fname} 必须是映射')
                    continue
                for key in fcfg:
                    if key == 'enable':
                        errs.append(f'features.{fname}.enable 不是合法键'
                                    f'（少一个 d，应为 enabled）')
                    elif key not in allowed_feature:
                        errs.append(f'features.{fname}.{key} 不是代码读取的键'
                                    f'（允许: {",".join(c.consts["feature_keys"])}）')
                if 'stages' in fcfg:
                    stages = fcfg['stages']
                    if not isinstance(stages, list):
                        errs.append(f'features.{fname}.stages 必须是数组')
                    else:
                        for idx, stage in enumerate(stages, 1):
                            if not isinstance(stage, dict):
                                errs.append(f'features.{fname}.stages[{idx}] 必须是映射')
                                continue
                            for key in stage:
                                if key not in allowed_stage:
                                    errs.append(
                                        f'features.{fname}.stages[{idx}].{key} 不是代码读取的键'
                                        f'（允许: {",".join(c.consts["stage_keys"])}）')
                            kind = stage.get('kind')
                            if not isinstance(kind, str) or not kind.strip():
                                errs.append(f'features.{fname}.stages[{idx}] 缺 kind')

    caps = data.get('capabilities')
    if caps is not None:
        if not isinstance(caps, dict):
            errs.append('capabilities 必须是映射')
        else:
            require = caps.get('require')
            if require is not None and not isinstance(require, list):
                errs.append('capabilities.require 必须是数组')
            elif require:
                for cap in require:
                    if cap not in c.consts['capabilities']:
                        errs.append(f'capabilities.require 未注册的能力: {cap}'
                                    f'（已注册: {",".join(c.consts["capabilities"])}）')

    charts = data.get('charts')
    if charts is not None:
        if not isinstance(charts, dict):
            errs.append('charts 必须是映射（pack / use）')
        else:
            use = charts.get('use')
            if use is not None and not isinstance(use, list):
                errs.append('charts.use 必须是数组')
            elif use:
                for item in use:
                    if item not in c.consts['charts']:
                        errs.append(f'charts.use 未注册: {item}'
                                    f'（已注册: {",".join(c.consts["charts"])}）')

    agents = data.get('agents')
    if agents is not None and not isinstance(agents, list):
        errs.append('agents 必须是数组（角色 id 列表）')

    if errs:
        return _fail('MANIFEST', errs)
    detail = 'features: ' + (','.join(feature_order) if feature_order else '-')
    return _ok('MANIFEST', detail)


def check_template(c: PackageCheck) -> Section:
    if not c.template_path.is_file():
        return _skip('TEMPLATE', 'template.json 缺失（见 FILES）')
    try:
        data, dups = load_json_strict(c.template_path)
    except JsonError as exc:
        return _fail('TEMPLATE', [str(exc)])
    if not isinstance(data, dict):
        return _fail('TEMPLATE', ['template.json 顶层必须是对象'])

    errs: list[str] = []
    for path in dups:
        if path.startswith('vocabulary.cluster_terms.'):
            label = path[len('vocabulary.cluster_terms.'):]
            errs.append(f'cluster_terms label 重复: {label}')
        else:
            errs.append(f'template.json 重复键: {path}')

    missing = [key for key in TEMPLATE_TOP_KEYS if key not in data]
    if missing:
        errs.append('缺少顶层键: ' + ','.join(missing))

    columns = 0
    contract = data.get('data_contract')
    if not isinstance(contract, dict):
        errs.append('data_contract 必须是映射')
    else:
        for key in DATA_CONTRACT_KEYS:
            if key not in contract:
                errs.append(f'data_contract 缺少 {key}')
        required = contract.get('required_columns')
        if not isinstance(required, list) or not all(
                isinstance(col, str) and col.strip() for col in required):
            errs.append('data_contract.required_columns 必须是非空字符串数组')
        column_map = contract.get('column_map')
        if not isinstance(column_map, dict):
            errs.append('data_contract.column_map 必须是映射（物理列名 → 逻辑列名）')
        else:
            columns = len(column_map)
            if isinstance(required, list):
                unmapped = [col for col in required
                            if isinstance(col, str) and col not in column_map]
                if unmapped:
                    errs.append('column_map 缺必需列映射: ' + ','.join(unmapped))

    localities = 0
    categories = 0
    vocabulary = data.get('vocabulary')
    if not isinstance(vocabulary, dict):
        errs.append('vocabulary 必须是映射（localities / cluster_terms）')
    else:
        loc = vocabulary.get('localities')
        if not isinstance(loc, dict) or not loc:
            errs.append('vocabulary.localities 必须是非空映射')
        else:
            localities = len(loc)
            for canonical, aliases in loc.items():
                if not isinstance(canonical, str) or not canonical.strip():
                    errs.append('localities 的 canonical 必须是非空字符串')
                if not isinstance(aliases, list):
                    errs.append(f'localities.{canonical} 的别名必须是 list[str]')
                    continue
                for idx, alias in enumerate(aliases, 1):
                    if not isinstance(alias, str):
                        errs.append(f'localities.{canonical} 第 {idx} 个别名不是字符串')
                    elif not alias.strip():
                        errs.append(f'localities.{canonical} 第 {idx} 个别名是空字符串')
        terms = vocabulary.get('cluster_terms')
        if not isinstance(terms, dict) or not terms:
            errs.append('vocabulary.cluster_terms 必须是非空映射')
        else:
            categories = len(terms)
            for label, words in terms.items():
                if not isinstance(label, str) or not label.strip():
                    errs.append('cluster_terms 的 label 必须是非空字符串')
                if not isinstance(words, list) or not words:
                    errs.append(f'cluster_terms.{label} 的词表必须是非空 list[str]')
                    continue
                for idx, word in enumerate(words, 1):
                    if not isinstance(word, str) or not word.strip():
                        errs.append(f'cluster_terms.{label} 第 {idx} 个词不是非空字符串')

    charts = data.get('charts')
    chart_count = 0
    if not isinstance(charts, list) or not charts:
        errs.append('charts 必须是非空数组（图表实例）')
    else:
        chart_count = len(charts)

    notes: list[str] = []
    slots = data.get('writer_slots')
    if slots is not None:
        if not isinstance(slots, list) or not all(
                isinstance(slot, str) and slot.strip() for slot in slots):
            errs.append('writer_slots 必须是非空字符串数组')
        else:
            # 模板目录按客户包隔离（宿主 `app/__init__.py` 用 `templates/<PACKAGE>/` 配置
            # `core.paths.template_dir()`），所以只认本包自己的那份占位符清单。
            template_manifest = TEMPLATES / c.name / 'report.template.json'
            if not template_manifest.is_file():
                notes.append(f'writer_slots: 该包没有 templates/{c.name}/ 目录'
                             f'（{template_manifest.relative_to(REPO).as_posix()} 不存在），'
                             f'{len(slots)} 个槽位未机械核对（跳过）')
            else:
                try:
                    manifest, _ = load_json_strict(template_manifest)
                except JsonError as exc:
                    errs.append(str(exc))
                else:
                    placeholders = manifest.get('placeholders') if isinstance(manifest, dict) else None
                    available = {
                        placeholder['id'] for placeholder in placeholders or []
                        if isinstance(placeholder, dict) and isinstance(placeholder.get('id'), str)
                    }
                    unknown = [slot for slot in slots if slot not in available]
                    if unknown:
                        errs.append('writer_slots 未在模板占位符中: ' + ','.join(unknown))
                    else:
                        notes.append(f'writer_slots: {len(slots)} 个槽位均在 '
                                     f'templates/{c.name}/report.template.json 的 placeholders 中')

    if errs:
        return _fail('TEMPLATE', errs, notes)
    detail = (f'{columns} columns, {localities} localities, '
              f'{categories} categories, {chart_count} charts')
    return _ok('TEMPLATE', detail, notes)


def check_prompts(c: PackageCheck) -> Section:
    path = c.prompts_dir / 'index.yaml'
    if not path.is_file():
        return _skip('PROMPTS', 'index.yaml 缺失（见 FILES）')
    try:
        data, dups = load_yaml(path)
    except YamlError as exc:
        return _fail('PROMPTS', [str(exc)])
    if not isinstance(data, dict):
        return _fail('PROMPTS', ['index.yaml 顶层必须是映射'])

    errs: list[str] = [f'index.yaml 重复键: {path}' for path in dups]
    declared = data.get('agent_prompts')
    base_n = 0
    overrides: list[str] = []
    if not isinstance(declared, dict) or not declared:
        errs.append('agent_prompts 必须是非空映射（key → agent/<key>.md）')
    else:
        for key, rel in declared.items():
            if not isinstance(rel, str) or not rel.strip():
                errs.append(f'agent_prompts.{key} 的值必须是相对路径字符串')
                continue
            rel = rel.strip().replace('\\', '/')
            if (c.prompts_dir / rel).is_file():
                overrides.append(str(key))
            elif (BASE_PROMPTS / rel).is_file():
                base_n += 1
            else:
                errs.append(f'提示词缺失: {key} → {rel}'
                            '（包内 prompts/ 与 core/prompts/base/ 都没有）')

    notes: list[str] = []
    if overrides:
        notes.append('overrides: ' + ', '.join(overrides))
    if errs:
        return _fail('PROMPTS', errs, notes)
    total = len(declared)
    return _ok('PROMPTS', f'{total} keys: {base_n} base + {len(overrides)} overrides', notes)


def check_roles(c: PackageCheck) -> Section:
    path = c.prompts_dir / 'roles.yaml'
    if not path.is_file():
        return _skip('ROLES', 'roles.yaml 缺失（见 FILES）')
    try:
        data, dups = load_yaml(path)
    except YamlError as exc:
        return _fail('ROLES', [str(exc)])
    if not isinstance(data, dict) or not data:
        return _fail('ROLES', ['roles.yaml 必须是「角色 id → 字段映射」的非空映射'])

    errs: list[str] = [f'roles.yaml 重复角色: {path}' for path in dups]
    c.roles = [str(role) for role in data]
    fields = set(c.consts['role_fields'])
    for role, spec in data.items():
        if not isinstance(spec, dict):
            errs.append(f'角色 {role} 必须是映射')
            continue
        for key in spec:
            if key not in fields:
                errs.append(f'角色 {role} 多出字段 {key}'
                            f'（core/prompts/registry.py:_ROLE_FIELDS = {",".join(c.consts["role_fields"])}）')
        for key in c.consts['role_fields']:
            if key not in spec:
                errs.append(f'角色 {role} 缺字段 {key}')
                continue
            value = spec[key]
            if not isinstance(value, str) or not value.strip():
                errs.append(f'角色 {role}.{key} 必须是非空字符串')
    if errs:
        return _fail('ROLES', errs)
    return _ok('ROLES', f'{len(data)} roles')


def check_agents(c: PackageCheck) -> Section:
    data = c.manifest_data
    if not isinstance(data, dict):
        return _skip('AGENTS', 'manifest.yaml 不可用（见 MANIFEST）')
    agents = data.get('agents')
    if not agents:
        return _skip('AGENTS', '未声明 agents:（全部角色参与）')
    if not isinstance(agents, list):
        return _skip('AGENTS', 'agents 不是数组（见 MANIFEST）')
    if c.roles is None:
        return _skip('AGENTS', 'roles.yaml 不可用，无法核对 agents（见 ROLES）')
    known = set(c.roles)
    declared = [str(agent) for agent in agents if agent]
    unknown = [agent for agent in declared if agent not in known]
    if unknown:
        return _fail('AGENTS', [
            f'agents 声明了 roles.yaml 没有的角色: {agent}' for agent in unknown
        ])
    return _ok('AGENTS', f'{len(declared)} declared, all in roles.yaml')


def check_load(c: PackageCheck) -> Section:
    canonical = (PACKAGES / c.name).resolve() == c.dir.resolve()
    if not canonical:
        try:
            shown = c.dir.relative_to(REPO).as_posix()
        except ValueError:
            shown = str(c.dir)
        return _skip('LOAD', f'包目录 {shown} 不是 packages/{c.name}，'
                             'REPORT_PACKAGE 无法指向它（真正起包请用 --package ' + c.name + '）')
    env = dict(os.environ)
    env['REPORT_PACKAGE'] = c.name
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    try:
        proc = subprocess.run(
            [sys.executable, '-c', 'import app'],
            cwd=str(REPO), env=env, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=LOAD_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return _fail('LOAD', [f'import app 超时（>{LOAD_TIMEOUT_S}s）'])
    if proc.returncode == 0:
        return _ok('LOAD', 'import app in subprocess')
    errors = [f'import app 退出码 {proc.returncode}（REPORT_PACKAGE={c.name}）']
    stderr_tail = [line.strip() for line in (proc.stderr or '').splitlines() if line.strip()][-8:]
    errors.extend(stderr_tail or [f'stderr 为空；stdout 尾部: {(proc.stdout or "").strip()[-300:]}'])
    return _fail('LOAD', errors)


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #


def check_package(pkg_dir: Path, consts: dict[str, tuple[str, ...]]) -> list[Section]:
    check = PackageCheck(pkg_dir, consts)
    if not pkg_dir.is_dir():
        return [_fail('FILES', [f'包目录不存在: {pkg_dir}'])]
    return [
        check_files(check),
        check_manifest(check),
        check_template(check),
        check_prompts(check),
        check_roles(check),
        check_agents(check),
        check_load(check),
    ]


def resolve_targets(raw: str | None, all_packages: bool) -> list[Path]:
    if all_packages:
        if not PACKAGES.is_dir():
            return []
        return sorted(
            (item for item in PACKAGES.iterdir()
             if item.is_dir() and not item.name.startswith(('.', '_'))),
            key=lambda item: item.name,
        )
    assert raw is not None
    direct = Path(raw)
    if direct.is_dir():
        return [direct.resolve()]
    candidate = PACKAGES / raw
    return [candidate.resolve() if candidate.exists() else candidate]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='客户包接入自检（PKG-CHECK）：结构 / manifest / template / prompts / 可加载性')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--package', help='包名（packages/<name>）或包目录路径')
    group.add_argument('--all', action='store_true', help='检查 packages/ 下所有包')
    args = parser.parse_args(argv)

    try:
        consts = load_constants()
    except SpecError as exc:
        print(f'[error] 无法从基座源码读取常量: {exc}', file=sys.stderr)
        return 1

    targets = resolve_targets(args.package, args.all)
    if not targets:
        print(f'[error] packages/ 下没有客户包: {PACKAGES}', file=sys.stderr)
        return 1

    failed = 0
    for pkg_dir in targets:
        sections = check_package(pkg_dir, consts)
        if print_report(pkg_dir.name, sections):
            failed += 1
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
