from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

import pandas as pd


class ConnectorValidationError(ValueError):
    """Raised when connector input cannot satisfy the required contract."""


class BaseConnector(ABC):
    @abstractmethod
    def get_fund_data(self, fund_config: dict, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Return a DataFrame indexed by DatetimeIndex with:
          - nav: required float column
          - distribution: optional float column

        Connectors should raise ConnectorValidationError for invalid user-provided data
        and return an empty DataFrame for recoverable fetch failures.
        """

    @staticmethod
    def normalize_frame(frame: pd.DataFrame, required_columns: Iterable[str] | None = None) -> pd.DataFrame:
        required_columns = tuple(required_columns or ("nav",))
        if frame is None or frame.empty:
            columns = list(dict.fromkeys([*required_columns, "distribution"]))
            return pd.DataFrame(columns=columns)

        result = frame.copy()

        if "date" in result.columns and not isinstance(result.index, pd.DatetimeIndex):
            result["date"] = pd.to_datetime(result["date"], errors="coerce")
            result = result.set_index("date")

        if not isinstance(result.index, pd.DatetimeIndex):
            result.index = pd.to_datetime(result.index, errors="coerce")
        if isinstance(result.index, pd.DatetimeIndex) and result.index.tz is not None:
            result.index = result.index.tz_convert(None)

        result = result[~result.index.isna()]

        missing = [column for column in required_columns if column not in result.columns]
        if missing:
            raise ConnectorValidationError(f"Missing required columns: {', '.join(missing)}")

        result = result.loc[:, [column for column in result.columns if column in {"nav", "distribution"}]].copy()
        result["nav"] = pd.to_numeric(result["nav"], errors="coerce")

        if "distribution" in result.columns:
            result["distribution"] = pd.to_numeric(result["distribution"], errors="coerce").fillna(0.0)

        result = result.dropna(subset=["nav"])
        result.index = result.index.normalize()
        result = result.sort_index()

        aggregations: dict[str, str] = {"nav": "last"}
        if "distribution" in result.columns:
            aggregations["distribution"] = "sum"

        result = result.groupby(level=0).agg(aggregations)
        return result
