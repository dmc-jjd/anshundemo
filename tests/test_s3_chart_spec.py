"""WP-S3-B：`chart_spec` 上移 `core/charts/spec.py`，`app/chart_spec.py` 收成注入壳。

锁住三件事：7 键投影逐字不变（模板工件字节不变）、截断语义不变、`DATA` 调用期注入未被切断（F2）。
"""

from __future__ import annotations

import zipfile

import pytest

import app.chart_spec as chart_spec
from core.charts.spec import DEFINITION_KEYS
from test_frozen_writer import fixture

BASIS = '用户确认的月报图形规则，可在模板审核时更换'


def _one_drawing_layout(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as document:
        document.writestr(
            'word/document.xml',
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:drawing/></w:body></w:document>',
        )
    return path


def test_definitions_project_exactly_seven_keys(tmp_path):
    _, template = fixture(tmp_path)
    definitions = chart_spec.definitions(template)
    assert definitions == [
        {'id': 'sentiment', 'drawing_index': 1, 'title': '舆情调性分布', 'style': 'pie',
         'style_basis': BASIS, 'scope': 'all_records', 'unit': '条'},
        {'id': 'daily', 'drawing_index': 2, 'title': '每日信息量', 'style': 'line',
         'style_basis': BASIS, 'scope': 'all_records', 'unit': '条'},
        {'id': 'platform', 'drawing_index': 3, 'title': '传播平台分布', 'style': 'pie',
         'style_basis': BASIS, 'scope': 'all_records', 'unit': '条'},
        {'id': 'theme', 'drawing_index': 4, 'title': '事件分类', 'style': 'bar',
         'style_basis': BASIS, 'scope': 'confirmed_events', 'unit': '件'},
        {'id': 'locality', 'drawing_index': 5, 'title': '事件涉及属地', 'style': 'barh',
         'style_basis': BASIS, 'scope': 'confirmed_events', 'unit': '件'},
    ]
    assert list(definitions[0]) == list(DEFINITION_KEYS)


def test_definitions_truncate_to_drawing_count(tmp_path):
    layout = _one_drawing_layout(tmp_path / 'layout.docx')
    definitions = chart_spec.definitions({'layout_source': str(layout)})
    assert [item['id'] for item in definitions] == ['sentiment']
    assert definitions[0]['drawing_index'] == 1


def test_styles_roundtrip_and_rejections(tmp_path):
    _, template = fixture(tmp_path)
    assert chart_spec.styles_for(template) == {'sentiment': 'pie', 'daily': 'line', 'platform': 'pie',
                                               'theme': 'bar', 'locality': 'barh'}
    changed = chart_spec.with_styles(template, {'theme': 'barh'})
    assert [item['style'] for item in changed['charts']] == ['pie', 'line', 'pie', 'barh', 'barh']
    assert changed['charts'][3]['style_basis'] == '人工选择'
    assert chart_spec.styles_for(changed)['theme'] == 'barh'
    with pytest.raises(ValueError):
        chart_spec.styles_for(template, {'daily': 'pie'})
    with pytest.raises(ValueError):
        chart_spec.styles_for(template, {'made_up': 'pie'})


def test_data_injection_is_still_read_at_call_time(tmp_path, monkeypatch):
    """F2：`DATA` 必须在**调用期**生效（core 不得模块级取 DATA）。

    WP-S8-L2：`chart_spec` 的实现已进 `core/chart_spec.py`，`DATA` 的家随之进 core——
    patch 必须打在**被读的模块**上；打 `app.chart_spec`（壳）只改壳的副本，静默失效（S8 §4.3）。
    判据不变：改 DATA 后 `definitions` 立刻跟着换根，说明它是调用期读而不是 import 期捕获。
    """
    import core.chart_spec as impl
    data_root = tmp_path / 'data'
    _one_drawing_layout(data_root / 'uploads' / 'layout.docx')
    monkeypatch.setattr(impl, 'DATA', data_root)
    stale = tmp_path / 'old-project' / 'data' / 'uploads' / 'layout.docx'
    definitions = chart_spec.definitions({'layout_source': str(stale)})
    assert [item['id'] for item in definitions] == ['sentiment']
