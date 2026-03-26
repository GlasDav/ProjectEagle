from __future__ import annotations

import os
from typing import Any

import pandas as pd
import requests


def load_teams_webhook_url(webhook_url: str | None = None) -> str:
    resolved = webhook_url or os.getenv("PERFSRAPER_TEAMS_WEBHOOK_URL")
    if not resolved:
        raise ValueError("Teams delivery requires --teams-webhook-url or PERFSRAPER_TEAMS_WEBHOOK_URL.")
    return resolved


def _format_percent(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def _snapshot(absolute_rows: list[dict], relative_rows: list[dict]) -> dict[str, Any]:
    benchmark = next((row for row in absolute_rows if row.get("is_benchmark")), None)
    funds = [row for row in absolute_rows if not row.get("is_benchmark")]
    valid_absolute = [row for row in funds if not row.get("error") and row.get("12M") is not None]
    valid_relative = [row for row in relative_rows if not row.get("error") and row.get("12M") is not None]

    return {
        "benchmark": benchmark,
        "fund_count": len(funds),
        "stale_count": sum(1 for row in funds if row.get("stale_days", 0) > 0),
        "ahead_count": sum(1 for row in valid_relative if float(row["12M"]) > 0),
        "best_absolute": max(valid_absolute, key=lambda row: float(row["12M"]), default=None),
        "best_relative": max(valid_relative, key=lambda row: float(row["12M"]), default=None),
        "leaders": sorted(valid_absolute, key=lambda row: float(row["12M"]), reverse=True)[:5],
    }


def build_teams_message_card(absolute_rows: list[dict], relative_rows: list[dict], as_of_date) -> dict[str, Any]:
    snapshot = _snapshot(absolute_rows, relative_rows)
    benchmark = snapshot["benchmark"]
    best_absolute = snapshot["best_absolute"]
    best_relative = snapshot["best_relative"]

    benchmark_text = (
        f"MTD: {_format_percent(benchmark.get('MTD'))}  \n12M: {_format_percent(benchmark.get('12M'))}  \n3Y p.a.: {_format_percent(benchmark.get('3Y'))}"
        if benchmark is not None
        else "Benchmark data unavailable."
    )
    top_funds = (
        "  \n".join(f"- {row['Fund']}: {_format_percent(row.get('12M'))}" for row in snapshot["leaders"])
        if snapshot["leaders"]
        else "No 12M fund leaderboard is available."
    )
    best_absolute_text = (
        f"{best_absolute['Fund']} leads on 12M total return at {_format_percent(best_absolute.get('12M'))}."
        if best_absolute is not None
        else "No 12M total-return leader is available."
    )
    best_relative_text = (
        f"{best_relative['Fund']} leads on 12M excess return at {_format_percent(best_relative.get('12M'))}."
        if best_relative is not None
        else "No 12M excess-return leader is available."
    )

    return {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": "1F6A5B",
        "summary": f"Australian Equity Fund Scorecard | {pd.Timestamp(as_of_date):%Y-%m-%d}",
        "title": f"Australian Equity Fund Scorecard | {pd.Timestamp(as_of_date):%Y-%m-%d}",
        "sections": [
            {
                "activityTitle": "Daily total-return snapshot",
                "activitySubtitle": "All figures are total return. Relative figures are measured against the S&P/ASX 200 Accumulation benchmark.",
                "facts": [
                    {"name": "Live funds", "value": str(snapshot["fund_count"])},
                    {"name": "Ahead of benchmark (12M)", "value": f"{snapshot['ahead_count']} / {snapshot['fund_count']}"},
                    {"name": "Benchmark 12M", "value": _format_percent(None if benchmark is None else benchmark.get("12M"))},
                    {"name": "Stale sources", "value": str(snapshot["stale_count"])},
                ],
                "markdown": True,
            },
            {
                "title": "Benchmark",
                "text": benchmark_text,
                "markdown": True,
            },
            {
                "title": "Best 12M total return",
                "text": best_absolute_text,
                "markdown": True,
            },
            {
                "title": "Best 12M excess return",
                "text": best_relative_text,
                "markdown": True,
            },
            {
                "title": "Top 12M funds",
                "text": top_funds,
                "markdown": True,
            },
        ],
    }


def send_teams_message_card(
    webhook_url: str,
    absolute_rows: list[dict],
    relative_rows: list[dict],
    as_of_date,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    payload = build_teams_message_card(absolute_rows, relative_rows, as_of_date)
    http = session or requests.Session()
    response = http.post(webhook_url, json=payload, timeout=20)
    response.raise_for_status()
    return payload
