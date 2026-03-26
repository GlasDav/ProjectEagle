from __future__ import annotations

import pandas as pd
import pytest

from teams_delivery import build_teams_message_card, load_teams_webhook_url, send_teams_message_card


def _sample_rows():
    absolute_rows = [
        {
            "Fund": "S&P/ASX 200 Accumulation",
            "is_benchmark": True,
            "error": False,
            "stale_days": 0,
            "latest_date": pd.Timestamp("2026-03-26"),
            "MTD": 0.012,
            "3M": 0.024,
            "6M": 0.041,
            "12M": 0.083,
            "3Y": 0.071,
            "5Y": 0.066,
        },
        {
            "Fund": "Firetrail High Conviction Fund",
            "error": False,
            "stale_days": 2,
            "latest_date": pd.Timestamp("2026-03-24"),
            "MTD": 0.018,
            "3M": 0.032,
            "6M": 0.051,
            "12M": 0.121,
            "3Y": 0.095,
            "5Y": 0.089,
        },
        {
            "Fund": "Airlie Australian Share Fund",
            "error": False,
            "stale_days": 0,
            "latest_date": pd.Timestamp("2026-03-26"),
            "MTD": 0.009,
            "3M": 0.021,
            "6M": 0.038,
            "12M": 0.099,
            "3Y": 0.081,
            "5Y": 0.074,
        },
    ]
    relative_rows = [
        {
            "Fund": "Firetrail High Conviction Fund",
            "error": False,
            "stale_days": 2,
            "latest_date": pd.Timestamp("2026-03-24"),
            "MTD": 0.006,
            "3M": 0.008,
            "6M": 0.010,
            "12M": 0.038,
            "3Y": 0.024,
            "5Y": 0.023,
        },
        {
            "Fund": "Airlie Australian Share Fund",
            "error": False,
            "stale_days": 0,
            "latest_date": pd.Timestamp("2026-03-26"),
            "MTD": -0.003,
            "3M": -0.003,
            "6M": -0.003,
            "12M": 0.016,
            "3Y": 0.010,
            "5Y": 0.008,
        },
    ]
    return absolute_rows, relative_rows


def test_load_teams_webhook_url_uses_argument_or_env(monkeypatch):
    monkeypatch.setenv("PERFSRAPER_TEAMS_WEBHOOK_URL", "https://env.example/webhook")
    assert load_teams_webhook_url() == "https://env.example/webhook"
    assert load_teams_webhook_url("https://arg.example/webhook") == "https://arg.example/webhook"


def test_load_teams_webhook_url_requires_value(monkeypatch):
    monkeypatch.delenv("PERFSRAPER_TEAMS_WEBHOOK_URL", raising=False)

    with pytest.raises(ValueError, match="PERFSRAPER_TEAMS_WEBHOOK_URL"):
        load_teams_webhook_url()


def test_build_teams_message_card_includes_summary_and_leaders():
    absolute_rows, relative_rows = _sample_rows()

    payload = build_teams_message_card(absolute_rows, relative_rows, pd.Timestamp("2026-03-26"))

    assert payload["type"] == "message"
    assert payload["summary"] == "Australian Equity Fund Scorecard | 2026-03-26"
    attachment = payload["attachments"][0]
    assert attachment["contentType"] == "application/vnd.microsoft.card.adaptive"
    content = attachment["content"]
    assert content["type"] == "AdaptiveCard"
    assert content["body"][2]["facts"][0]["value"] == "2"
    assert "Firetrail High Conviction Fund" in content["body"][3]["items"][3]["text"]
    assert "Airlie Australian Share Fund" in content["body"][5]["text"]
    assert content["body"][-1]["type"] == "Table"
    assert len(content["body"][-1]["rows"]) == 4


def test_send_teams_message_card_posts_json():
    absolute_rows, relative_rows = _sample_rows()
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

    class FakeSession:
        def post(self, url, json, timeout):
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            return FakeResponse()

    payload = send_teams_message_card(
        webhook_url="https://example.test/webhook",
        absolute_rows=absolute_rows,
        relative_rows=relative_rows,
        as_of_date=pd.Timestamp("2026-03-26"),
        session=FakeSession(),
    )

    assert captured["url"] == "https://example.test/webhook"
    assert captured["timeout"] == 20
    assert captured["json"] == payload
