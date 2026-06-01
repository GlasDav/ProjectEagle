from __future__ import annotations

import json
import os
from urllib.parse import urlparse
from typing import Any

import pandas as pd
import requests

from performance import PERIODS
from table_highlighting import HIGHLIGHT_BOTTOM, HIGHLIGHT_TOP, PerformanceHighlight, build_period_highlights

LEGACY_TOP_MARKER = "\N{LARGE GREEN CIRCLE}"
LEGACY_BOTTOM_MARKER = "\N{LARGE RED CIRCLE}"
LEGACY_HIGHLIGHT_LEGEND = "Green circles mark best performers; red circles mark worst performers."
MAX_TEAMS_CARD_BYTES = 24_000


class TeamsPayloadList(list):
    """List of Teams payloads with first-card mapping access for older callers."""

    def __getitem__(self, item):
        if isinstance(item, str):
            return super().__getitem__(0)[item]
        return super().__getitem__(item)


def load_teams_webhook_url(webhook_url: str | None = None) -> str:
    resolved = webhook_url or os.getenv("PERFSRAPER_TEAMS_WEBHOOK_URL")
    if not resolved:
        raise ValueError("Teams delivery requires --teams-webhook-url or PERFSRAPER_TEAMS_WEBHOOK_URL.")
    return resolved


def _format_percent(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def _row_is_stale(row: dict) -> bool:
    return bool(row.get("is_stale", row.get("stale_days", 0) > 0))


def _measurement_date(absolute_rows: list[dict], as_of_date) -> pd.Timestamp:
    benchmark = next((row for row in absolute_rows if row.get("is_benchmark")), None)
    latest_date = None if benchmark is None else benchmark.get("latest_date")
    if latest_date is not None:
        return pd.Timestamp(latest_date)
    return pd.Timestamp(as_of_date)


def _format_report_date(value) -> str:
    return f"{pd.Timestamp(value):%Y-%m-%d}"


def _format_fund_label(row: dict) -> str:
    label = str(row["Fund"])
    if row.get("is_disabled"):
        return f"{label} ({row.get('disabled_reason') or 'Source pending'})"
    if row.get("latest_date") is not None and int(row.get("stale_days") or 0) > 0:
        label = f"{label} (as of {pd.Timestamp(row['latest_date']):%Y-%m-%d})"
    return label


def _is_firetrail(row: dict) -> bool:
    return str(row.get("Fund", "")).casefold().startswith("firetrail ")


def _is_legacy_connector_webhook(webhook_url: str | None) -> bool:
    if not webhook_url:
        return False
    parsed = urlparse(webhook_url)
    host = (parsed.netloc or "").casefold()
    path = (parsed.path or "").casefold()
    return "webhook.office.com" in host or "/incomingwebhook/" in path


def teams_webhook_payload_mode(webhook_url: str | None) -> str:
    return "legacy MessageCard" if _is_legacy_connector_webhook(webhook_url) else "Adaptive Card"


def _text_block(
    text: str,
    *,
    weight: str | None = None,
    size: str | None = None,
    color: str | None = None,
    wrap: bool = True,
    horizontal_alignment: str | None = None,
) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "TextBlock", "text": text, "wrap": wrap}
    if weight:
        block["weight"] = weight
    if size:
        block["size"] = size
    if color:
        block["color"] = color
    if horizontal_alignment:
        block["horizontalAlignment"] = horizontal_alignment
    return block


def _value_text_block(
    value: float | None,
    *,
    error: bool = False,
    header: bool = False,
    highlight: PerformanceHighlight | None = None,
) -> dict[str, Any]:
    if header:
        return _text_block(_format_percent(value), weight="Bolder")
    if error:
        return _text_block("Error", color="Attention")
    if value is None:
        return _text_block("N/A", color="Accent")
    if highlight == HIGHLIGHT_TOP:
        return _text_block(_format_percent(value), color="Good", weight="Bolder")
    if highlight == HIGHLIGHT_BOTTOM:
        return _text_block(_format_percent(value), color="Attention", weight="Bolder")
    color = "Good" if value >= 0 else "Attention"
    return _text_block(_format_percent(value), color=color)


def _format_highlighted_percent(value: float | None, highlight: PerformanceHighlight | None = None) -> str:
    label = _format_percent(value)
    if highlight == HIGHLIGHT_TOP:
        return f"**{label}** {LEGACY_TOP_MARKER}"
    if highlight == HIGHLIGHT_BOTTOM:
        return f"**{label}** {LEGACY_BOTTOM_MARKER}"
    return label


