"""客户包级「重点预警 / TOP10」开关：包级关 = 这个客户永远不做（硬约束）。

背景：`first_warning` / `top10` 原先只有模板级 `rules.features`，客户级 manifest 里
没有这两个键——客户说「我们永远不做 TOP10」时无处可配。这组用例钉住三层判据，
缺一层就又是「改了配置没生效」的假开关：

1. 包级声明真的读得出来：`manifest.features` 五项、两项新键 `enabled: true`；
2. `resolve_tools` 认识新键：`top10=false` → `select_materials` 退出白名单；
   `first_warning` 没有专属工具（预警只是 `filter_records` 的共用 scope），
   关掉它**不得**牵连 `filter_records`（否则正面/中性/负面口径一起停摆）；
3. 两层是**相与**：包级关 + 模板级开 → 给模型的清单里没有 TOP10 工具；
   包级开 + 模板级关同样没有（原有行为不变）；两层全开时与改前逐字一致。

全部走真实代码路径（真实 `Store`、真实工具子进程、真实报告图），只替换模型适配器
与「客户包清单读取」这一个接缝（`workflow._package_feature_switches`）：后者是包级
配置在宿主侧的唯一读口，替换它等价于换一个客户包清单。
"""
from __future__ import annotations

import pytest

import app.workflow as workflow
from app.config import PACKAGE_DIR
from core import manifest as manifest_module
from core.manifest import Manifest, load_manifest
from core.tools import registry
from test_template_processing_features import _run_report

ALL_ON = {'dedup': True, 'classification': True, 'first_warning': True, 'top10': True, 'locality': True}
TOP10_OFF = {**ALL_ON, 'top10': False}
TOP10_TOOLS = {'select_materials'}


def _package(**overrides):
    """客户包级开关；缺省全开（= 现状包），可按测试点关。"""
    base = {name: True for name in ALL_ON}
    base.update(overrides)
    return base


def test_manifest_declares_five_switches_all_on():
    """① 包级声明：五项，四个处理开关（含 first_warning / top10）全开。"""
    manifest = load_manifest(PACKAGE_DIR)

    assert set(manifest.features) == {'locality', 'event_classification', 'dedup',
                                      'first_warning', 'top10'}
    for key in ('first_warning', 'top10'):
        assert manifest.features[key] == {'enabled': True}


def test_resolve_tools_knows_top10_without_touching_shared_filter():
    """② `resolve_tools` 认识新键；first_warning 的空组是显式无操作。"""
    required = tuple(registry.CAPABILITY_TOOLS)

    on = registry.resolve_tools(required, {'top10': {'enabled': True}})
    off = registry.resolve_tools(required, {'top10': {'enabled': False}})
    assert TOP10_TOOLS <= on, '前提：开着时 TOP10 工具在白名单'
    assert not TOP10_TOOLS & off, '关掉后必须真的消失，否则就是假开关'

    warning_off = registry.resolve_tools(required, {'first_warning': {'enabled': False}})
    assert 'filter_records' in warning_off, (
        '预警范围是 filter_records 的共用 scope：关预警不能把整个筛选面停掉'
    )
    assert 'select_materials' in warning_off, '关预警不该牵连 TOP10'


def test_package_switch_mapping_treats_missing_key_as_off(monkeypatch):
    """包级读口：未声明 = 关，显式 enabled: true 才是开。"""
    def manifest_with(features):
        return Manifest(package='fake', report_type='x', version='1.0.0',
                        template='template.json', prompts='prompts', features=features)

    monkeypatch.setattr(manifest_module, 'load_manifest',
                        lambda package_dir: manifest_with({
                            'dedup': {'enabled': True},
                            'event_classification': {'enabled': True},
                            'first_warning': {'enabled': False},
                            'top10': {'enabled': False}}))
    assert workflow._package_feature_switches() == {'dedup': True, 'classification': True,
                                                    'first_warning': False, 'top10': False,
                                                    'locality': False}

    # 未写全五个开关 -> 缺的键视为关，不得静默全开
    monkeypatch.setattr(manifest_module, 'load_manifest',
                        lambda package_dir: manifest_with({}))
    assert workflow._package_feature_switches() == {name: False for name in ALL_ON}


