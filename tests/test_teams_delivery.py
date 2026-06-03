from __future__ import annotations

import json

import pandas as pd

from teams_delivery import MAX_TEAMS_CARD_BYTES, build_teams_message_card, send_teams_message_card, teams_webhook_payload_mode


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


def _competitor_sets():
    return [
        {
            "id": "market_neutral_funds",
            "title": "Absolute return funds",
            "rows": [
                {
                    "Fund": "S&P/ASX 200 Accumulation",
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
                    "Fund": "Bennelong Market Neutral Fund",
                    "Style": "Agnostic",
                    "is_disabled": True,
                    "disabled_reason": "No durable public historical unit price and distribution feed has been validated.",
                    "is_stale": False,
                    "error": False,
                    "stale_days": 0,
                    "latest_date": None,
                    "MTD": None,
                    "3M": None,
                    "6M": None,
                    "12M": None,
                    "3Y": None,
                    "5Y": None,
                },
            ],
        }
    ]


def _ranked_rows(count: int = 7):
    rows = []
    for index in range(1, count + 1):
        rows.append(
            {
                "Fund": f"Fund {index}",
                "Style": "Growth",
                "is_benchmark": False,
                "is_stale": False,
                "error": False,
                "stale_days": 0,
                "latest_date": None,
                "MTD": index / 100,
                "3M": index / 100,
                "6M": index / 100,
                "12M": index / 100,
                "3Y": index / 100,
                "5Y": index / 100,
            }
        )
    return rows


def _firetrail_rows():
    rows = _ranked_rows(3)
    rows[0]["Fund"] = "Firetrail High Conviction Fund"
    rows[1]["Fund"] = "Firetrail Alpha Plus Fund Complex ETF"
    rows[2]["Fund"] = "Other Fund"
    return rows


def _ranked_rows_with_high_benchmark():
    benchmark = {
        "Fund": "S&P/ASX 200 Accumulation",
        "Style": "",
        "is_benchmark": True,
        "is_stale": False,
        "error": False,
        "stale_days": 0,
        "latest_date": None,
        "MTD": 0.99,
        "3M": 0.99,
        "6M": 0.99,
        "12M": 0.99,
        "3Y": 0.99,
        "5Y": 0.99,
    }
    return [benchmark, *_ranked_rows()]


def test_build_teams_message_card_adaptive_includes_style_column():
    absolute_rows, relative_rows = _sample_rows()

    payload = build_teams_message_card(
        absolute_rows,
        relative_rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://example.com/webhook",
    )

    table = payload[1]["attachments"][0]["content"]["body"][-1]
    headers = [cell["items"][0]["text"] for cell in _adaptive_table_rows(table)[0]["columns"]]
    fund_row = _adaptive_table_rows(table)[1]["columns"]

    assert headers[1] == "Style"
    assert fund_row[1]["items"][0]["text"] == "Growth"


def test_build_teams_message_card_adaptive_headline_uses_benchmark_latest_nav_date():
    absolute_rows, relative_rows = _sample_rows()
    absolute_rows[0]["latest_date"] = pd.Timestamp("2026-03-28")

    payload = build_teams_message_card(
        absolute_rows,
        relative_rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://example.com/webhook",
    )

    content = payload["attachments"][0]["content"]
    body = content["body"]

    assert payload["summary"] == "Australian Equity Fund Scorecard | 2026-03-28"
    assert body[0]["text"] == "Australian Equity Fund Scorecard | 2026-03-28"
    assert payload[1]["attachments"][0]["content"]["body"][1]["text"].startswith("As at 2026-03-28.")


def test_build_teams_message_card_legacy_headline_uses_benchmark_latest_nav_date():
    absolute_rows, relative_rows = _sample_rows()
    absolute_rows[0]["latest_date"] = pd.Timestamp("2026-03-28")

    payload = build_teams_message_card(
        absolute_rows,
        relative_rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://webhook.office.com/example",
    )

    assert payload["summary"] == "Australian Equity Fund Scorecard | 2026-03-28"
    assert payload["title"] == "Australian Equity Fund Scorecard | 2026-03-28"
    assert payload["sections"][-1]["title"] == "Relative performance table (as at 2026-03-28)"


def _walk_adaptive_nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_adaptive_nodes(child)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_adaptive_nodes(item)


