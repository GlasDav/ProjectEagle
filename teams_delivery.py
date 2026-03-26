from __future__ import annotations

import os
from urllib.parse import urlparse
from typing import Any

import pandas as pd
import requests

from performance import PERIODS


def load_teams_webhook_url(webhook_url: str | None = None) -> str:
    resolved = webhook_url or os.getenv("PERFSRAPER_TEAMS_WEBHOOK_URL")
    if not resolved:
        raise ValueError("Teams delivery requires --teams-webhook-url or PERFSRAPER_TEAMS_WEBHOOK_URL.")
    return resolved


def _format_percent(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def _format_fund_label(row: dict) -> str:
    label = str(row["Fund"])
    if row.get("stale_days", 0) > 0 and row.get("latest_date") is not None:
        label = f"{label} (as of {pd.Timestamp(row['latest_date']):%Y-%m-%d})"
    return label


def _is_legacy_connector_webhook(webhook_url: str | None) -> bool:
    if not webhook_url:
        return False
    parsed = urlparse(webhook_url)
    host = (parsed.netloc or "").casefold()
    path = (parsed.path or "").casefold()
    return "webhook.office.com" in host or "/incomingwebhook/" in path


def _text_block(text: str, *, weight: str | None = None, size: str | None = None, color: str | None = None, wrap: bool = True) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "TextBlock", "text": text, "wrap": wrap}
    if weight:
        block["weight"] = weight
    if size:
        block["size"] = size
    if color:
        block["color"] = color
    return block


def _value_text_block(value: float | None, *, error: bool = False, header: bool = False) -> dict[str, Any]:
    if header:
        return _text_block(_format_percent(value), weight="Bolder")
    if error:
        return _text_block("Error", color="Attention")
    if value is None:
        return _text_block("N/A", color="Accent")
    color = "Good" if value >= 0 else "Attention"
    return _text_block(_format_percent(value), color=color)


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


def _build_plaintext_table(rows: list[dict]) -> str:
    headers = ["Fund", *[f"{period} p.a." if period in {"3Y", "5Y"} else period for period in PERIODS]]
    rendered_rows = []
    for row in rows:
        rendered_rows.append(
            [
                _format_fund_label(row),
                *[_format_percent(None if row.get("error") else row.get(period)) for period in PERIODS],
            ]
        )

    widths = [len(header) for header in headers]
    for row in rendered_rows:
        for index, value in enumerate(row):
            widths[index] = min(max(widths[index], len(value)), 42 if index == 0 else 10)

    def fit(value: str, width: int) -> str:
        return value if len(value) <= width else value[: max(width - 1, 1)] + "…"

    lines = []
    lines.append(" | ".join(fit(header, widths[index]).ljust(widths[index]) for index, header in enumerate(headers)))
    lines.append("-|-".join("-" * width for width in widths))
    for row in rendered_rows:
        lines.append(" | ".join(fit(value, widths[index]).ljust(widths[index]) for index, value in enumerate(row)))
    return "\n".join(lines)