def test_package_off_beats_template_on(tmp_path, monkeypatch):
    """③ 包级关 + 模板级开 → TOP10 工具不在给模型的清单里，也不被调用。"""
    seen, calls = [], []
    monkeypatch.setattr(workflow, '_package_feature_switches', lambda: _package(top10=False))

    state, events = _run_report(tmp_path, monkeypatch, ALL_ON, seen, calls)

    assert seen, '规划器没有被调用'
    assert not TOP10_TOOLS & set(seen[0])
    assert not TOP10_TOOLS & set(state['metadata']['available_tools'])
    assert not TOP10_TOOLS & set(calls), '白名单之外不该真被调用'
    feature_events = [event for event in events if event['type'] == 'processing_features']
    assert feature_events and feature_events[0]['top10'] is False, (
        '模板级开着时，生效开关必须已经被包级压成 False'
    )
    assert feature_events[0]['first_warning'] is True, '只关 top10 不该牵连其它开关'


def test_template_off_still_prunes_when_package_on(tmp_path, monkeypatch):
    """④ 包级开 + 模板级关 → 同样没有 TOP10 工具（原有行为不变）。"""
    seen, calls = [], []

    state, events = _run_report(tmp_path, monkeypatch, TOP10_OFF, seen, calls)

    assert seen, '规划器没有被调用'
    assert not TOP10_TOOLS & set(seen[0])
    assert not TOP10_TOOLS & set(state['metadata']['available_tools'])
    feature_events = [event for event in events if event['type'] == 'processing_features']
    assert feature_events and feature_events[0]['top10'] is False


def test_both_layers_on_keeps_the_pre_change_tool_list(tmp_path, monkeypatch):
    """⑤ 两层全开 → 工具清单与改前逐字一致（= capabilities 剪枝结果 − 规划器不可见工具）。"""
    seen, calls = [], []
    state, events = _run_report(tmp_path, monkeypatch, ALL_ON, seen, calls)

    available = state['metadata']['available_tools']
    expected = set(load_manifest(PACKAGE_DIR).policy.allow) - set(workflow._PLANNER_HIDDEN)
    assert set(available) == expected
    assert len(available) == len(expected)
    assert TOP10_TOOLS <= set(available)
    feature_events = [event for event in events if event['type'] == 'processing_features']
    assert feature_events and all(feature_events[0][name] is True for name in ALL_ON)


def test_locality_off_prunes_resolve_locality_but_keeps_filter_records():
    """locality:false 时白名单和保底步骤都没有 resolve_locality；不得牵连 filter_records。"""
    features = {**ALL_ON, 'locality': False}
    policy = workflow._processing_policy(features)
    assert 'resolve_locality' not in policy.allow
    assert 'filter_records' in policy.allow
    assert 'resolve_locality' in workflow._disabled_steps(features)
    assert 'filter_records' not in workflow._disabled_steps(features)


def test_locality_on_keeps_resolve_locality():
    policy = workflow._processing_policy(ALL_ON)
    assert 'resolve_locality' in policy.allow
    assert 'resolve_locality' not in workflow._disabled_steps(ALL_ON)


def test_ruyuan_manifest_matches_closed_locality():
    from core import paths
    from core.packages import package_context

    with package_context('ruyuan_yuebao'):
        manifest = load_manifest(paths.package_dir())
    assert manifest.features['locality']['enabled'] is False
    assert 'resolve_locality' not in set(manifest.policy.allow)
    assert 'locality' not in set(manifest.required_capabilities)


def test_closed_locality_packages_effective_tools_exclude_resolve_locality():
    """即使龙川 manifest 尚未整理 allow，生效白名单和保底步骤也不再包含属地工具。"""
    from core import paths
    from core.packages import package_context
    from core.tools.registry import CAPABILITY_TOOLS, resolve_tools

    for package in ('ruyuan_yuebao', 'longchuan_yuebao'):
        with package_context(package):
            switches = workflow._package_feature_switches()
            assert switches['locality'] is False
            features = {key: {'enabled': switches[name]} for name, key in workflow._FEATURE_SWITCHES.items()}
            resolved = resolve_tools(tuple(CAPABILITY_TOOLS), features)
            assert 'resolve_locality' not in resolved
            named = {name: switches[name] for name in workflow._FEATURE_SWITCHES}
            assert 'resolve_locality' in workflow._disabled_steps(named)
