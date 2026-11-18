from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace

import pytest

from core.packages import registry
from core.tools import vocabulary
from core.tools.records import import_records


def _xlsx(headers, rows, sheet_index: int):
    def cell(col, row, value):
        return f'<c r="{chr(65 + col)}{row}" t="inlineStr"><is><t>{value}</t></is></c>'

    body = "".join(
        f'<row r="{i}">' + "".join(cell(j, i, v) for j, v in enumerate(row)) + "</row>"
        for i, row in enumerate([headers] + rows, 1)
    )
    xml = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{body}</sheetData></worksheet>"
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(f"xl/worksheets/sheet{sheet_index}.xml", xml)
    return out.getvalue()


class _CaptureStore:
    def put_artifact(self, task_id, kind, payload):
        self.payload = payload
        return "captured"


def test_sheet_index_reads_package_contract():
    assert vocabulary.sheet_index("anshun_monthly") == 3
    assert vocabulary.sheet_index("demo_b") == 3
    assert vocabulary.sheet_index("ruyuan_yuebao") == 1
    assert vocabulary.sheet_index("longchuan_yuebao") == 1


def test_sheet_index_missing_key_fails(monkeypatch):
    monkeypatch.setattr(vocabulary, "_contract", lambda: {})
    with pytest.raises(ValueError, match="sheet_index_not_configured"):
        vocabulary.sheet_index()


def test_catalog_exposes_contract_sheet_index():
    entries = {item["package"]: item for item in registry.catalog()}
    assert entries["anshun_monthly"]["sheet_index"] == 3
    assert entries["demo_b"]["sheet_index"] == 3
    assert entries["ruyuan_yuebao"]["sheet_index"] == 1
    assert entries["longchuan_yuebao"]["sheet_index"] == 1


def test_import_records_without_sheet_index_uses_anshun_contract(tmp_path):
    path = tmp_path / "anshun.xlsx"
    path.write_bytes(_xlsx(["标题", "舆情调性"], [["示例", "正面"]], 3))
    ctx = SimpleNamespace(store=_CaptureStore(), package="anshun_monthly", task_id="t-sheet")
    result = import_records({"path": str(path)}, ctx)
    assert result.status == "ok"
    assert len(ctx.store.payload["records"]) == 1


def test_import_records_without_sheet_index_uses_ruyuan_contract(tmp_path):
    columns = vocabulary.required_columns("ruyuan_yuebao")
    path = tmp_path / "ruyuan.xlsx"
    path.write_bytes(_xlsx(columns, [["示例"] + [""] * (len(columns) - 1)], 1))
    ctx = SimpleNamespace(store=_CaptureStore(), package="ruyuan_yuebao", task_id="t-sheet")
    result = import_records({"path": str(path)}, ctx)
    assert result.status == "ok"
    assert len(ctx.store.payload["records"]) == 1


def test_workflow_sheet_index_prefers_metadata_then_contract():
    from app.workflow import _sheet_index

    assert _sheet_index(SimpleNamespace(metadata={"sheet_index": 5}, package="ruyuan_yuebao")) == 5
    assert _sheet_index(SimpleNamespace(metadata={}, package="ruyuan_yuebao")) == 1
    assert _sheet_index(SimpleNamespace(metadata={}, package="anshun_monthly")) == 3
