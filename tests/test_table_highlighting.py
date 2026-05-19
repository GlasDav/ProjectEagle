from __future__ import annotations

from table_highlighting import HIGHLIGHT_BOTTOM, HIGHLIGHT_TOP, build_period_highlights


def _fund_row(name: str, value: float) -> dict:
    return {
        "Fund": name,
        "is_benchmark": False,
        "is_average": False,
        "error": False,
        "MTD": value,
    }


def test_highlights_exclude_benchmark_and_average_by_default():
    rows = [
        {"Fund": "S&P/ASX 200 Accumulation", "is_benchmark": True, "MTD": 0.99},
        _fund_row("Fund 1", 0.01),
        _fund_row("Fund 2", 0.02),
        _fund_row("Fund 3", 0.03),
        _fund_row("Fund 4", 0.04),
        {"Fund": "Average", "is_average": True, "MTD": -0.99},
    ]

    highlights = build_period_highlights(rows, periods=["MTD"])

    assert highlights == {
        (1, "MTD"): HIGHLIGHT_BOTTOM,
        (4, "MTD"): HIGHLIGHT_TOP,
    }


def test_highlight_count_scales_down_for_mid_sized_tables():
    rows = [_fund_row(f"Fund {index}", index / 100) for index in range(1, 8)]

    highlights = build_period_highlights(rows, periods=["MTD"])

    assert highlights == {
        (0, "MTD"): HIGHLIGHT_BOTTOM,
        (1, "MTD"): HIGHLIGHT_BOTTOM,
        (5, "MTD"): HIGHLIGHT_TOP,
        (6, "MTD"): HIGHLIGHT_TOP,
    }
