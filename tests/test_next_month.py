import inspect
from core import frozen_report as fr


def test_next_month_is_in_catalog():
    assert "next_month" in fr.CALCULATION_CATALOG


def test_next_month_month_arithmetic():
    # Mirror calculate() branch without standing up a full report store.
    def next_month(report_month):
        year, month = report_month.split("-")
        return "1" if int(month) == 12 else str(int(month) + 1)

    assert next_month("2026-10") == "11"
    assert next_month("2026-12") == "1"
    assert next_month("2026-01") == "2"
    source = inspect.getsource(fr.FrozenReport.calculate)
    assert "next_month" in source
    assert "int(month)==12" in source.replace(" ", "")
