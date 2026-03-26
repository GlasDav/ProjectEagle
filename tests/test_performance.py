from __future__ import annotations

import pandas as pd
import pytest

from performance import calculate_relative_returns, calculate_returns, nearest_on_or_before


def test_nearest_on_or_before_returns_last_valid_date():
    series = pd.Series([100, 101], index=pd.to_datetime(["2024-01-01", "2024-01-05"]))
    result = nearest_on_or_before(series, pd.Timestamp("2024-01-04"))
    assert result == pd.Timestamp("2024-01-01")


def test_calculate_returns_for_month_and_year_periods():
    index = pd.to_datetime(
        [
            "2019-03-31",
            "2021-03-31",
            "2022-09-30",
            "2023-04-30",
            "2024-01-30",
            "2024-03-31",
            "2024-04-30",
        ]
    )
    tri = pd.Series([80.0, 90.0, 95.0, 100.0, 110.0, 121.0, 133.1], index=index)

    returns = calculate_returns(tri, pd.Timestamp("2024-04-30"))

    assert returns["MTD"] == pytest.approx(0.1)
    assert returns["3M"] == pytest.approx((133.1 / 110.0) - 1)
    assert returns["6M"] == pytest.approx((133.1 / 100.0) - 1)
    assert returns["12M"] == pytest.approx((133.1 / 100.0) - 1)
    assert returns["3Y"] == pytest.approx((133.1 / 90.0) ** (365.25 / (pd.Timestamp("2024-04-30") - pd.Timestamp("2021-03-31")).days) - 1)
    assert returns["5Y"] == pytest.approx((133.1 / 80.0) ** (365.25 / (pd.Timestamp("2024-04-30") - pd.Timestamp("2019-03-31")).days) - 1)


def test_calculate_returns_returns_none_when_history_is_insufficient():
    tri = pd.Series([100.0], index=pd.to_datetime(["2024-01-01"]))
    returns = calculate_returns(tri, pd.Timestamp("2024-01-01"))
    assert all(value is None for value in returns.values())


def test_calculate_relative_returns_subtracts_benchmark():
    fund = {"MTD": 0.05, "3M": None}
    benchmark = {"MTD": 0.02, "3M": 0.01}
    relative = calculate_relative_returns(fund, benchmark)
    assert relative["MTD"] == pytest.approx(0.03)
    assert relative["3M"] is None
