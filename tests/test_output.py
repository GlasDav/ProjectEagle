from __future__ import annotations

import pandas as pd

from output import build_html_report, build_plaintext_report


def _sample_rows():
    absolute_rows = [
        {
            "Fund": "S&P/ASX 200 Accumulation",
            "is_benchmark": True,
            "error": False,
            "stale_days": 0,
            "latest_date": pd.Timestamp("2026-03-26"),
            "MTD": 0.012,
            "3M": 0.024,
            "6M": 0.041,
            "12M": 0.083,
            "3Y": 0.071,
            "5Y": 0.066,
        },
        {
            "Fund": "Firetrail High Conviction Fund",
            "error": False,
            "stale_days": 2,
            "latest_date": pd.Timestamp("2026-03-24"),
            "MTD": 0.018,
            "3M": 0.032,
            "6M": 0.051,
            "12M": 0.121,
            "3Y": 0.095,
            "5Y": 0.089,
        },
        {
            "Fund": "Airlie Australian Share Fund",
            "error": False,
            "stale_days": 0,
            "latest_date": pd.Timestamp("2026-03-26"),
            "MTD": 0.009,
            "3M": 0.021,
            "6M": 0.038,
            "12M": 0.099,
            "3Y": 0.081,
            "5Y": 0.074,
        },
    ]
    relative_rows = [
        {
            "Fund": "Firetrail High Conviction Fund",
            "error": False,
            "stale_days": 2,
            "latest_date": pd.Timestamp("2026-03-24"),
            "MTD": 0.006,
            "3M": 0.008,
            "6M": 0.010,
            "12M": 0.038,
            "3Y": 0.024,
            "5Y": 0.023,
        },
        {
            "Fund": "Airlie Australian Share Fund",
            "error": False,
            "stale_days": 0,
            "latest_date": pd.Timestamp("2026-03-26"),
            "MTD": -0.003,
            "3M": -0.003,
            "6M": -0.003,
            "12M": 0.016,
            "3Y": 0.010,
            "5Y": 0.008,
        },
    ]
    return absolute_rows, relative_rows


def test_build_html_report_includes_summary_and_tables():
    absolute_rows, relative_rows = _sample_rows()

    html = build_html_report(absolute_rows, relative_rows, pd.Timestamp("2026-03-26"))

    assert "Australian Equity Fund Scorecard" in html
    assert "Funds ahead of benchmark (12M)" in html
    assert "Top 12M funds" in html
    assert "Return above or below benchmark" in html
    assert "Firetrail High Conviction Fund" in html
    assert "Public data through 2026-03-24 (2 days stale)" in html


def test_build_plaintext_report_summarizes_benchmark_and_leaders():
    absolute_rows, relative_rows = _sample_rows()

    text = build_plaintext_report(absolute_rows, relative_rows, pd.Timestamp("2026-03-26"))

    assert "Australian Equity Fund Scorecard (2026-03-26)" in text
    assert "Benchmark 12M: 8.3%" in text
    assert "Funds ahead of benchmark over 12M: 2 of 2" in text
    assert "Best 12M total return: Firetrail High Conviction Fund (12.1%)" in text
