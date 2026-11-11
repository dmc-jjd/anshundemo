"""WP-S3-A：客户图表实例数据 + 基座图表实例注册表。

`core/charts/registry.py` 是客户实例数据的唯一读取口；这里锁住三件事：
id 清单与 manifest 声明不漂移、实例结构完整、family 与静态 `ChartStyles` 的样式集合同源。
"""

from __future__ import annotations

import re
from typing import get_args

import pytest

from app.chart_spec import ChartStyles
from app.config import PACKAGE_DIR
from core.charts import registry
from core.manifest import load_manifest

EXPECTED_IDS = ['sentiment', 'daily', 'platform', 'theme', 'locality']
REQUIRED_KEYS = {'id', 'title', 'draft_title', 'final_title', 'family', 'style',
                 'binding', 'unit', 'scope'}
FAMILY_STYLES = {'pie': {'pie', 'bar', 'barh'}, 'line': {'line', 'bar'},
                 'bar': {'pie', 'bar', 'barh'}, 'barh': {'pie', 'bar', 'barh'}}


def test_ids_match_manifest_declaration():
    """RISK-7：id 的两份清单（template.json 实例 vs manifest.yaml use）不许漂移。"""
    assert registry.ids() == EXPECTED_IDS
    assert set(registry.ids()) == set(load_manifest(PACKAGE_DIR).chart_use)


def test_every_instance_is_complete_and_bindable():
    assert len(registry.charts()) == len(EXPECTED_IDS)
    for item in registry.charts():
        assert REQUIRED_KEYS <= set(item), item['id']
        assert re.fullmatch(r'[a-z_]+\.[a-z_]+', item['binding']['source']), item['id']
        assert item['style'] in FAMILY_STYLES[item['family']], item['id']
    with pytest.raises(KeyError, match='unknown_chart_type:nope'):
        registry.chart('nope')


def test_unconfigured_registry_refuses_instead_of_falling_back():
    saved = registry._package_dir
    registry._package_dir = None
    try:
        with pytest.raises(RuntimeError, match='package_not_configured'):
            registry.ids()
    finally:
        registry._package_dir = saved


def test_family_maps_to_the_static_style_literals():
    """family 不是死数据：它必须与 `ChartStyles` 各字段的 Literal 集合逐一相等。"""
    for item in registry.charts():
        literal = set(get_args(ChartStyles.model_fields[item['id']].annotation))
        assert literal == FAMILY_STYLES[item['family']], item['id']
