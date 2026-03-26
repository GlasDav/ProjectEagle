from __future__ import annotations

import pytest

from connectors.base import ConnectorValidationError
from connectors.csv_connector import CSVConnector


def test_csv_connector_loads_cum_distribution_csv():
    connector = CSVConnector()
    frame = connector.get_fund_data(
        {"file": "data/fixtures/example_cum_distribution.csv", "nav_type": "cum_distribution"},
        "2024-01-01",
        "2024-12-31",
    )
    assert list(frame.columns) == ["nav", "distribution"]
    assert len(frame) == 3


def test_csv_connector_loads_ex_distribution_csv():
    connector = CSVConnector()
    frame = connector.get_fund_data(
        {"file": "data/fixtures/example_ex_distribution.csv", "nav_type": "ex_distribution"},
        "2024-01-01",
        "2024-12-31",
    )
    assert "distribution" in frame.columns
    assert frame["distribution"].sum() == 0.5


def test_csv_connector_rejects_missing_distribution_for_ex_distribution():
    connector = CSVConnector()
    with pytest.raises(ConnectorValidationError):
        connector.get_fund_data(
            {"file": "data/fixtures/example_missing_distribution.csv", "nav_type": "ex_distribution"},
            "2024-01-01",
            "2024-12-31",
        )
