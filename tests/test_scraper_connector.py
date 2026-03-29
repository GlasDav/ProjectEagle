from __future__ import annotations

import pandas as pd
import pytest

from connectors.scraper_connector import (
    _align_distributions_to_next_price_date,
    _build_allan_gray_fact_sheet_candidates,
    _build_airlie_price_and_distribution_frames,
    _build_chester_price_and_distribution_frames,
    _build_solaris_price_and_distribution_frames,
    _build_smallco_price_and_distribution_frames,
    _extract_smallco_current_price,
    _merge_prices_and_distributions,
    _parse_allan_gray_fact_sheet_distributions,
    _parse_eqt_historical_prices_page,
    _parse_hyperion_distribution_sheet,
    _parse_bennelong_history_sheet,
    _parse_perpetual_distribution_table,
    _parse_report_csv,
    _parse_selector_unit_prices_frame,
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


def test_build_solaris_price_and_distribution_frames_uses_ex_exit_price():
    price_history = pd.DataFrame(
        {
            "Date": ["31/12/2025", "02/01/2026"],
            "Entry Price": ["1.3593", "1.3398"],
            "NAV": ["1.3552", "1.3358"],
            "Exit Price": ["1.3511", "1.3318"],
        }
    )
    distribution_history = pd.DataFrame(
        {
            "Ex Date": ["31/12/2025"],
            "Entry Price": ["1.3593"],
            "NAV": ["1.3552"],
            "Exit Price": ["1.3511"],
            "Ex Entry Price": ["1.3384"],
            "Ex NAV": ["1.3344"],
            "Ex Exit Price": ["1.3304"],
            "Cash Portion": ["2.0852"],
            "Franking Credits": ["0.7162"],
        }
    )

    prices, distributions = _build_solaris_price_and_distribution_frames(
        price_history,
        distribution_history,
        "Exit Price",
        "Ex Exit Price",
        "Cash Portion",
    )

    assert prices.to_dict(orient="records") == [
        {"date": pd.Timestamp("2025-12-31"), "nav": 1.3304},
        {"date": pd.Timestamp("2026-01-02"), "nav": 1.3318},
    ]
    assert distributions.to_dict(orient="records") == [
        {"date": pd.Timestamp("2025-12-31"), "distribution": pytest.approx(0.020852)}
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


def test_build_chester_price_and_distribution_frames_prefers_ex_row_on_distribution_dates():
    raw = pd.DataFrame(
        {
            "PriceDt": [
                "28/06/2018 0:00:00",
                "29/06/2018 0:00:00",
                "29/06/2018 0:00:00",
                "2018/2/7 12:00 AM",
            ],
            "App": [1.314579, 1.284971, 1.318303, 1.280423],
            "NAV": [1.310648, 1.281127, 1.314360, 1.276593],
            "Red": [1.306716, 1.277284, 1.310417, 1.272764],
            "Expr1": [None, None, "CUM", None],
            "Dist": [None, 0.033247, None, None],
        }
    )

    prices, distributions = _build_chester_price_and_distribution_frames(raw, "Red")

    assert prices.to_dict(orient="records") == [
        {"date": pd.Timestamp("2018-06-28"), "nav": 1.306716},
        {"date": pd.Timestamp("2018-06-29"), "nav": 1.277284},
        {"date": pd.Timestamp("2018-07-02"), "nav": 1.272764},
    ]
    assert distributions.to_dict(orient="records") == [
        {"date": pd.Timestamp("2018-06-29"), "distribution": pytest.approx(0.033247)}
    ]


def test_parse_selector_unit_prices_frame_reads_exit_price_and_distribution():
    raw = pd.DataFrame(
        {
            "Date": ["2005-05-31", "2005-06-30", "2005-07-31"],
            "Mid Price": [1.1249, 1.2358, 1.2621],
            "Entry Price": [1.1277, 1.2389, 1.2653],
            "Exit Price": [1.1221, 1.2327, 1.2589],
            "Distribution": [None, 0.0198, None],
        }
    )

    prices, distributions = _parse_selector_unit_prices_frame(raw, "Exit Price")

    assert prices.to_dict(orient="records") == [
        {"date": pd.Timestamp("2005-05-31"), "nav": 1.1221},
        {"date": pd.Timestamp("2005-06-30"), "nav": 1.2327},
        {"date": pd.Timestamp("2005-07-31"), "nav": 1.2589},
    ]
    assert distributions.to_dict(orient="records") == [
        {"date": pd.Timestamp("2005-06-30"), "distribution": pytest.approx(0.0198)}
    ]


def test_parse_eqt_historical_prices_page_extracts_sell_prices():
    page_html = r"""
    <script>
    self.__next_f.push([1,"34:[\"$\",\"section\",null,{\"columns\":[],\"data\":[{\"fundPriceID\":1,\"fundID\":\"ETL0349\",\"priceDate\":\"2025-06-30T00:00:00Z\",\"buy\":1.52,\"sell\":1.51,\"nav\":1.515,\"status\":1,\"statusDescription\":\"Valid\"},{\"fundPriceID\":2,\"fundID\":\"ETL0349\",\"priceDate\":\"2025-07-01T00:00:00Z\",\"buy\":1.31,\"sell\":1.30,\"nav\":1.305,\"status\":1,\"statusDescription\":\"Valid\"}],\"pageSize\":20}"])
    </script>
    """

    parsed = _parse_eqt_historical_prices_page(page_html, "ETL0349", "sell")

    assert parsed.to_dict(orient="records") == [
        {"date": pd.Timestamp("2025-06-30"), "nav": 1.51},
        {"date": pd.Timestamp("2025-07-01"), "nav": 1.30},
    ]


def test_build_allan_gray_fact_sheet_candidates_transforms_latest_class_a_link():
    page_html = """
    <a href="https://www.allangray.com.au/wp-content/uploads/AGA-Documents/Australia-and-New-Zealand/Fact-Sheets/AGA-Equity-Fund-Class-A/Allan-Gray-Australia-Equity-Fund-Fact-Sheet-Class-A-February-2026.pdf">Class A</a>
    """

    candidates = _build_allan_gray_fact_sheet_candidates(page_html, "B")

    assert candidates[0] == (
        "https://www.allangray.com.au/wp-content/uploads/AGA-Documents/Australia-and-New-Zealand/Fact-Sheets/"
        "AGA-Equity-Fund-Class-B/Allan-Gray-Australia-Equity-Fund-Fact-Sheet-Class-B-February-2026.pdf"
    )


def test_parse_allan_gray_fact_sheet_distributions_reads_recent_annual_rows():
    pdf_text = """
Allan Gray Australia Equity Fund (Class B)
Distributions
Year Cents per unit Distribution return
30 June 2025 22.8068 14.2%
30 June 2024 13.0756 8.0%
30 June 2023 16.1629 10.7%
30 June 2022 15.2742 9.7%
30 June 2021 5.8262 4.6%
""".strip()

    parsed = _parse_allan_gray_fact_sheet_distributions(pdf_text)

    assert parsed.to_dict(orient="records") == [
        {"date": pd.Timestamp("2025-06-30"), "distribution": pytest.approx(0.228068)},
        {"date": pd.Timestamp("2024-06-30"), "distribution": pytest.approx(0.130756)},
        {"date": pd.Timestamp("2023-06-30"), "distribution": pytest.approx(0.161629)},
        {"date": pd.Timestamp("2022-06-30"), "distribution": pytest.approx(0.152742)},
        {"date": pd.Timestamp("2021-06-30"), "distribution": pytest.approx(0.058262)},
    ]


def test_parse_hyperion_distribution_sheet_supports_quarter_groups():
    sheet = pd.DataFrame(
        {
            "Fund": [
                "Distn Components for September 2025",
                None,
                "Australian sourced income",
                "Total",
                "Total Non Cash Distribution",
                "Total Cash Distribution",
            ],
            "CPU": [None, None, "CPU", 1.677394, 0.318028, 1.359367],
            "Spacer": [None, None, None, None, None, None],
            "Fund.1": [
                "Distn Components for December 2025",
                None,
                "Australian sourced income",
                "Total",
                "Total Non Cash Distribution",
                "Total Cash Distribution",
            ],
            "CPU.1": [None, None, "CPU", 0.4631, 0.0, 0.4631],
        }
    )

    parsed = _parse_hyperion_distribution_sheet(sheet)

    assert parsed.to_dict(orient="records") == [
        {"date": pd.Timestamp("2025-09-30"), "distribution": pytest.approx(0.01359367)},
        {"date": pd.Timestamp("2025-12-31"), "distribution": pytest.approx(0.004631)},
    ]


def test_parse_hyperion_distribution_sheet_supports_date_row_layout():
    sheet = pd.DataFrame(
        {
            "Fund": [
                "APIR",
                None,
                "Australian sourced income",
                "Total",
                "Total Non Cash Distribution",
                "Total Cash Distribution",
            ],
            "Sep": ["BNT0003AU", pd.Timestamp("2023-09-30"), "CPU", 1.829028, 0.191957, 1.637071],
            "Dec": [None, pd.Timestamp("2023-12-31"), "CPU", 0.069186, 0.007261, 0.061925],
        }
    )

    parsed = _parse_hyperion_distribution_sheet(sheet)

    assert parsed.to_dict(orient="records") == [
        {"date": pd.Timestamp("2023-09-30"), "distribution": pytest.approx(0.01637071)},
        {"date": pd.Timestamp("2023-12-31"), "distribution": pytest.approx(0.00061925)},
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
