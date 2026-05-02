from __future__ import annotations

from pathlib import Path

import yaml


def test_selector_fund_is_not_in_default_live_config():
    repo_root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((repo_root / "config.yaml").read_text(encoding="utf-8"))

    live_names = {
        str(fund.get("name", "")).strip()
        for fund in config["funds"]
        if fund.get("enabled", True) is not False
    }

    assert "Selector High Conviction Equity Fund" not in live_names

