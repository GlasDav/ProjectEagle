from __future__ import annotations

import pandas as pd

from teams_delivery import build_teams_message_card


def _sample_rows():
    absolute_rows = [
        {
            "Fund": "Benchmark",
            "Style": "",
            "is_benchmark": True,
            "error": False,
            "stale_days": 0,
            "latest_date": None,
            "MTD": 0.01,
            "3M": 0.02,
            "6M": 0.03,
            "12M": 0.04,
            "3Y": 0.05,
            "5Y": 0.06,
        },
        {
            "Fund": "Fund A",
            "Style": "growth",
            "is_benchmark": False,
            "error": False,
            "stale_days": 0,
            "latest_date": None,
            "MTD": 0.02,
            "3M": 0.03,
            "6M": 0.04,
            "12M": 0.05,
            "3Y": 0.06,
            "5Y": 0.07,
        },
    ]
    relative_rows = [
        {
            "Fund": "Fund A",
            "Style": "growth",
            "error": False,
            "stale_days": 0,
            "latest_date": None,
            "MTD": 0.01,
            "3M": 0.01,
            "6M": 0.01,
            "12M": 0.01,
            "3Y": 0.01,
            "5Y": 0.01,
        }
    ]
    return absolute_rows, relative_rows


def test_build_teams_message_card_adaptive_includes_style_column():
    absolute_rows, relative_rows = _sample_rows()

    payload = build_teams_message_card(
        absolute_rows,
        relative_rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://example.com/webhook",
    )

    table = payload["attachments"][0]["content"]["body"][-1]
    headers = [cell["items"][0]["text"] for cell in table["rows"][0]["cells"]]
    benchmark_row = table["rows"][1]["cells"]
    fund_row = table["rows"][2]["cells"]

    assert headers[1] == "Style"
    assert benchmark_row[1]["items"][0]["text"] == ""
    assert fund_row[1]["items"][0]["text"] == "growth"


def test_build_teams_message_card_legacy_includes_style_column():
    absolute_rows, relative_rows = _sample_rows()

    payload = build_teams_message_card(
        absolute_rows,
        relative_rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://webhook.office.com/example",
    )

    table_text = payload["sections"][-1]["text"]

    assert "Style" in table_text
    assert "growth" in table_text
