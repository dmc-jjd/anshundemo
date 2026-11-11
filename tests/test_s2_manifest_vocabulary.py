from __future__ import annotations
import io,zipfile

import pytest

from app.config import PACKAGE_DIR
from app.storage import Store
from app.tool import REQUIRED_COLUMNS, import_records
from app.tool_executor import RunContext
from core.manifest import load_manifest
from core.ports import Manifest
from core.tools import vocabulary


def _xlsx(headers, rows):
    def cell(col, row, value):
        return f'<c r="{chr(65 + col)}{row}" t="inlineStr"><is><t>{value}</t></is></c>'
    body = ''.join(f'<row r="{i}">' + ''.join(cell(j, i, v) for j, v in enumerate(row)) + '</row>'
                   for i, row in enumerate([headers] + rows, 1))
    xml = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           f'<sheetData>{body}</sheetData></worksheet>')
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('xl/worksheets/sheet3.xml', xml)
    return out.getvalue()


def test_manifest_policy_comes_from_yaml():
    manifest = load_manifest(PACKAGE_DIR)
    assert manifest.package == 'anshun_monthly'
    assert manifest.policy.permits('import_records', 'processing') is None
    assert manifest.policy.budget('writing') == 80
    assert len(manifest.policy.phases['writing']) == 5


def test_manifest_missing_keys_fails_startup():
    with pytest.raises(ValueError, match='manifest_missing_keys'):
        Manifest.from_mapping({})


def test_cluster_terms_keep_source_order():
    terms = vocabulary.cluster_terms()
    assert len(terms) == 12
    assert list(terms)[0] == '交通管理'
    assert list(terms)[-1] == '自然灾害'


def test_required_columns_and_localities_come_from_template():
    assert vocabulary.required_columns() == ['标题', '舆情调性']
    assert len(vocabulary.localities()) == 8


def test_import_records_still_rejects_tables_missing_a_required_column(tmp_path):
    assert REQUIRED_COLUMNS == vocabulary.required_columns()
    path = tmp_path / 'only_title.xlsx'
    path.write_bytes(_xlsx(['标题'], [['只有标题的样本']]))
    ctx = RunContext(Store(tmp_path / 'data'), 's2a')
    with pytest.raises(ValueError) as exc:
        import_records({'path': str(path), 'sheet_index': 3}, ctx)
    assert str(exc.value) == 'missing_required_columns'


EXPECTED_RECORD_KEY_ORDER = [
    'id', 'title', 'published', 'source', 'author', 'source_id', 'category', 'url',
    'platform', 'media_attribute', 'media_level', 'sentiment', 'warning', 'summary', 'source_ref',
]


class _CaptureStore:
    """捕获构造期 payload：Store 落盘用 sort_keys=True，读回来键序恒为字母序，
    因此"字段序"只能在落盘前断言。"""

    def __init__(self):
        self.payload = None

    def put_artifact(self, task_id, kind, payload):
        self.payload = payload
        return 'captured'

    def get_artifact(self, ref):
        return self.payload


def test_import_records_keeps_field_order(tmp_path):
    """RISK-3：records 的字段插入序由 column_map 键序决定。

    注意：工件落盘时被 `sort_keys=True` 抹平，所以哈希门禁**检不出**字段序回退，
    这条测试是唯一防线。它断言的是构造期顺序，不是落盘后的顺序。
    """
    headers = ['标题', '发布时间', '来源信息', '作者', '作者Id', '事件分类',
               '网址', '媒体环节', '媒体属性', '媒体级别', '舆情调性', '是否预警', '摘要']
    row = ['样本标题', '46234', '来源', '作者', 'sid', '交通管理',
           'http://x', '微博', '自媒体', '省级', '负面', '是', '摘要内容']
    path = tmp_path / 'full.xlsx'
    path.write_bytes(_xlsx(headers, [row]))

    ctx = RunContext(_CaptureStore(), 's2a-order')
    import_records({'path': str(path), 'sheet_index': 3}, ctx)
    records = ctx.store.payload['records']

    assert list(records[0].keys()) == EXPECTED_RECORD_KEY_ORDER
    # 顺带守住 A 包最关键的一处语义：Excel 序列日期必须被转换，不能被展开语法覆盖回原始值
    assert records[0]['published'].startswith('20') and 'T' in records[0]['published']
