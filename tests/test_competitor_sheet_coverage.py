from __future__ import annotations

from pathlib import Path

import yaml


FIRETRAIL_COMPETITOR_FUNDS = [
    "Firetrail Australian High Conviction Fund",
    "Bennelong Concentrated Australian Equities",
    "Greencape High Conviction Fund",
    "Wavestone Australian Share Fund",
    "DNR High Conviction Australian Equities",
    "Pendal Focus Australian Share Fund",
    "Schroder Australian Equity Fund",
    "Fidelity Australian Equities Fund",
    "Investors Mutual Australian Share Fund",
    "Northcape Capital Core Australian Equities",
    "Airlie Australian Share Fund",
    "Perpetual Concentrated Equity Fund",
    "Ausbil Australian Active Equity",
    "Hyperion Australian Growth Companies",
    "Chester High Conviction Fund",
    "Solaris Core Australian Equity Fund",
    "Vanguard Australian Shares Index",
    "Chester Opportunities Fund",
    "Katana Australian Equity Fund",
    "Dimensional Australian Value",
    "Allan Gray Australian Equity",
    "Forager Australian Value",
    "AuscapAM Auscap Ex-20 Australian Equities Fund",
    "RQI Australian Value (formerly Realindex)",
    "Martin Currie Australia Value Equity",
    "Dimensional Aust Core Equity",
    "Lazard Select Australian Equity",
    "Lazard Australian Equity (Benchmark Unconstrained)",
    "First Sentier FSI Geared Australian Share Fund",
    "AB Concentrated Australian Equities",
    "Macquarie Australian Shares",
    "Paradice Australian Equities",
]


def test_firetrail_competitor_sheet_funds_are_represented_in_config():
    repo_root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((repo_root / "config.yaml").read_text(encoding="utf-8"))

    covered_names: set[str] = set()
    for fund in config["funds"]:
        name = str(fund.get("name", "")).strip()
        if name:
            covered_names.add(name)
        for alias in fund.get("aliases", []):
            alias_text = str(alias).strip()
            if alias_text:
                covered_names.add(alias_text)

    missing = sorted(set(FIRETRAIL_COMPETITOR_FUNDS) - covered_names)
    assert missing == [], f"Missing competitor-sheet funds in config: {missing}"
