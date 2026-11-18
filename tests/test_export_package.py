# -*- coding: utf-8 -*-
"""Package export maps: Anshun cover/slots stay, other packages do not inherit Anshun names."""
from __future__ import annotations

from pathlib import Path

from app.export import template_values
from app.storage import Store


def _values(tmp_path, package, metrics=None, draft=None, facts_extra=None):
    store = Store(tmp_path / "store")
    metrics = metrics or {
        "record_count": 10000,
        "sentiment": {"正面": 1000, "中性": 2000, "负面": 7000},
        "platform": {
            "移动客户端": 10, "网站": 20, "微信公众号": 30, "视频": 40,
            "微博": 50, "纸媒": 60, "电视": 70, "互动栏目": 80,
        },
        "peak_day": "2026-10-15",
    }
    ref = store.put_artifact("t", "metrics", metrics)
    facts = {
        "package": package,
        "report_month": "2026-10",
        "result_refs": {"calculate_metrics": ref},
    }
    if facts_extra:
        facts.update(facts_extra)
    return template_values(draft or {}, facts, store=store)


def test_anshun_export_cover_platforms_and_peak(tmp_path):
    values = _values(tmp_path, "anshun_monthly")
    assert values["B5_COVER"] == "2026年第10期"
    assert values["B12_COVER"] == "安顺市2026年10月网络舆情分析报告"
    assert values["B17_RED_01"] == "1.00"
    assert values["B17_RED_02"] == "1000"
    assert values["B17_RED_03"] == "10.00"
    assert values["B17_RED_04"] == "2000"
    assert values["B17_RED_05"] == "20.00"
    assert values["B17_RED_06"] == "7000"
    assert values["B17_RED_07"] == "70.00%"
    assert values["B26_RED_01"] == "10"
    assert values["B29_RED_01"] == "10"
    assert values["B17_RED_08"] == "10月15日"
    assert values["B26_MAGENTA_02"] == "移动客户端、网站、微信公众号、视频、微博、纸媒、电视、互动栏目平台"
    assert values["B26_MAGENTA_03"] == "移动客户端"
    assert values["B26_RED_04"] == "10"
    assert values["B26_RED_05"] == "0.10"
    assert values["B26_MAGENTA_21"] == "电视"
    assert values["B26_MAGENTA_26"] == "互动栏目"
    # 互动栏目 overwrites TV count/percent slots, then appends %.
    assert values["B26_RED_22"] == "80"
    assert values["B26_RED_23"] == "0.80%"
    assert "西秀区" not in values.values()  # no dedup workbook, localities not filled
    assert values["B12_COVER"].startswith("安顺市")


def _xlsx(headers, rows, sheet_index=1):
    import io, zipfile

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


def test_anshun_export_fills_configured_localities(tmp_path):
    path = tmp_path / "dedup.xlsx"
    path.write_bytes(_xlsx(
        ["区县", "事件分类"],
        [["西秀区", "市场监管"], ["西秀区", "市场监管"], ["黄果树旅游区", "交通管理"], ["市区", "市场监管"]],
        1,
    ))
    values = _values(
        tmp_path,
        "anshun_monthly",
        facts_extra={"deduplicated_path": str(path), "deduplicated_sheet_index": 1},
    )
    assert values["B17_RED_10"] == "4"
    assert values["B17_RED_11"] == "0.04%"
    assert values["B30_RED_01"] == "4"
    assert values["B30_YELLOW_03"] == "市场监管"
    assert values["B17_YELLOW_12"] == "市场监管、交通管理"
    assert values["B30_RED_07"] == "1"  # 市区
    assert values["B30_RED_09"] == "2"  # 西秀区
    assert values["B30_RED_11"] == "1"  # 黄果树旅游区
    assert values["B30_RED_13"] == "0"  # 关岭县
    assert values["B12_COVER"] == "安顺市2026年10月网络舆情分析报告"


def test_other_packages_export_has_no_anshun_cover_or_districts(tmp_path):
    banned = ("安顺市", "西秀区", "西秀", "黄果树旅游区", "黄果树", "关岭县", "平坝区", "紫云县", "普定县", "镇宁县", "安顺经开区")
    for package in ("longchuan_yuebao", "ruyuan_yuebao"):
        values = _values(
            tmp_path / package,
            package,
            draft={"slot_values": {"SOME_SLOT": {"value": "包内槽位", "source_refs": ["r"]}}},
        )
        blob = " ".join(str(v) for v in values.values()) + " ".join(values)
        for word in banned:
            assert word not in blob, (package, word, values)
        assert "B12_COVER" not in values
        assert "B5_COVER" not in values
        assert values.get("SOME_SLOT") == "包内槽位"