def _highlight_cell_style(highlight: PerformanceHighlight | None) -> str | None:
    if highlight == HIGHLIGHT_TOP:
        return "good"
    if highlight == HIGHLIGHT_BOTTOM:
        return "attention"
    return None


def _average_by_style(rows: list[dict], period: str) -> list[dict[str, object]]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        if row.get("is_benchmark") or row.get("is_average") or row.get("error"):
            continue
        style = str(row.get("Style") or "").strip()
        value = row.get(period)
        if not style or value is None:
            continue
        grouped.setdefault(style, []).append(float(value))

    averages = [
        {"style": style, "average": sum(values) / len(values)}
        for style, values in grouped.items()
        if values
    ]
    return sorted(averages, key=lambda row: (-float(row["average"]), str(row["style"])))


def _style_commentary(absolute_rows: list[dict], relative_rows: list[dict]) -> str:
    absolute_styles = _average_by_style(absolute_rows, "12M")
    relative_styles = _average_by_style(relative_rows, "12M")

    if not absolute_styles and not relative_styles:
        return "No 12M style averages are available yet."

    absolute_leader = absolute_styles[0] if absolute_styles else None
    absolute_trailer = absolute_styles[-1] if len(absolute_styles) > 1 else None
    relative_leader = relative_styles[0] if relative_styles else None

    if absolute_leader and relative_leader and absolute_leader["style"] == relative_leader["style"]:
        commentary = (
            f"On 12M style averages, {absolute_leader['style']} leads both total return "
            f"({_format_percent(float(absolute_leader['average']))}) and excess return "
            f"({_format_percent(float(relative_leader['average']))} versus benchmark)."
        )
    elif absolute_leader and relative_leader:
        commentary = (
            f"On 12M style averages, {absolute_leader['style']} leads total return at "
            f"{_format_percent(float(absolute_leader['average']))}, while {relative_leader['style']} leads "
            f"excess return at {_format_percent(float(relative_leader['average']))} versus benchmark."
        )
    elif absolute_leader:
        commentary = (
            f"On 12M style averages, {absolute_leader['style']} leads total return at "
            f"{_format_percent(float(absolute_leader['average']))}."
        )
    else:
        commentary = (
            f"On 12M style averages, {relative_leader['style']} leads excess return at "
            f"{_format_percent(float(relative_leader['average']))} versus benchmark."
        )

    if absolute_trailer is not None and absolute_leader is not None and absolute_trailer["style"] != absolute_leader["style"]:
        commentary += (
            f" {absolute_trailer['style']} is the weakest total-return cohort at "
            f"{_format_percent(float(absolute_trailer['average']))}."
        )
    return commentary


def _snapshot(absolute_rows: list[dict], relative_rows: list[dict]) -> dict[str, Any]:
    benchmark = next((row for row in absolute_rows if row.get("is_benchmark")), None)
    funds = [row for row in absolute_rows if not row.get("is_benchmark") and not row.get("is_average")]
    fund_relative_rows = [row for row in relative_rows if not row.get("is_average")]
    valid_absolute = [row for row in funds if not row.get("error") and row.get("12M") is not None]
    valid_relative = [row for row in fund_relative_rows if not row.get("error") and row.get("12M") is not None]

    return {
        "benchmark": benchmark,
        "fund_count": len(funds),
        "stale_count": sum(1 for row in funds if _row_is_stale(row)),
        "ahead_count": sum(1 for row in valid_relative if float(row["12M"]) > 0),
        "best_absolute": max(valid_absolute, key=lambda row: float(row["12M"]), default=None),
        "best_relative": max(valid_relative, key=lambda row: float(row["12M"]), default=None),
        "leaders": sorted(valid_absolute, key=lambda row: float(row["12M"]), reverse=True)[:5],
        "style_commentary": _style_commentary(funds, fund_relative_rows),
    }


def _legacy_fund_label(row: dict) -> str:
    label = _format_fund_label(row)
    if row.get("is_benchmark"):
        return f"**{label}**"
    if _is_firetrail(row):
        return f"**{label}**"
    return label


