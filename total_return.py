from __future__ import annotations

import logging

import pandas as pd

LOGGER = logging.getLogger(__name__)
DIRECT_NAV_TYPES = {"total_return", "adjusted_close", "cum_distribution"}
SUPPORTED_NAV_TYPES = DIRECT_NAV_TYPES | {"ex_distribution"}


def build_total_return_index(fund_data: pd.DataFrame, nav_type: str) -> pd.Series:
    if nav_type not in SUPPORTED_NAV_TYPES:
        raise ValueError(f"Unsupported nav_type '{nav_type}'.")

    if fund_data is None or fund_data.empty:
        return pd.Series(dtype="float64", name="tri")

    frame = fund_data.copy()
    frame.index = pd.to_datetime(frame.index, errors="coerce")
    frame = frame[~frame.index.isna()].sort_index()
    aggregations = {"nav": "last"}
    if "distribution" in frame.columns:
        aggregations["distribution"] = "sum"
    frame = frame.groupby(level=0).agg(aggregations)
    frame["nav"] = pd.to_numeric(frame["nav"], errors="coerce")
    frame = frame.dropna(subset=["nav"])
    if frame.empty:
        return pd.Series(dtype="float64", name="tri")

    if nav_type in DIRECT_NAV_TYPES:
        base_value = frame["nav"].iloc[0]
        tri = (frame["nav"] / base_value) * 100.0
        tri.name = "tri"
        return tri

    had_distribution_column = "distribution" in frame.columns
    raw_distributions = pd.to_numeric(frame.get("distribution", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    distributions = raw_distributions.reindex(frame.index, fill_value=0.0).fillna(0.0)

    has_nonzero_distribution = not raw_distributions.dropna().empty and (distributions != 0).any()
    if not had_distribution_column or not has_nonzero_distribution:
        LOGGER.warning("No usable distribution data found for ex_distribution series. Falling back to price-only returns.")

    returns = frame["nav"] / frame["nav"].shift(1) - 1
    distribution_mask = distributions != 0
    returns.loc[distribution_mask] = (frame["nav"].loc[distribution_mask] + distributions.loc[distribution_mask]) / frame[
        "nav"
    ].shift(1).loc[distribution_mask] - 1
    returns.iloc[0] = 0.0
    tri = (1 + returns.fillna(0.0)).cumprod() * 100.0
    tri.name = "tri"
    return tri
