"""`/api/templates/{id}/definition` 对 `.doc` 基准报告的残留缺陷回归。

为什么单开一个文件：
    `test_doc97.py` 钉读取器契约、`test_doc97_fixes.py` 钉四个下游绕过点。这里钉的是
    **模板确认页的主接口**（`/definition`）以及它上游的模板构建：`.doc` 作为基准报告时，
    版式（`layout_source`）不是 OOXML ZIP，最旧的实现让 `zipfile.BadZipFile` 冒到路由层
    变成 500，用户一进模板确认页就崩。

为什么 `.doc` 是「200 + 降级」而不是报错：
    definition 的主体（块 / 字段 / 图表实例 / schema）全部不依赖版式源文件。只读版式的
    那一部分只有「图形数量」（`drawing_index` 的语义 = 模板 docx 里第 N 个图形）。`.doc`
    的图形是 OLE2 里的 EMF 对象，数量给不出来，于是图表清单降级为空并在返回体标记
    `layout_available=False`；坏 ZIP 不同——它是真错误，按 422 交回可指导文案。

`.docx` 的返回体必须逐字不变：`test_docx_definition_body_is_byte_identical_to_pre_change`
用**独立重放的改前逻辑**算出期望字节，与响应逐字节比对。
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.schemas import TaskState
from app.storage import Store
from core import chart_spec
from core.charts import registry
from core.structured_template import build_structured_template
from core.tools.template_compare import parse_report_document

REPO = Path(__file__).resolve().parents[1]
SAMPLE = Path(r'C:\Users\knwl\Desktop\国内研究室报告\月报\龙川月报\龙川县8月舆情月报.doc')
DOCX = REPO / 'templates' / 'anshun_monthly' / 'template-with-placeholders.docx'
requires_sample = pytest.mark.skipif(not SAMPLE.exists(), reason='样本 .doc 不在本机')

NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
BASIS = '用户确认的月报图形规则，可在模板审核时更换'


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _layout(tmp_path: Path, drawings: int = 5) -> Path:
    """只带 N 个 `<w:drawing>` 的最小版式 docx——`drawing_index` 的语义就来自它。"""
    path = tmp_path / f'layout-{drawings}.docx'
    body = '<w:body>' + '<w:drawing/>' * drawings + '</w:body>'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('word/document.xml', f'<w:document xmlns:w="{NS}">{body}</w:document>')
    return path


def _client(tmp_path: Path, monkeypatch, layout: Path) -> tuple[TestClient, str]:
    """一个已确认的模板任务：工件里**不带** `charts`，逼 `/definition` 真的去读版式。"""
    store = Store(tmp_path / 'store')
    ref = store.put_artifact('t', 'structured_template_candidate', {
        'status': 'confirmed_by_human',
        'source_reports': [{'path': str(layout), 'sha256': _sha(layout)}],
        'layout_source': str(layout)})
    store.put_task(TaskState(id='t', kind='template', phase='awaiting_review',
                             metadata={'confirmed_template_ref': ref}))
    monkeypatch.setattr(main, 'store', store)
    return TestClient(main.app, raise_server_exceptions=False), ref


# ------------------------------------------------------- 主缺陷：`.doc` 不再 500

@requires_sample
def test_legacy_doc_definition_returns_200_with_degraded_charts(tmp_path, monkeypatch):
    """`.doc` 基准报告 → 200（改前 500）；块/字段照常，图表清单降级为空并带标记。"""
    client, ref = _client(tmp_path, monkeypatch, SAMPLE)
    with client:
        response = client.get('/api/templates/t/definition')

    assert response.status_code == 200, response.text
    assert response.status_code != 500
    body = response.json()
    definition = body['definition']
    assert body['artifact_ref'] == ref
    assert definition['layout_available'] is False
    assert definition['charts'] == []
    assert definition['layout_source'] == str(SAMPLE)
    assert [Path(item['path']).name for item in definition['source_reports']] == [SAMPLE.name]


@requires_sample
def test_legacy_doc_base_builds_template_before_definition_is_served(tmp_path):
    """模板构建阶段（02 阶段入口）也必须过：改前 `build_structured_template` 在这里抛 BadZipFile。"""
    documents = [parse_report_document(str(SAMPLE)), parse_report_document(str(DOCX))]
    template = build_structured_template(documents, 'comparison')

    assert template['layout_source'] == str(SAMPLE)
    assert template['charts'] == []
    assert template['blocks']
    assert template['output_schema']['type'] == 'object'


# ------------------------------------------------------- `.docx`：逐字不变

def test_docx_definition_body_is_byte_identical_to_pre_change(tmp_path, monkeypatch):
    """`.docx` 的响应体必须与改前逐字节一致：期望值用**独立重放的改前逻辑**算出。"""
    layout = _layout(tmp_path, 5)
    client, ref = _client(tmp_path, monkeypatch, layout)
    with client:
        response = client.get('/api/templates/t/definition')
    assert response.status_code == 200, response.text

    # 改前逻辑的重放：读 zip 里的 drawing 数量 + 7 键投影（不从被测实现里取期望值）。
    with zipfile.ZipFile(layout) as archive:
        drawings = archive.read('word/document.xml').count(b'<w:drawing')
    charts = [{'id': item['id'], 'drawing_index': index + 1, 'title': item['title'],
               'style': item['style'], 'style_basis': BASIS, 'scope': item['scope'],
               'unit': item['unit']}
              for index, item in enumerate(registry.charts()[:drawings])]
    expected = {
        'revision': 0,
        'artifact_ref': ref,
        'definition': {                     # 工件 JSON 按 sort_keys 落盘，charts 由路由追加在末尾
            'layout_source': str(layout),
            'source_reports': [{'path': str(layout), 'sha256': _sha(layout)}],
            'status': 'confirmed_by_human',
            'charts': charts,
        },
        'model_review_validated': False,
        'local_definition': None,
        'questions': [],
    }
    assert len(charts) == 5
    expected_body = json.dumps(expected, ensure_ascii=False, separators=(',', ':')).encode()
    assert response.content == expected_body
    assert 'layout_available' not in response.json()['definition']


# ------------------------------------------------------- 坏源：4xx 且可指导

def test_broken_layout_source_is_422_with_actionable_detail(tmp_path, monkeypatch):
    """非 ZIP 非 OLE2 的版式源：改前 500；改后 422，文案指向「换成可读 .docx」。"""
    broken = tmp_path / 'broken.docx'
    broken.write_bytes(b'PK\x03\x04 truncated, not a real zip')
    client, _ref = _client(tmp_path, monkeypatch, broken)
    with client:
        response = client.get('/api/templates/t/definition')

    assert response.status_code == 422, response.text
    detail = response.json()['detail']
    assert detail.startswith('template_layout_unavailable:')
    assert '.docx' in detail and broken.name in detail


# ------------------------------------------------------- 实现层：异常类型收紧

@requires_sample
def test_definitions_degrades_legacy_doc_instead_of_raising(tmp_path):
    """直调 `.doc`：降级为空，不能是 `BadZipFile`（它不是 ValueError，路由层兜不住）。"""
    assert chart_spec.definitions({'layout_source': str(SAMPLE)}) == []
    assert chart_spec.layout_available({'layout_source': str(SAMPLE)}) is False


def test_definitions_raises_value_error_for_broken_zip(tmp_path):
    """坏 ZIP 是真错误：显式 ValueError（可被路由转 4xx），不是 `BadZipFile`。"""
    broken = tmp_path / 'broken.docx'
    broken.write_bytes(b'not a zip at all')
    with pytest.raises(ValueError, match='template_layout_unavailable'):
        chart_spec.definitions({'layout_source': str(broken)})
    assert chart_spec.layout_available({'layout_source': str(broken)}) is False


@requires_sample
def test_with_styles_on_legacy_doc_does_not_raise(tmp_path):
    """`chart-version` 走的是同一个 `definitions`——`.doc` 上也不能 500。"""
    changed = chart_spec.with_styles({'layout_source': str(SAMPLE)}, {'theme': 'barh'})
    assert changed['charts'] == []
