from __future__ import annotations

from datetime import date

import pandas as pd

PERIODS = ("MTD", "3M", "6M", "12M", "3Y", "5Y")


def nearest_on_or_before(series: pd.Series, target_date: pd.Timestamp) -> pd.Timestamp | None:
    eligible = series.index[series.index <= target_date]
    if len(eligible) == 0:
        return None
    return eligible[-1]


def calculate_returns(total_return_index: pd.Series, as_of_date: date | pd.Timestamp) -> dict[str, float | None]:
    series = total_return_index.dropna().sort_index()
    if series.empty:
        return {period: None for period in PERIODS}

    as_of_timestamp = pd.Timestamp(as_of_date)
    end_date = nearest_on_or_before(series, as_of_timestamp)
    if end_date is None:
        return {period: None for period in PERIODS}

    end_value = float(series.loc[end_date])
    month_start = end_date.replace(day=1)
    targets = {
        "MTD": month_start,
        "3M": end_date - pd.DateOffset(months=3),
        "6M": end_date - pd.DateOffset(months=6),
        "12M": end_date - pd.DateOffset(months=12),
        "3Y": end_date - pd.DateOffset(years=3),
        "5Y": end_date - pd.DateOffset(years=5),
    }

    results: dict[str, float | None] = {}
    for period, target in targets.items():
        start_date = nearest_on_or_before(series, pd.Timestamp(target))
        if start_date is None or start_date == end_date:
            results[period] = None
            continue

        start_value = float(series.loc[start_date])
        if start_value <= 0:
            results[period] = None
            continue

        total_return = (end_value / start_value) - 1
        if period in {"3Y", "5Y"}:
            days = (end_date - start_date).days
            if days <= 0:
                results[period] = None
                continue
            results[period] = (1 + total_return) ** (365.25 / days) - 1
        else:
            results[period] = total_return

    return results


def calculate_relative_returns(
    fund_returns: dict[str, float | None], benchmark_returns: dict[str, float | None]
) -> dict[str, float | None]:
    return {
        period: None
        if fund_returns.get(period) is None or benchmark_returns.get(period) is None
        else fund_returns[period] - benchmark_returns[period]
        for period in PERIODS
    }
