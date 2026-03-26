from __future__ import annotations

import os

import pytest

from connectors.yfinance_connector import YFinanceConnector


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_YFINANCE_TESTS") != "1",
    reason="Set RUN_YFINANCE_TESTS=1 to run live Yahoo Finance integration tests.",
)


def test_yfinance_connector_fetches_validation_ticker():
    connector = YFinanceConnector()
    frame = connector.get_fund_data(
        {"ticker": "VAS.AX", "nav_type": "adjusted_close"},
        "2024-01-01",
        "2024-02-01",
    )
    assert not frame.empty
