from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from output import build_html_report, build_rich_table, export_to_excel


def _sample_rows():
    absolute_rows = [
        {
            "Fund": "Benchmark",
            "Style": "",
            "is_benchmark": True,
            "error": False,
            "stale_days": 0,
            "latest_date": None,
            "MTD": 0.01,
            "3M": 0.02,
            "6M": 0.03,
            "12M": 0.04,
            "3Y": 0.05,
            "5Y": 0.06,
        },
        {
            "Fund": "Fund A",
            "Style": "growth",
            "is_benchmark": False,
            "error": False,
            "stale_days": 0,
            "latest_date": None,
            "MTD": 0.02,
            "3M": 0.03,
            "6M": 0.04,
            "12M": 0.05,
            "3Y": 0.06,
            "5Y": 0.07,
        },
    ]
    relative_rows = [
        {
            "Fund": "Fund A",
            "Style": "growth",
            "error": False,
            "stale_days": 0,
            "latest_date": None,
            "MTD": 0.01,
            "3M": 0.01,
            "6M": 0.01,
            "12M": 0.01,
            "3Y": 0.01,
            "5Y": 0.01,
        }
    ]
    return absolute_rows, relative_rows


def test_build_rich_table_includes_style_column():
    absolute_rows, _ = _sample_rows()

    table = build_rich_table(absolute_rows, "Example")

    assert [column.header for column in table.columns] == ["Fund", "Style", "MTD", "3M", "6M", "12M", "3Y (p.a.)", "5Y (p.a.)"]


def test_build_html_report_includes_style_column_and_values():
    absolute_rows, relative_rows = _sample_rows()

    html = build_html_report(absolute_rows, relative_rows, pd.Timestamp("2026-03-29"))

    assert "<th>Style</th>" in html
    assert ">growth<" in html


def test_export_to_excel_writes_style_column(tmp_path: Path):
    absolute_rows, relative_rows = _sample_rows()
    output_path = tmp_path / "report.xlsx"

    export_to_excel(absolute_rows, relative_rows, pd.Timestamp("2026-03-29"), output_path)

    workbook = load_workbook(output_path)
    absolute_sheet = workbook["Absolute"]
    assert absolute_sheet["A1"].value == "Fund"
    assert absolute_sheet["B1"].value == "Style"
    assert absolute_sheet["B2"].value is None
    assert absolute_sheet["B3"].value == "growth"