def _build_plaintext_table(
    rows: list[dict],
    *,
    top_n: int = 3,
    bottom_n: int = 3,
    include_benchmark_highlight: bool = False,
) -> str:
    highlights = build_period_highlights(
        rows,
        periods=PERIODS,
        top_n=top_n,
        bottom_n=bottom_n,
        include_benchmark=include_benchmark_highlight,
    )
    headers = ["Fund", "Style", *[f"{period} p.a." if period in {"3Y", "5Y"} else period for period in PERIODS]]
    rendered_rows = []
    for row_index, row in enumerate(rows):
        rendered_rows.append(
            [
                _legacy_fund_label(row),
                str(row.get("Style") or ""),
                *[
                    _format_highlighted_percent(
                        None if row.get("error") else row.get(period),
                        highlights.get((row_index, period)),
                    )
                    for period in PERIODS
                ],
            ]
        )

    widths = [len(header) for header in headers]
    for row in rendered_rows:
        for index, value in enumerate(row):
            widths[index] = min(max(widths[index], len(value)), 42 if index == 0 else 12)

    def fit(value: str, width: int) -> str:
        return value if len(value) <= width else value[: max(width - 1, 1)] + "…"

    lines = []
    lines.append(" | ".join(fit(header, widths[index]).ljust(widths[index]) for index, header in enumerate(headers)))
    lines.append("-|-".join("-" * width for width in widths))
    for row in rendered_rows:
        lines.append(" | ".join(fit(value, widths[index]).ljust(widths[index]) for index, value in enumerate(row)))
    return f"{LEGACY_HIGHLIGHT_LEGEND}\n\n" + "\n".join(lines)


def _competitor_set_title(competitor_set) -> str:
    if isinstance(competitor_set, dict):
        return str(competitor_set.get("title") or "Competitor set")
    return str(getattr(competitor_set, "title", "Competitor set"))


def _competitor_set_rows(competitor_set) -> list[dict]:
    if isinstance(competitor_set, dict):
        return list(competitor_set.get("rows") or [])
    return list(getattr(competitor_set, "rows", []) or [])


def _adaptive_table_column(items: list[dict[str, Any]], *, width: str, style: str | None = None) -> dict[str, Any]:
    column: dict[str, Any] = {"type": "Column", "width": width, "items": items}
    if style:
        column["style"] = style
    return column


def _adaptive_table_row(cells: list[dict[str, Any]], *, separator: bool = False) -> dict[str, Any]:
    row: dict[str, Any] = {"type": "ColumnSet", "columns": cells, "spacing": "Small"}
    if separator:
        row["separator"] = True
    return row


def _build_adaptive_table(
    rows_source: list[dict],
    *,
    top_n: int = 3,
    bottom_n: int = 3,
    include_benchmark_highlight: bool = False,
) -> dict[str, Any]:
    """Build a Teams-safe table from ColumnSet rows.

    Teams Workflows currently accepts Adaptive Card payloads that contain the
    newer ``Table`` element, but the Teams renderer can silently drop that
    element. ColumnSet has much broader Teams support, so the report table is
    rendered as a header ColumnSet followed by one ColumnSet per data row.
    """

    headers = ["Fund", "Style", *[f"{period} (p.a.)" if period in {"3Y", "5Y"} else period for period in PERIODS]]
    column_widths = ["stretch", "auto", *["auto" for _ in PERIODS]]
    highlights = build_period_highlights(
        rows_source,
        periods=PERIODS,
        top_n=top_n,
        bottom_n=bottom_n,
        include_benchmark=include_benchmark_highlight,
    )

    header_cells = [
        _adaptive_table_column(
            [
                _text_block(
                    header,
                    weight="Bolder",
                    wrap=index < 2,
                    horizontal_alignment="Right" if index >= 2 else None,
                )
            ],
            width=column_widths[index],
        )
        for index, header in enumerate(headers)
    ]
    items: list[dict[str, Any]] = [_adaptive_table_row(header_cells)]

    if not rows_source:
        items.append(_text_block("No rows are available for this table.", color="Accent"))
        return {"type": "Container", "items": items}

    for row_index, row in enumerate(rows_source):
        label_block = _text_block(
            _format_fund_label(row),
            weight="Bolder" if row.get("is_benchmark") or row.get("is_average") or _is_firetrail(row) else None,
            color="Good" if _is_firetrail(row) else None,
        )
        cells = [
            _adaptive_table_column([label_block], width="stretch"),
            _adaptive_table_column([_text_block(str(row.get("Style") or ""))], width="auto"),
        ]
        for period in PERIODS:
            highlight = highlights.get((row_index, period))
            value_block = _value_text_block(
                row.get(period),
                error=row.get("error", False),
                highlight=highlight,
            )
            value_block["horizontalAlignment"] = "Right"
            cells.append(
                _adaptive_table_column(
                    [value_block],
                    width="auto",
                    style=_highlight_cell_style(highlight),
                )
            )
        items.append(_adaptive_table_row(cells, separator=True))

    return {"type": "Container", "items": items}


