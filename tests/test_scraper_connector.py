from __future__ import annotations

import pandas as pd
import pytest

from connectors.scraper_connector import (
    _align_distributions_to_next_price_date,
    _build_airlie_price_and_distribution_frames,
    _build_smallco_price_and_distribution_frames,
    _extract_smallco_current_price,
    _merge_prices_and_distributions,
    _parse_bennelong_history_sheet,
    _parse_perpetual_distribution_table,
    _parse_report_csv,
)


def test_parse_perpetual_distribution_table_filters_summary_rows():
    raw_table = pd.DataFrame(
        [
            ["Report Period To", "Distribution Amount", "Reinvestment Price", None],
            ["2025 - 2026 Financial Year", "1.7455", None, None],
            ["December 2025 Download Report", "1.2488", "$1.647", "View Report"],
            ["September 2025 Download Report", "0.4967", "$1.722", "View Report"],
        ]
    )

    parsed = _parse_perpetual_distribution_table(raw_table)

    assert parsed["date"].dt.strftime("%Y-%m-%d").tolist() == ["2025-12-31", "2025-09-30"]
    assert parsed["distribution"].tolist() == [1.2488 / 100.0, 0.4967 / 100.0]


def test_align_distributions_to_next_price_date_prefers_next_trading_day():
    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-06-30", "2025-07-01", "2025-09-30", "2025-10-01"]),
            "nav": [1.48, 1.46, 1.73, 1.72],
        }
    )
    distributions = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-06-30", "2025-09-30"]),
            "distribution": [0.019491, 0.004967],
        }
    )

    aligned = _align_distributions_to_next_price_date(prices, distributions)

    assert aligned["date"].dt.strftime("%Y-%m-%d").tolist() == ["2025-07-01", "2025-10-01"]
    assert aligned["distribution"].tolist() == [0.019491, 0.004967]


def test_merge_prices_and_distributions_supports_next_price_date_timing():
    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-06-30", "2025-07-01", "2025-07-02"]),
            "nav": [100.0, 90.0, 91.0],
        }
    )
    distributions = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-06-30"]),
            "distribution": [10.0],
        }
    )

    merged = _merge_prices_and_distributions(
        prices,
        distributions,
        "2025-06-30",
        "2025-07-02",
        distribution_timing="next_price_date",
    )

    assert merged["distribution"].tolist() == [0.0, 10.0, 0.0]


def test_build_airlie_price_and_distribution_frames_uses_ex_rows():
    raw = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2025-12-31", "2025-12-31", "2025-12-30", "2026-01-02"]),
            "Exit": [3.8463, 3.7715, 3.8401, 3.7560],
            "Type": [None, "ex", None, None],
        }
    )

    prices, distributions = _build_airlie_price_and_distribution_frames(raw, "Exit")

    assert prices.to_dict(orient="records") == [
        {"date": pd.Timestamp("2025-12-30"), "nav": 3.8401},
        {"date": pd.Timestamp("2025-12-31"), "nav": 3.7715},
        {"date": pd.Timestamp("2026-01-02"), "nav": 3.7560},
    ]
    assert distributions.to_dict(orient="records") == [
        {"date": pd.Timestamp("2025-12-31"), "distribution": pytest.approx(0.0748)}
    ]


def test_parse_bennelong_history_sheet_uses_ex_distribution_redemption():
    sheet_text = """
Date\tApplication\tRedemption\tDistribution CPU\tEx Dist. Redemption
13/03/2026\t1.7649\\n\t1.7579
31/12/2025\t1.9876\t1.9796\t2.3357\t1.9564
30/12/2025\t1.9619\t1.9540
""".strip()

    parsed = _parse_bennelong_history_sheet(sheet_text, "Redemption")

    assert parsed.to_dict(orient="records") == [
        {"date": pd.Timestamp("2026-03-13"), "nav": 1.7579, "distribution": 0.0},
        {"date": pd.Timestamp("2025-12-31"), "nav": 1.9564, "distribution": pytest.approx(0.023357)},
        {"date": pd.Timestamp("2025-12-30"), "nav": 1.9540, "distribution": 0.0},
    ]


def test_build_smallco_price_and_distribution_frames_uses_ex_rows():
    tables = [
        pd.DataFrame(
            {
                "Date": ["Jul 25", "Jun 25", "Jun 25", None],
                "Unit Price": ["$2.1087", "$2.0084", "$2.3478", None],
                "Entry Price*": ["$2.1182", "$2.0174", "$2.3583", None],
                "Exit Price**": ["$2.0992", "$1.9993", "$2.3372", None],
                "Distributions": [None, None, "$0.3394", None],
            }
        )
    ]

    prices, distributions = _build_smallco_price_and_distribution_frames(tables, "Exit Price**")

    assert prices.to_dict(orient="records") == [
        {"date": pd.Timestamp("2025-06-30"), "nav": 1.9993},
        {"date": pd.Timestamp("2025-07-31"), "nav": 2.0992},
    ]
    assert distributions.to_dict(orient="records") == [
        {"date": pd.Timestamp("2025-06-30"), "distribution": pytest.approx(0.3394)}
    ]


def test_extract_smallco_current_price_uses_page_header():
    html = """
<svg>
  <text><tspan x="-19.465" y="0">25</tspan></text>
  <text><tspan x="-14.003" y="0">Mar</tspan></text>
</svg>
<p class="text-secondary fw-bold"><span class="text-uppercase">Last unit price date</span></p>
<p>$1.5290</p>
<p class="text-secondary fw-bold"><span class="text-uppercase">Exit Price</span></p>
""".strip()

    parsed = _extract_smallco_current_price(html, today=pd.Timestamp("2026-03-26"))

    assert parsed.to_dict(orient="records") == [
        {"date": pd.Timestamp("2026-03-25"), "nav": 1.5290}
    ]


def test_parse_report_csv_skips_report_preamble():
    csv_text = """
"Report Name","UNIT PRICE HISTORY"
"Report Period ","26 Mar 2021",TO,"26 Mar 2026"

"Fund Name"
Date,"Entry Price","Exit Price"
24-Mar-2026,2.5481,2.5369
23-Mar-2026,2.5422,2.5310
""".strip()

    parsed = _parse_report_csv(csv_text, 'Date,"Entry Price","Exit Price"')

    assert parsed.to_dict(orient="records") == [
        {"Date": "24-Mar-2026", "Entry Price": 2.5481, "Exit Price": 2.5369},
        {"Date": "23-Mar-2026", "Entry Price": 2.5422, "Exit Price": 2.5310},
    ]
