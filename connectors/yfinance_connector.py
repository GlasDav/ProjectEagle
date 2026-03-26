from __future__ import annotations

import logging
import time

import pandas as pd
import yfinance as yf

from .base import BaseConnector

LOGGER = logging.getLogger(__name__)


class YFinanceConnector(BaseConnector):
    def get_fund_data(self, fund_config: dict, start_date: str, end_date: str) -> pd.DataFrame:
        ticker = fund_config["ticker"]
        attempts = 2
        for attempt in range(1, attempts + 1):
            try:
                history = yf.download(
                    ticker,
                    start=start_date,
                    end=(pd.Timestamp(end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                    auto_adjust=False,
                    progress=False,
                    timeout=10,
                    threads=False,
                )
                break
            except Exception as exc:
                if attempt == attempts:
                    LOGGER.warning("Yahoo Finance fetch failed for %s: %s", ticker, exc)
                    return pd.DataFrame(columns=["nav", "distribution"])
                time.sleep(1)
        else:
            return pd.DataFrame(columns=["nav", "distribution"])

        if history is None or history.empty:
            LOGGER.warning("Yahoo Finance returned no rows for %s", ticker)
            return pd.DataFrame(columns=["nav", "distribution"])

        if isinstance(history.columns, pd.MultiIndex):
            history.columns = history.columns.get_level_values(0)

        nav_column = "Adj Close"
        if ticker == "^AXJT" or fund_config.get("nav_type") == "total_return":
            if "Adj Close" in history.columns and not history["Adj Close"].dropna().empty:
                nav_column = "Adj Close"
            else:
                nav_column = "Close"
        elif "Adj Close" not in history.columns or history["Adj Close"].dropna().empty:
            nav_column = "Close"

        frame = pd.DataFrame({"date": history.index, "nav": history[nav_column]})
        return self.normalize_frame(frame)
