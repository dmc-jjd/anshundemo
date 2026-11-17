from __future__ import annotations

import io, zipfile
from types import SimpleNamespace

from core.tools import vocabulary
from core.tools.records import import_records
from app.api_views.task_resume import display_name, template_display_index


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


def test_import_records_keeps_rows_when_only_summary_column_is_empty(tmp_path, monkeypatch):
    """只有一列摘要、且部分行为空时，不能再因 summary_columns[1] 下标越界而整表导入失败。"""
    monkeypatch.setattr(vocabulary, 'summary_columns', lambda package=None: ['摘要'])
    path = tmp_path / 'empty-summary.xlsx'
    path.write_bytes(_xlsx(
        ['标题', '舆情调性', '摘要'],
        [['有摘要的标题', '负面', '这段摘要'], ['空摘要标题', '正面', '']],
    ))
    captured = {}

    class Store:
        def put_artifact(self, task_id, kind, payload):
            captured['payload'] = payload
            return 'ref'

    result = import_records({'path': str(path), 'sheet_index': 3}, SimpleNamespace(store=Store(), package=None, task_id='t-summary'))
    records = captured['payload']['records']
    assert result.status == 'ok'
    assert len(records) == 2
    assert records[0]['summary'] == '这段摘要'
    assert records[0]['title'] == '有摘要的标题'
    assert records[1]['summary'] == ''
    assert records[1]['title'] == '空摘要标题'


def test_template_display_index_uses_confirmed_task_name_when_library_misses():
    report = SimpleNamespace(
        kind='report',
        template_ref='template_version-missing',
        metadata={'report_month': '2026-10', 'report_issue': 10, 'report_date': ''},
    )
    template = SimpleNamespace(
        kind='template',
        metadata={'confirmed_template_ref': 'template_version-missing', 'template_name': '示例县月报V1'},
    )
    empty = SimpleNamespace(kind='report', template_ref='template_version-missing', metadata={})

    class Store:
        def list_tasks(self):
            return [template, empty]

    index = template_display_index(Store(), [])
    assert display_name(report, index).startswith('示例县月报V1')
    assert 'template_version-missing' not in display_name(report, index)