def _build_adaptive_teams_message_card(absolute_rows: list[dict], relative_rows: list[dict], as_of_date) -> dict[str, Any]:
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

    facts = [
        {"title": "Live funds", "value": str(snapshot["fund_count"])},
        {"title": "Ahead of benchmark (12M)", "value": f"{snapshot['ahead_count']} / {snapshot['fund_count']}"},
        {"title": "Benchmark 12M", "value": _format_percent(None if benchmark is None else benchmark.get("12M"))},
        {"title": "Stale sources", "value": str(snapshot["stale_count"])},
    ]

    headers = ["Fund", *[f"{period} (p.a.)" if period in {"3Y", "5Y"} else period for period in PERIODS]]
    table_rows = [
        {
            "type": "TableRow",
            "cells": [{"type": "TableCell", "items": [_text_block(header, weight="Bolder")]} for header in headers],
        }
    ]

    for row in absolute_rows:
        label_block = _text_block(
            _format_fund_label(row),
            weight="Bolder" if row.get("is_benchmark") else None,
        )
        cells = [{"type": "TableCell", "items": [label_block]}]
        for period in PERIODS:
            cells.append({"type": "TableCell", "items": [_value_text_block(row.get(period), error=row.get("error", False))]})
        table_rows.append({"type": "TableRow", "cells": cells})

    table = {
        "type": "Table",
        "firstRowAsHeaders": True,
        "showGridLines": True,
        "gridStyle": "accent",
        "columns": [
            {"width": 3.6},
            {"width": 1.0},
            {"width": 1.0},
            {"width": 1.0},
            {"width": 1.0},
            {"width": 1.0},
            {"width": 1.0},
        ],
        "rows": table_rows,
    }

    card_content = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "msteams": {"width": "Full"},
        "body": [
            _text_block(f"Australian Equity Fund Scorecard | {pd.Timestamp(as_of_date):%Y-%m-%d}", weight="Bolder", size="Large"),
            _text_block(
                "All figures are total return. Relative highlights are measured against the S&P/ASX 200 Accumulation benchmark.",
                color="Accent",
            ),
            {"type": "FactSet", "facts": facts},
            {
                "type": "Container",
                "style": "emphasis",
                "items": [
                    _text_block("Benchmark", weight="Bolder"),
                    _text_block(benchmark_text),
                    _text_block("Best 12M total return", weight="Bolder", size="Medium"),
                    _text_block(best_absolute_text),
                    _text_block("Best 12M excess return", weight="Bolder", size="Medium"),
                    _text_block(best_relative_text),
                ],
            },
            _text_block("Top 12M funds", weight="Bolder", size="Medium"),
            _text_block(top_funds),
            _text_block("Full performance table", weight="Bolder", size="Medium"),
            _text_block("The table below shows absolute total-return performance for every fund in the report."),
            table,
        ],
    }

    return {
        "type": "message",
        "summary": f"Australian Equity Fund Scorecard | {pd.Timestamp(as_of_date):%Y-%m-%d}",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": card_content,
            }
        ],
    }


def _build_legacy_teams_message_card(absolute_rows: list[dict], relative_rows: list[dict], as_of_date) -> dict[str, Any]:
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

    table_text = _build_plaintext_table(absolute_rows)

    return {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": "1F6A5B",
        "summary": f"Australian Equity Fund Scorecard | {pd.Timestamp(as_of_date):%Y-%m-%d}",
        "title": f"Australian Equity Fund Scorecard | {pd.Timestamp(as_of_date):%Y-%m-%d}",
        "text": "All figures are total return. Relative highlights are measured against the S&P/ASX 200 Accumulation benchmark.",
        "sections": [
            {
                "activityTitle": "Daily total-return snapshot",
                "facts": [
                    {"name": "Live funds", "value": str(snapshot["fund_count"])},
                    {"name": "Ahead of benchmark (12M)", "value": f"{snapshot['ahead_count']} / {snapshot['fund_count']}"},
                    {"name": "Benchmark 12M", "value": _format_percent(None if benchmark is None else benchmark.get("12M"))},
                    {"name": "Stale sources", "value": str(snapshot["stale_count"])},
                ],
                "markdown": True,
            },
            {"title": "Benchmark", "text": benchmark_text, "markdown": True},
            {"title": "Best 12M total return", "text": best_absolute_text, "markdown": True},
            {"title": "Best 12M excess return", "text": best_relative_text, "markdown": True},
            {"title": "Top 12M funds", "text": top_funds, "markdown": True},
            {
                "title": "Full performance table",
                "text": table_text,
                "markdown": True,
            },
        ],
    }


def build_teams_message_card(
    absolute_rows: list[dict],
    relative_rows: list[dict],
    as_of_date,
    webhook_url: str | None = None,
) -> dict[str, Any]:
    if _is_legacy_connector_webhook(webhook_url):
        return _build_legacy_teams_message_card(absolute_rows, relative_rows, as_of_date)
    return _build_adaptive_teams_message_card(absolute_rows, relative_rows, as_of_date)


def send_teams_message_card(
    webhook_url: str,
    absolute_rows: list[dict],
    relative_rows: list[dict],
    as_of_date,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    payload = build_teams_message_card(absolute_rows, relative_rows, as_of_date, webhook_url=webhook_url)
    http = session or requests.Session()
    response = http.post(webhook_url, json=payload, timeout=20)
    if response.status_code >= 400:
        body = response.text.strip()
        snippet = body[:500] if body else "<empty response body>"
        raise RuntimeError(f"Teams webhook returned HTTP {response.status_code}: {snippet}")
    return payload
