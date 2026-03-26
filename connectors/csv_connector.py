from __future__ import annotations

from pathlib import Path

import pandas as pd

from .base import BaseConnector, ConnectorValidationError


class CSVConnector(BaseConnector):
    def get_fund_data(self, fund_config: dict, start_date: str, end_date: str) -> pd.DataFrame:
        file_path = Path(fund_config["file"])
        if not file_path.is_absolute():
            file_path = Path.cwd() / file_path

        if not file_path.exists():
            raise ConnectorValidationError(f"CSV file not found: {file_path}")

        frame = pd.read_csv(file_path)
        nav_type = fund_config.get("nav_type")
        if nav_type == "ex_distribution" and "distribution" not in frame.columns:
            raise ConnectorValidationError(
                f"CSV file {file_path} must include a 'distribution' column for ex_distribution funds."
            )

        normalized = self.normalize_frame(frame)
        if nav_type != "ex_distribution" and "distribution" not in normalized.columns:
            normalized["distribution"] = 0.0

        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
        return normalized.loc[(normalized.index >= start) & (normalized.index <= end)]