def _payload_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8"))


def _split_rows_for_size(rows: list[dict], build_payload) -> list[dict[str, Any]]:
    if not rows:
        return [build_payload([], 1, 1)]

    chunks: list[list[dict]] = []
    chunk: list[dict] = []
    for row in rows:
        candidate = [*chunk, row]
        # Use a deliberately high chunk count while sizing so final titles are no longer than the probe title.
        if chunk and _payload_size(build_payload(candidate, len(chunks) + 1, 99)) > MAX_TEAMS_CARD_BYTES:
            chunks.append(chunk)
            chunk = [row]
        else:
            chunk = candidate
    if chunk:
        chunks.append(chunk)

    chunk_count = len(chunks)
    return [build_payload(chunk_rows, index, chunk_count) for index, chunk_rows in enumerate(chunks, start=1)]


def _adaptive_message_payload(body: list[dict[str, Any]], summary: str) -> dict[str, Any]:
    return {
        "type": "message",
        "summary": summary,
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.5",
                    "msteams": {"width": "Full"},
                    "body": body,
                },
            }
        ],
    }


def _table_title(title: str, chunk_index: int, chunk_count: int) -> str:
    return title if chunk_count == 1 else f"{title} ({chunk_index}/{chunk_count})"


def _build_adaptive_table_cards(
    *,
    rows: list[dict],
    title: str,
    summary: str,
    description: str,
    intro_body: list[dict[str, Any]] | None = None,
    include_benchmark_highlight: bool = False,
) -> list[dict[str, Any]]:
    def build_payload(chunk_rows: list[dict], chunk_index: int, chunk_count: int) -> dict[str, Any]:
        table_title = _table_title(title, chunk_index, chunk_count)
        body = [*(intro_body or [])] if chunk_index == 1 else []
        body.extend(
            [
                _text_block(table_title, weight="Bolder", size="Medium"),
                _text_block(description),
                _build_adaptive_table(chunk_rows, include_benchmark_highlight=include_benchmark_highlight),
            ]
        )
        return _adaptive_message_payload(body, summary)

    return _split_rows_for_size(rows, build_payload)


def _build_adaptive_teams_message_card(absolute_rows: list[dict], relative_rows: list[dict], as_of_date, competitor_sets: list | None = None) -> list[dict[str, Any]]:
    snapshot = _snapshot(absolute_rows, relative_rows)
    benchmark = snapshot["benchmark"]
    best_absolute = snapshot["best_absolute"]
    best_relative = snapshot["best_relative"]
    report_date = _measurement_date(absolute_rows, as_of_date)
    report_date_label = _format_report_date(report_date)
    summary = f"Australian Equity Fund Scorecard | {report_date_label}"

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
    intro_body = [
        _text_block(summary, weight="Bolder", size="Large"),
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
                _text_block("Style lens", weight="Bolder", size="Medium"),
                _text_block(str(snapshot["style_commentary"])),
            ],
        },
        _text_block("Top 12M funds", weight="Bolder", size="Medium"),
        _text_block(top_funds),
    ]

    payloads = _build_adaptive_table_cards(
        rows=relative_rows,
        title="Relative performance table",
        summary=summary,
        description=(
            f"As at {report_date_label}. Fund rows show excess returns versus the benchmark, "
            "and the Average row is the simple mean of live funds."
        ),
        intro_body=intro_body,
    )
    for competitor_set in competitor_sets or []:
        payloads.extend(
            _build_adaptive_table_cards(
                rows=_competitor_set_rows(competitor_set),
                title=_competitor_set_title(competitor_set),
                summary=summary,
                description=f"Peer-set table as at {report_date_label}.",
                include_benchmark_highlight=False,
            )
        )
    return TeamsPayloadList(payloads)


def _legacy_payload(title: str, summary: str, text: str, sections: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": "1F6A5B",
        "summary": summary,
        "title": title,
        "text": text,
        "sections": sections,
    }


