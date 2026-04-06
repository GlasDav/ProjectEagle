from __future__ import annotations

import pandas as pd

from teams_delivery import build_teams_message_card


def _sample_rows():
    absolute_rows = [
        {
            "Fund": "Benchmark",
            "Style": "",
            "is_benchmark": True,
            "is_stale": False,
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
            "Style": "Growth",
            "is_benchmark": False,
            "is_stale": False,
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
            "Style": "Growth",
            "is_stale": False,
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
    assert fund_row[1]["items"][0]["text"] == "Growth"


def test_build_teams_message_card_adaptive_includes_style_lens_and_threshold_aware_stale_count():
    absolute_rows, relative_rows = _sample_rows()
    absolute_rows[1]["latest_date"] = pd.Timestamp("2026-03-20")
    absolute_rows[1]["stale_days"] = 9
    absolute_rows[1]["is_stale"] = False
    relative_rows[0]["latest_date"] = pd.Timestamp("2026-03-20")
    relative_rows[0]["stale_days"] = 9
    relative_rows[0]["is_stale"] = False

    payload = build_teams_message_card(
        absolute_rows,
        relative_rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://example.com/webhook",
    )

    body = payload["attachments"][0]["content"]["body"]
    facts = body[2]["facts"]
    style_items = body[3]["items"]

    assert any(block.get("text") == "Style lens" for block in style_items if isinstance(block, dict) and block.get("type") == "TextBlock")
    assert next(fact["value"] for fact in facts if fact["title"] == "Stale sources") == "0"


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
    assert "Growth" in table_text
    assert any(section.get("title") == "Style lens" for section in payload["sections"])