def _adaptive_table_rows(table):
    return [item for item in table["items"] if item.get("type") == "ColumnSet"]


def _payload_size(payload):
    return len(json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8"))


def test_adaptive_card_column_widths_are_strings():
    absolute_rows, relative_rows = _sample_rows()
    payloads = build_teams_message_card(
        absolute_rows,
        relative_rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://example.com/webhook",
        competitor_sets=[{"id": "competitors", "title": "Competitors", "rows": _ranked_rows(4)}],
    )

    widths = []
    for payload in payloads:
        content = payload["attachments"][0]["content"]
        for node in _walk_adaptive_nodes(content):
            if "width" in node:
                widths.append(node["width"])

    assert widths
    assert all(isinstance(width, str) for width in widths)
    assert all(width in {"auto", "stretch", "Full"} or width.replace(".", "", 1).isdigit() or width.endswith("px") for width in widths)


def test_adaptive_card_tables_use_teams_safe_columnsets():
    absolute_rows, relative_rows = _sample_rows()
    payloads = build_teams_message_card(
        absolute_rows,
        relative_rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://example.com/webhook",
        competitor_sets=[{"id": "competitors", "title": "Competitors", "rows": _ranked_rows(4)}],
    )

    tables = [
        node
        for payload in payloads
        for node in _walk_adaptive_nodes(payload["attachments"][0]["content"])
        if node.get("type") == "Container" and any(item.get("type") == "ColumnSet" for item in node.get("items", []))
    ]

    assert tables
    assert not any(node.get("type") == "Table" for payload in payloads for node in _walk_adaptive_nodes(payload["attachments"][0]["content"]))
    for table in tables:
        rows = _adaptive_table_rows(table)
        first_row = rows[0]
        first_row_text = [cell["items"][0]["text"] for cell in first_row["columns"]]
        expected_widths = ["360px", "78px", "58px", "58px", "58px", "64px", "76px", "76px"]

        assert first_row_text == [
            "Fund",
            "Style",
            "MTD",
            "3M",
            "6M",
            "12M",
            "3Y (p.a.)",
            "5Y (p.a.)",
        ]
        assert all([cell["width"] for cell in row["columns"]] == expected_widths for row in rows)
        assert not any("style" in cell for row in rows for cell in row["columns"])


def test_teams_payloads_include_relative_and_peer_tables_without_absolute_table():
    absolute_rows, relative_rows = _sample_rows()
    absolute_rows[0]["latest_date"] = pd.Timestamp("2026-03-28")
    competitor_sets = [
        {"id": "long_short", "title": "Long-short funds", "rows": _ranked_rows(2)},
        *_competitor_sets(),
    ]

    adaptive_payload = build_teams_message_card(
        absolute_rows,
        relative_rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://example.com/webhook",
        competitor_sets=competitor_sets,
    )
    adaptive_bodies = [payload["attachments"][0]["content"]["body"] for payload in adaptive_payload]
    adaptive_card_titles = [body[0].get("text") for body in adaptive_bodies]
    adaptive_titles = [
        block.get("text")
        for body in adaptive_bodies
        for block in body
        if block.get("type") == "TextBlock"
    ]
    adaptive_tables = [
        block
        for body in adaptive_bodies
        for block in body
        if block.get("type") == "Container" and any(item.get("type") == "ColumnSet" for item in block.get("items", []))
    ]

    assert adaptive_payload["summary"] == "Australian Equity Fund Scorecard | 2026-03-28"
    assert adaptive_card_titles == [
        "Australian Equity Fund Scorecard | 2026-03-28",
        "Relative performance table",
        "Long-short funds",
        "Absolute return funds",
    ]
    assert "Relative performance table" in adaptive_titles
    assert "Long-short funds" in adaptive_titles
    assert "Absolute return funds" in adaptive_titles
    assert "Full performance table" not in adaptive_titles
    assert len(adaptive_tables) == 3
    assert len(adaptive_payload) == 4
    assert _adaptive_table_rows(adaptive_tables[0])[1]["columns"][0]["items"][0]["text"] == "Fund A"
    assert all(
        row["columns"][0]["items"][0]["text"] != "Benchmark"
        for row in _adaptive_table_rows(adaptive_tables[0])[1:]
    )

    legacy_payload = build_teams_message_card(
        absolute_rows,
        relative_rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://webhook.office.com/example",
        competitor_sets=competitor_sets,
    )
    legacy_sections = [section for payload in legacy_payload for section in payload["sections"]]
    legacy_titles = [section.get("title") for section in legacy_sections if section.get("title")]
    relative_section = next(section for section in legacy_sections if str(section.get("title", "")).startswith("Relative performance table"))

    assert legacy_payload["title"] == "Australian Equity Fund Scorecard | 2026-03-28"
    assert len(legacy_payload) == 3
    assert "Long-short funds" in legacy_titles
    assert "Absolute return funds" in legacy_titles
    assert not any(str(title).startswith("Full performance table") for title in legacy_titles)
    assert "Fund A" in relative_section["text"]
    assert "Benchmark row shows absolute benchmark total returns" not in relative_section["text"]


def test_adaptive_default_sized_main_table_splits_without_compacting():
    absolute_rows, _ = _sample_rows()
    relative_rows = _ranked_rows(23)

    payloads = build_teams_message_card(
        absolute_rows,
        relative_rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://example.com/webhook",
    )

    table_payloads = payloads[1:]
    table_rows = [_adaptive_table_rows(payload["attachments"][0]["content"]["body"][-1]) for payload in table_payloads]
    payload_json = json.dumps(table_payloads, ensure_ascii=False)

    assert len(payloads) == 3
    assert all(_payload_size(payload) <= MAX_TEAMS_CARD_BYTES for payload in table_payloads)
    assert all(rows[0]["columns"][0]["items"][0]["text"] == "Fund" for rows in table_rows)
    assert all(rows[0]["columns"][1]["items"][0]["text"] == "Style" for rows in table_rows)
    assert sum(len(rows) - 1 for rows in table_rows) == 23
    assert table_rows[0][1]["columns"][0]["items"][0]["text"] == "Fund 1"
    assert table_rows[0][1]["columns"][1]["items"][0]["text"] == "Growth"
    assert table_rows[-1][-1]["columns"][0]["items"][0]["text"] == "Fund 23"
    assert "Fund [Style]" not in payload_json
    assert "\N{LARGE GREEN CIRCLE}" not in payload_json
    assert "\N{LARGE RED CIRCLE}" not in payload_json


def test_adaptive_main_table_splits_regular_tables_before_compacting():
    absolute_rows, _ = _sample_rows()
    relative_rows = _ranked_rows(80)

    payloads = build_teams_message_card(
        absolute_rows,
        relative_rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://example.com/webhook",
    )

    assert len(payloads) == 5
    table_payloads = payloads[1:]
    tables = [payload["attachments"][0]["content"]["body"][-1] for payload in table_payloads]
    table_rows = [_adaptive_table_rows(table) for table in tables]
    payload_json = json.dumps(table_payloads, ensure_ascii=False)
    highlighted_values = [
        cell["items"][0]
        for rows in table_rows
        for row in rows[1:]
        for cell in row["columns"][2:]
        if cell["items"][0].get("color")
    ]

    assert all(_payload_size(payload) <= MAX_TEAMS_CARD_BYTES for payload in table_payloads)
    assert all(rows[0]["columns"][0]["items"][0]["text"] == "Fund" for rows in table_rows)
    assert all(rows[0]["columns"][1]["items"][0]["text"] == "Style" for rows in table_rows)
    assert sum(len(rows) - 1 for rows in table_rows) == 80
    assert table_rows[0][1]["columns"][0]["items"][0]["text"] == "Fund 1"
    assert table_rows[0][1]["columns"][1]["items"][0]["text"] == "Growth"
    assert table_rows[-1][-1]["columns"][0]["items"][0]["text"] == "Fund 80"
    assert table_rows[-1][-1]["columns"][1]["items"][0]["text"] == "Growth"
    assert table_rows[0][-1]["columns"][2]["items"][0].get("color") is None
    assert table_rows[1][1]["columns"][2]["items"][0].get("color") is None
    assert {value["color"] for value in highlighted_values} == {"Attention", "Good"}
    assert "Fund [Style]" not in payload_json
    assert "\N{LARGE GREEN CIRCLE}" not in payload_json
    assert "\N{LARGE RED CIRCLE}" not in payload_json
    titles = [
        block.get("text")
        for payload in payloads
        for block in payload["attachments"][0]["content"]["body"]
        if block.get("type") == "TextBlock"
    ]
    assert "Relative performance table (1/4)" in titles
    assert "Relative performance table (4/4)" in titles


def test_adaptive_split_cards_only_include_scorecard_intro_once():
    absolute_rows, _ = _sample_rows()
    relative_rows = _ranked_rows(80)

    payloads = build_teams_message_card(
        absolute_rows,
        relative_rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://example.com/webhook",
    )

    bodies = [payload["attachments"][0]["content"]["body"] for payload in payloads]

    assert len(payloads) == 5
    assert bodies[0][0]["text"] == "Australian Equity Fund Scorecard | 2026-03-29"
    assert bodies[1][0]["text"] == "Relative performance table (1/4)"
    assert bodies[-1][0]["text"] == "Relative performance table (4/4)"
    assert sum(
        1
        for body in bodies
        for block in body
        if block.get("type") == "TextBlock" and block.get("text") == "Australian Equity Fund Scorecard | 2026-03-29"
    ) == 1


def test_build_teams_message_card_labels_rows_with_non_stale_date_offsets():
    absolute_rows, relative_rows = _sample_rows()
    relative_rows[0]["latest_date"] = pd.Timestamp("2026-03-28")
    relative_rows[0]["stale_days"] = 1
    relative_rows[0]["is_stale"] = False

    payload = build_teams_message_card(
        absolute_rows,
        relative_rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://example.com/webhook",
    )

    table = payload[1]["attachments"][0]["content"]["body"][-1]

    assert _adaptive_table_rows(table)[1]["columns"][0]["items"][0]["text"] == "Fund A (as of 2026-03-28)"


def test_send_teams_message_card_posts_each_card_and_reports_failing_card():
    class FakeResponse:
        def __init__(self, status_code: int):
            self.status_code = status_code
            self.text = ""

    class FakeSession:
        def __init__(self):
            self.posts = []

        def post(self, webhook_url, json, timeout):
            self.posts.append(json)
            return FakeResponse(200 if len(self.posts) == 1 else 403)

    absolute_rows, relative_rows = _sample_rows()
    session = FakeSession()

    try:
        send_teams_message_card(
            "https://webhook.office.com/example",
            absolute_rows,
            relative_rows,
            pd.Timestamp("2026-03-29"),
            competitor_sets=[{"id": "competitors", "title": "Competitors", "rows": _ranked_rows()}],
            session=session,
            sleeper=lambda _seconds: None,
        )
    except RuntimeError as exc:
        message = str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected Teams delivery to fail")

    assert len(session.posts) == 2
    assert "HTTP 403" in message
    assert "card 2/2" in message
    assert "Competitors" in message
    assert "Payload mode was legacy MessageCard" in message
    assert "workflow/connector is enabled" in message


def test_send_teams_message_card_posts_payloads_in_order_with_delays():
    class FakeResponse:
        status_code = 200
        text = ""

    class FakeSession:
        def __init__(self):
            self.posts = []

        def post(self, webhook_url, json, timeout):
            self.posts.append(json)
            return FakeResponse()

    absolute_rows, _ = _sample_rows()
    relative_rows = _ranked_rows(23)
    session = FakeSession()
    delays = []

    payloads = send_teams_message_card(
        "https://example.com/webhook",
        absolute_rows,
        relative_rows,
        pd.Timestamp("2026-03-29"),
        competitor_sets=[
            {"id": "long_short", "title": "Long-short funds", "rows": _ranked_rows(2)},
            *_competitor_sets(),
        ],
        session=session,
        post_delay_seconds=0.25,
        sleeper=delays.append,
    )
    posted_titles = [post["attachments"][0]["content"]["body"][0]["text"] for post in session.posts]

    assert payloads == session.posts
    assert posted_titles == [
        "Australian Equity Fund Scorecard | 2026-03-29",
        "Relative performance table (1/2)",
        "Relative performance table (2/2)",
        "Long-short funds",
        "Absolute return funds",
    ]
    assert delays == [0.25, 0.25, 0.25, 0.25]


def test_teams_webhook_payload_mode_identifies_legacy_and_adaptive_urls():
    assert teams_webhook_payload_mode("https://tenant.webhook.office.com/example") == "legacy MessageCard"
    assert teams_webhook_payload_mode("https://prod-00.logic.azure.com/workflows/example/triggers/manual/paths/invoke") == "Adaptive Card"


def test_build_teams_message_card_adaptive_uses_dynamic_top_and_bottom_highlight_count():
    rows = _ranked_rows()

    payload = build_teams_message_card(
        rows,
        rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://example.com/webhook",
    )

    table = payload[1]["attachments"][0]["content"]["body"][-1]
    first_mtd_cell = _adaptive_table_rows(table)[1]["columns"][2]
    third_mtd_cell = _adaptive_table_rows(table)[3]["columns"][2]
    third_last_mtd_cell = _adaptive_table_rows(table)[-3]["columns"][2]
    last_mtd_cell = _adaptive_table_rows(table)[-1]["columns"][2]
    first_mtd = first_mtd_cell["items"][0]
    last_mtd = last_mtd_cell["items"][0]

    assert "style" not in first_mtd_cell
    assert first_mtd["color"] == "Attention"
    assert first_mtd["weight"] == "Bolder"
    assert "style" not in third_mtd_cell
    assert third_mtd_cell["items"][0].get("color") is None
    assert "style" not in third_last_mtd_cell
    assert third_last_mtd_cell["items"][0].get("color") is None
    assert "style" not in last_mtd_cell
    assert last_mtd["color"] == "Good"
    assert last_mtd["weight"] == "Bolder"


def test_build_teams_message_card_adaptive_appends_competitor_set_tables():
    absolute_rows, relative_rows = _sample_rows()

    payload = build_teams_message_card(
        absolute_rows,
        relative_rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://example.com/webhook",
        competitor_sets=_competitor_sets(),
    )

    assert len(payload) == 3
    body = payload[2]["attachments"][0]["content"]["body"]
    assert body[-3]["text"] == "Absolute return funds"
    assert body[-1]["type"] == "Container"
    assert "Bennelong Market Neutral Fund" in _adaptive_table_rows(body[-1])[2]["columns"][0]["items"][0]["text"]


def test_build_teams_message_card_adaptive_competitor_tables_use_dynamic_top_and_bottom_highlight_count():
    absolute_rows, relative_rows = _sample_rows()

    payload = build_teams_message_card(
        absolute_rows,
        relative_rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://example.com/webhook",
        competitor_sets=[{"id": "competitors", "title": "Competitors", "rows": _ranked_rows()}],
    )

    table = payload[2]["attachments"][0]["content"]["body"][-1]
    first_mtd_cell = _adaptive_table_rows(table)[1]["columns"][2]
    second_mtd_cell = _adaptive_table_rows(table)[2]["columns"][2]
    third_mtd_cell = _adaptive_table_rows(table)[3]["columns"][2]
    third_last_mtd_cell = _adaptive_table_rows(table)[-3]["columns"][2]
    second_last_mtd_cell = _adaptive_table_rows(table)[-2]["columns"][2]
    last_mtd_cell = _adaptive_table_rows(table)[-1]["columns"][2]
    first_mtd = first_mtd_cell["items"][0]
    second_mtd = second_mtd_cell["items"][0]
    second_last_mtd = second_last_mtd_cell["items"][0]
    last_mtd = last_mtd_cell["items"][0]

    assert "style" not in first_mtd_cell
    assert first_mtd["color"] == "Attention"
    assert first_mtd["weight"] == "Bolder"
    assert "style" not in second_mtd_cell
    assert second_mtd["color"] == "Attention"
    assert second_mtd["weight"] == "Bolder"
    assert "style" not in third_mtd_cell
    assert third_mtd_cell["items"][0].get("color") is None
    assert "style" not in third_last_mtd_cell
    assert third_last_mtd_cell["items"][0].get("color") is None
    assert "style" not in second_last_mtd_cell
    assert second_last_mtd["color"] == "Good"
    assert second_last_mtd["weight"] == "Bolder"
    assert "style" not in last_mtd_cell
    assert last_mtd["color"] == "Good"
    assert last_mtd["weight"] == "Bolder"


def test_build_teams_message_card_adaptive_competitor_highlights_ignore_benchmark_row():
    absolute_rows, relative_rows = _sample_rows()

    payload = build_teams_message_card(
        absolute_rows,
        relative_rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://example.com/webhook",
        competitor_sets=[{"id": "competitors", "title": "Competitors", "rows": _ranked_rows_with_high_benchmark()}],
    )

    table = payload[2]["attachments"][0]["content"]["body"][-1]
    benchmark_mtd = _adaptive_table_rows(table)[1]["columns"][2]["items"][0]
    lowest_fund_mtd_cell = _adaptive_table_rows(table)[2]["columns"][2]
    highest_fund_mtd_cell = _adaptive_table_rows(table)[-1]["columns"][2]
    lowest_fund_mtd = lowest_fund_mtd_cell["items"][0]
    highest_fund_mtd = highest_fund_mtd_cell["items"][0]

    assert benchmark_mtd.get("weight") is None
    assert "style" not in lowest_fund_mtd_cell
    assert lowest_fund_mtd["color"] == "Attention"
    assert lowest_fund_mtd["weight"] == "Bolder"
    assert "style" not in highest_fund_mtd_cell
    assert highest_fund_mtd["color"] == "Good"
    assert highest_fund_mtd["weight"] == "Bolder"


def test_build_teams_message_card_adaptive_bolds_all_firetrail_funds():
    rows = _firetrail_rows()

    payload = build_teams_message_card(
        rows,
        rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://example.com/webhook",
    )

    table = payload[1]["attachments"][0]["content"]["body"][-1]

    assert _adaptive_table_rows(table)[1]["columns"][0]["items"][0]["weight"] == "Bolder"
    assert _adaptive_table_rows(table)[2]["columns"][0]["items"][0]["weight"] == "Bolder"
    assert _adaptive_table_rows(table)[3]["columns"][0]["items"][0].get("weight") is None


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


def test_build_teams_message_card_legacy_marks_dynamic_best_and_worst_with_emoji_suffix():
    rows = _ranked_rows()

    payload = build_teams_message_card(
        rows,
        rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://webhook.office.com/example",
    )

    table_text = payload["sections"][-1]["text"]
    green_marker = "\N{LARGE GREEN CIRCLE}"
    red_marker = "\N{LARGE RED CIRCLE}"

    assert "Best" not in table_text
    assert "Worst" not in table_text
    assert f"**7.0%** {green_marker}" in table_text
    assert f"**6.0%** {green_marker}" in table_text
    assert f"**5.0%** {green_marker}" not in table_text
    assert f"**1.0%** {red_marker}" in table_text
    assert f"**2.0%** {red_marker}" in table_text
    assert f"**3.0%** {red_marker}" not in table_text
    assert "Green circles mark best performers" in table_text


def test_build_teams_message_card_legacy_competitor_tables_mark_dynamic_best_and_worst_with_emoji_suffix():
    absolute_rows, relative_rows = _sample_rows()

    payload = build_teams_message_card(
        absolute_rows,
        relative_rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://webhook.office.com/example",
        competitor_sets=[{"id": "competitors", "title": "Competitors", "rows": _ranked_rows()}],
    )

    table_text = payload[1]["sections"][-1]["text"]
    green_marker = "\N{LARGE GREEN CIRCLE}"
    red_marker = "\N{LARGE RED CIRCLE}"

    assert "Best" not in table_text
    assert "Worst" not in table_text
    assert f"**1.0%** {red_marker}" in table_text
    assert f"**2.0%** {red_marker}" in table_text
    assert f"**3.0%** {red_marker}" not in table_text
    assert f"**5.0%** {green_marker}" not in table_text
    assert f"**6.0%** {green_marker}" in table_text
    assert f"**7.0%** {green_marker}" in table_text
    assert "Green circles mark best performers" in table_text


def test_build_teams_message_card_legacy_bolds_all_firetrail_funds_without_emoji_prefix():
    rows = _firetrail_rows()

    payload = build_teams_message_card(
        rows,
        rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://webhook.office.com/example",
    )

    table_text = payload["sections"][-1]["text"]

    assert "**Firetrail High Conviction Fund**" in table_text
    assert "**Firetrail Alpha Plus Fund Complex ETF**" in table_text
    assert "🟢 **Firetrail" not in table_text


def test_build_teams_message_card_legacy_appends_competitor_set_sections():
    absolute_rows, relative_rows = _sample_rows()

    payload = build_teams_message_card(
        absolute_rows,
        relative_rows,
        pd.Timestamp("2026-03-29"),
        webhook_url="https://webhook.office.com/example",
        competitor_sets=_competitor_sets(),
    )

    assert payload[1]["sections"][-1]["title"] == "Absolute return funds"
    assert "Bennelong Market Neutral Fund" in payload[1]["sections"][-1]["text"]
