from __future__ import annotations

import logging

import pandas as pd
import pytest

from total_return import build_total_return_index


def test_build_total_return_index_direct_nav_types_rebase_to_100():
    index = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
    frame = pd.DataFrame({"nav": [10.0, 10.5, 11.0]}, index=index)

    tri = build_total_return_index(frame, "cum_distribution")

    assert tri.iloc[0] == 100.0
    assert tri.iloc[-1] == pytest.approx(110.0)


def test_build_total_return_index_ex_distribution_reinvests_distribution():
    index = pd.date_range("2024-01-01", periods=6, freq="D")
    frame = pd.DataFrame(
        {
            "nav": [10.00, 10.10, 10.201, 10.30301, 9.9060401, 10.0051005],
            "distribution": [0.0, 0.0, 0.0, 0.0, 0.50, 0.0],
        },
        index=index,
    )

    tri = build_total_return_index(frame, "ex_distribution")

    expected = [100.0, 101.0, 102.01, 103.0301, 104.060401, 105.10100501]
    for actual, expected_value in zip(tri.tolist(), expected):
        assert actual == pytest.approx(expected_value, rel=1e-9)


def test_build_total_return_index_collapses_duplicate_dates():
    index = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-02", "2024-01-03"])
    frame = pd.DataFrame(
        {
            "nav": [10.0, 9.9, 9.95, 10.10],
            "distribution": [0.0, 0.1, 0.2, 0.0],
        },
        index=index,
    )

    tri = build_total_return_index(frame, "ex_distribution")

    assert tri.index.tolist() == list(pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]))
    assert tri.iloc[1] == pytest.approx(102.5)


def test_build_total_return_index_logs_fallback_when_distribution_missing(caplog):
    index = pd.to_datetime(["2024-01-01", "2024-01-02"])
    frame = pd.DataFrame({"nav": [10.0, 9.5]}, index=index)

    with caplog.at_level(logging.WARNING):
        tri = build_total_return_index(frame, "ex_distribution")

    assert "Falling back to price-only returns" in caplog.text
    assert tri.iloc[-1] == 95.0


def test_build_total_return_index_logs_fallback_when_distribution_column_all_zero(caplog):
    index = pd.to_datetime(["2024-01-01", "2024-01-02"])
    frame = pd.DataFrame({"nav": [10.0, 9.5], "distribution": [0.0, 0.0]}, index=index)

    with caplog.at_level(logging.WARNING):
        tri = build_total_return_index(frame, "ex_distribution")

    assert "Falling back to price-only returns" in caplog.text
    assert tri.iloc[-1] == 95.0
