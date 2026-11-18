# -*- coding: utf-8 -*-
"""Step 11: package file lookup, date column_map, create-task package alignment."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.packages_api import resolve_files
from core.tools.records import import_records


def _xlsx(headers, rows, sheet_index=1):
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


def test_resolve_files_does_not_borrow_default_uploads(tmp_path):
    default_dir = tmp_path / "anshun_uploads"
    other_dir = tmp_path / "other_uploads"
    default_dir.mkdir(); other_dir.mkdir()
    (default_dir / "abc.xlsx").write_bytes(b"anshun-only")

    class Store:
        def uploads_for(self, package):
            return other_dir if package == "longchuan_yuebao" else default_dir

    with pytest.raises(HTTPException) as exc:
        resolve_files(Store(), ["abc"], package="longchuan_yuebao", default=default_dir)
    assert exc.value.status_code == 404


def test_import_records_published_uses_column_map(tmp_path, monkeypatch):
    from core.tools import vocabulary

    contract = dict(vocabulary._contract_of("anshun_monthly"))
    contract["column_map"] = dict(contract["column_map"])
    contract["column_map"].pop("发布时间", None)
    contract["column_map"]["信息发布时间"] = "published"
    monkeypatch.setattr(vocabulary, "_contract_of", lambda package=None: contract)
    path = tmp_path / "dated.xlsx"
    path.write_bytes(_xlsx(
        ["标题", "舆情调性", "信息发布时间"],
        [["示例", "正面", "2026-10-08"]],
        3,
    ))
    captured = {}

    class Store:
        def put_artifact(self, task_id, kind, payload):
            captured["payload"] = payload
            return "ref"

    import_records(
        {"path": str(path), "sheet_index": 3},
        SimpleNamespace(store=Store(), package="anshun_monthly", task_id="t-date"),
    )
    assert captured["payload"]["records"][0]["published"] == "2026-10-08"
