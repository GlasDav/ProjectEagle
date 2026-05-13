from __future__ import annotations

from pathlib import Path

import yaml

from main import load_config, is_default_report_fund


def test_removed_funds_are_not_in_default_live_config():
    repo_root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((repo_root / "config.yaml").read_text(encoding="utf-8"))

    live_names = {
        str(fund.get("name", "")).strip()
        for fund in config["funds"]
        if fund.get("enabled", True) is not False
    }

    removed_names = {
        "Selector High Conviction Equity Fund",
        "Vanguard Australian Shares Index",
        "Smallco Broadcap",
        "First Sentier FSI Geared Australian Share Fund",
        "RQI Australian Value (formerly Realindex)",
        "Investors Mutual Australian Share Fund",
        "Dimensional Australian Value",
        "Dimensional Aust Core Equity",
    }
    assert removed_names.isdisjoint(live_names)


def test_live_config_declares_requested_competitor_sets_and_keeps_peer_only_funds_out_of_default_report():
    repo_root = Path(__file__).resolve().parents[1]
    config = load_config(repo_root / "config.yaml")

    competitor_sets = {competitor_set["id"]: competitor_set for competitor_set in config["competitor_sets"]}
    assert competitor_sets["long_short_funds"]["funds"] == [
        "Firetrail Alpha Plus Fund Complex ETF",
        "Ten Cap Alpha Plus Complex ETF",
        "Sage Capital Equity Plus Fund",
        "Perpetual SHARE-PLUS Long-Short Fund",
        "Regal Australian Long Short Equity Fund",
        "Acadian Australian Equity Long Short Fund",
        "Vinva Australian Equity Alpha Extension Fund",
    ]
    assert competitor_sets["market_neutral_funds"]["funds"] == [
        "Acadian Wholesale Australian Market Neutral Fund",
        "Firetrail Absolute Return Fund",
        "Sage Capital Absolute Return Fund",
        "Regal Tasman Market Neutral Fund",
        "Bennelong Market Neutral Fund",
    ]

    default_names = {fund["name"] for fund in config["funds"] if is_default_report_fund(fund)}
    assert "Firetrail Alpha Plus Fund Complex ETF" not in default_names
    assert "Ten Cap Alpha Plus Complex ETF" not in default_names
    assert "Sage Capital Equity Plus Fund" not in default_names
    assert "Perpetual SHARE-PLUS Long-Short Fund" not in default_names
    assert "Vinva Australian Equity Alpha Extension Fund" not in default_names
    assert "Firetrail Absolute Return Fund" not in default_names
    assert "Sage Capital Absolute Return Fund" not in default_names

    disabled_peer_funds = [
        fund
        for fund in config["funds"]
        if fund["name"] in {
            "Ten Cap Alpha Plus Complex ETF",
            "Regal Australian Long Short Equity Fund",
            "Acadian Australian Equity Long Short Fund",
            "Acadian Wholesale Australian Market Neutral Fund",
            "Regal Tasman Market Neutral Fund",
            "Bennelong Market Neutral Fund",
        }
    ]
    assert disabled_peer_funds
    assert all(fund.get("enabled") is False and fund.get("disabled_reason") for fund in disabled_peer_funds)