def _build_legacy_table_cards(
    *,
    rows: list[dict],
    title: str,
    summary: str,
    text: str,
    description: str,
    intro_sections: list[dict[str, Any]] | None = None,
    include_benchmark_highlight: bool = False,
) -> list[dict[str, Any]]:
    def build_payload(chunk_rows: list[dict], chunk_index: int, chunk_count: int) -> dict[str, Any]:
        table_title = _table_title(title, chunk_index, chunk_count)
        sections = [*(intro_sections or [])]
        sections.append(
            {
                "title": table_title,
                "text": f"{description}\n\n{_build_plaintext_table(chunk_rows, include_benchmark_highlight=include_benchmark_highlight)}",
                "markdown": True,
            }
        )
        return _legacy_payload(table_title if not intro_sections else summary, summary, text, sections)

    return _split_rows_for_size(rows, build_payload)


def _build_legacy_teams_message_card(absolute_rows: list[dict], relative_rows: list[dict], as_of_date, competitor_sets: list | None = None) -> list[dict[str, Any]]:
    snapshot = _snapshot(absolute_rows, relative_rows)
    benchmark = snapshot["benchmark"]
    best_absolute = snapshot["best_absolute"]
    best_relative = snapshot["best_relative"]
    report_date = _measurement_date(absolute_rows, as_of_date)
    report_date_label = _format_report_date(report_date)
    summary = f"Australian Equity Fund Scorecard | {report_date_label}"
    text = "All figures are total return. Relative highlights are measured against the S&P/ASX 200 Accumulation benchmark."

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

    intro_sections = [
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
        {"title": "Style lens", "text": str(snapshot["style_commentary"]), "markdown": True},
        {"title": "Top 12M funds", "text": top_funds, "markdown": True},
    ]

    payloads = _build_legacy_table_cards(
        rows=relative_rows,
        title=f"Relative performance table (as at {report_date_label})",
        summary=summary,
        text=text,
        description="Fund rows show excess returns versus the benchmark. Average row is the simple mean of live funds.",
        intro_sections=intro_sections,
    )
    for competitor_set in competitor_sets or []:
        payloads.extend(
            _build_legacy_table_cards(
                rows=_competitor_set_rows(competitor_set),
                title=_competitor_set_title(competitor_set),
                summary=summary,
                text=text,
                description=f"Peer-set table as at {report_date_label}.",
                include_benchmark_highlight=False,
            )
        )
    return TeamsPayloadList(payloads)


def build_teams_message_card(
    absolute_rows: list[dict],
    relative_rows: list[dict],
    as_of_date,
    webhook_url: str | None = None,
    competitor_sets: list | None = None,
) -> list[dict[str, Any]]:
    if _is_legacy_connector_webhook(webhook_url):
        return _build_legacy_teams_message_card(absolute_rows, relative_rows, as_of_date, competitor_sets=competitor_sets)
    return _build_adaptive_teams_message_card(absolute_rows, relative_rows, as_of_date, competitor_sets=competitor_sets)




def _payload_label(payload: dict[str, Any]) -> str:
    if "attachments" in payload:
        body = payload.get("attachments", [{}])[0].get("content", {}).get("body", [])
        if len(body) >= 3 and isinstance(body[-3], dict) and body[-3].get("type") == "TextBlock":
            return str(body[-3].get("text") or payload.get("summary") or "Teams card")
    return str(payload.get("title") or payload.get("summary") or "Teams card")


def _teams_error_guidance(webhook_url: str, status_code: int) -> str:
    if status_code not in {401, 403}:
        return ""
    mode = teams_webhook_payload_mode(webhook_url)
    return (
        f" Payload mode was {mode}. Verify the GitHub secret has the current Teams webhook URL, "
        "the workflow/connector is enabled, and the posting identity still has access to the channel. "
        "If the URL is a legacy connector URL, plan migration to a Teams Workflows webhook."
    )


def send_teams_message_card(
    webhook_url: str,
    absolute_rows: list[dict],
    relative_rows: list[dict],
    as_of_date,
    competitor_sets: list | None = None,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    payloads = build_teams_message_card(absolute_rows, relative_rows, as_of_date, webhook_url=webhook_url, competitor_sets=competitor_sets)
    http = session or requests.Session()
    for index, payload in enumerate(payloads, start=1):
        response = http.post(webhook_url, json=payload, timeout=20)
        if response.status_code >= 400:
            body = response.text.strip()
            snippet = body[:500] if body else "<empty response body>"
            title = _payload_label(payload)
            guidance = _teams_error_guidance(webhook_url, response.status_code)
            raise RuntimeError(
                f"Teams webhook returned HTTP {response.status_code} for card {index}/{len(payloads)} ({title}): {snippet}.{guidance}"
            )
    return payloads
