from __future__ import annotations

import pandas as pd
import pytest

from connectors.scraper_connector import (
    _align_distributions_to_next_price_date,
    _apply_configured_price_scaling,
    _build_allan_gray_fact_sheet_candidates,
    _build_airlie_price_and_distribution_frames,
    _build_chester_price_and_distribution_frames,
    _build_first_sentier_history_file_path,
    _build_forager_price_and_distribution_frames,
    _build_gsfm_price_and_distribution_frames,
    _build_macquarie_history_url,
    _parse_lazard_annual_distribution_pdf_text,
    _parse_dnr_distribution_history_table,
    _extend_lazard_history_with_performance_anchors,
    _parse_lazard_historical_nav,
    _parse_lazard_legacy_distribution_pdf_text,
    _parse_macquarie_historical_price_csv,
    _build_solaris_price_and_distribution_frames,
    _build_smallco_price_and_distribution_frames,
    _extract_smallco_current_price,
    _parse_first_sentier_history_csv,
    _parse_iml_distribution_history,
    _parse_iml_unit_price_history,
    _parse_katana_annual_distributions,
    _parse_katana_daily_price,
    _parse_katana_monthly_prices,
    _parse_channelcapital_unit_price_csv,
    _parse_cfs_history_csv,
    _merge_prices_and_distributions,
    _parse_allan_gray_fact_sheet_distributions,
    _parse_eqt_historical_prices_page,
    _parse_hyperion_distribution_sheet,
    _parse_bennelong_history_sheet,
    _parse_paradice_price_history_csv,
    _parse_perpetual_distribution_table,
    _parse_report_csv,
    _parse_selector_unit_prices_frame,
    _find_selector_unit_prices_workbook_url,
    _parse_allan_gray_fact_sheet_latest_price,
    _parse_vanguard_distribution_history,
    _parse_vanguard_price_history,
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


def test_apply_configured_price_scaling_scales_rows_before_cutoff_only():
    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-21", "2026-01-22"]),
            "nav": [1.2491, 11.2918],
        }
    )
    distributions = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-02", "2026-07-01"]),
            "distribution": [0.00156426, 0.013925],
        }
    )

    scaled_prices, scaled_distributions = _apply_configured_price_scaling(
        prices,
        distributions,
        {
            "price_scale_before_date": "2026-01-22",
            "price_scale_before_factor": 10,
        },
    )

    assert scaled_prices["nav"].tolist() == pytest.approx([12.491, 11.2918])
    assert scaled_distributions["distribution"].tolist() == pytest.approx([0.0156426, 0.013925])
    assert prices["nav"].tolist() == [1.2491, 11.2918]


def test_parse_channelcapital_unit_price_csv_handles_price_and_distribution_columns():
    csv_text = """Date ,Application Price ($) ,NAV Price ($) ,Redemption Price ($) ,Distribution ($) ,Fund Growth of $10,000
2026-01-02,1.1123,1.1090,1.1056,,10000
2026-01-05,1.1234,1.1201,1.1168,0.0123,10100
"""

    prices, distributions = _parse_channelcapital_unit_price_csv(
        csv_text,
        price_field="Redemption Price ($)",
        distribution_field="Distribution ($)",
    )

    assert prices["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-01-02", "2026-01-05"]
    assert prices["nav"].tolist() == pytest.approx([1.1056, 1.1168])
    assert distributions["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-01-05"]
    assert distributions["distribution"].tolist() == pytest.approx([0.0123])


def test_parse_cfs_history_csv_uses_post_income_exit_price_and_distribution():
    csv_text = """
13/05/2026,1.4276,,1.4233
11/12/2025,1.4566,1.4260,1.4522
30/06/2025,1.4758,1.4391,1.4714
21/03/2026,1.3973,0,1.3931
""".strip()

    prices, distributions = _parse_cfs_history_csv(csv_text, "Exit Price")

    assert prices.to_dict(orient="records") == [
        {"date": pd.Timestamp("2026-05-13"), "nav": 1.4233},
        {"date": pd.Timestamp("2025-12-11"), "nav": 1.4260},
        {"date": pd.Timestamp("2025-06-30"), "nav": 1.4391},
        {"date": pd.Timestamp("2026-03-21"), "nav": 1.3931},
    ]
    assert distributions.to_dict(orient="records") == [
        {"date": pd.Timestamp("2025-12-11"), "distribution": pytest.approx(0.0262)},
        {"date": pd.Timestamp("2025-06-30"), "distribution": pytest.approx(0.0323)},
    ]


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


def test_parse_iml_unit_price_history_reads_exit_prices():
    csv_text = """
Date,Entry,Exit
01/04/2026,2.6063,2.5933
31/03/2026,2.5667,2.5539
30/03/2026,2.5670,2.5542
""".strip()

    parsed = _parse_iml_unit_price_history(csv_text, "Exit")

    assert parsed.to_dict(orient="records") == [
        {"date": pd.Timestamp("2026-04-01"), "nav": 2.5933},
        {"date": pd.Timestamp("2026-03-31"), "nav": 2.5539},
        {"date": pd.Timestamp("2026-03-30"), "nav": 2.5542},
    ]


def test_parse_iml_distribution_history_maps_period_end_to_month_end():
    csv_text = """
"Period ending","Amount (cpu)"
"2025 December",5.5000
"2025 June",23.8700
"2002 November",0.0000
""".strip()

    parsed = _parse_iml_distribution_history(csv_text)

    assert parsed.to_dict(orient="records") == [
        {"date": pd.Timestamp("2025-12-31"), "distribution": pytest.approx(0.055)},
        {"date": pd.Timestamp("2025-06-30"), "distribution": pytest.approx(0.2387)},
    ]


def test_build_forager_price_and_distribution_frames_prefers_distribution_row():
    raw = pd.DataFrame(
        {
            "Date": [
                "2025-12-31",
                "2025-12-31",
                "2025-12-30",
                "2024-06-30",
                "2024-06-30",
            ],
            "Redemption Price": [2.1987, 2.2586, 2.1000, 1.5276, 1.5558],
            "Distribution": [0.0600, None, None, 0.0300, None],
        }
    )

    prices, distributions = _build_forager_price_and_distribution_frames(raw, "Redemption Price")

    assert prices.to_dict(orient="records") == [
        {"date": pd.Timestamp("2024-06-30"), "nav": 1.5276},
        {"date": pd.Timestamp("2025-12-30"), "nav": 2.1000},
        {"date": pd.Timestamp("2025-12-31"), "nav": 2.1987},
    ]
    assert distributions.to_dict(orient="records") == [
        {"date": pd.Timestamp("2024-06-30"), "distribution": pytest.approx(0.03)},
        {"date": pd.Timestamp("2025-12-31"), "distribution": pytest.approx(0.06)},
    ]


def test_build_forager_price_and_distribution_frames_supports_legacy_distribution_fallback():
    raw = pd.DataFrame(
        {
            "Date": ["2023-06-28", "2023-06-29", "2023-06-30", "2023-07-03"],
            "Mid Price": [1.19, 1.17, 1.21, 1.21],
            "Redemption Price": [None, 0.03, None, None],
            "Distribution": [None, None, None, None],
        }
    )

    prices, distributions = _build_forager_price_and_distribution_frames(raw, "Mid Price")

    assert prices.to_dict(orient="records") == [
        {"date": pd.Timestamp("2023-06-28"), "nav": 1.19},
        {"date": pd.Timestamp("2023-06-29"), "nav": 1.17},
        {"date": pd.Timestamp("2023-06-30"), "nav": 1.21},
        {"date": pd.Timestamp("2023-07-03"), "nav": 1.21},
    ]
    assert distributions.to_dict(orient="records") == [
        {"date": pd.Timestamp("2023-06-29"), "distribution": pytest.approx(0.03)}
    ]


def test_build_first_sentier_history_file_path_normalizes_query():
    assert _build_first_sentier_history_file_path("16-KIDS26-AU-EN-adviser") == (
        "cfsgam/historical-price/AU/en/adviser/16_KIDS26_AU_EN_adviser.json"
    )


def test_parse_first_sentier_history_csv_reads_exit_prices_and_distributions():
    csv_text = """
"RQI Investors",
"FUND","APIR","DATE","ENTRY PRICE (AUD)","UNIT PRICE (AUD)","EXIT PRICE (AUD)","DISTRIBUTION",
"RQI Australian Value - Class A (CFSIL)","FSF0976AU","01 Apr 2026","1.1788","1.1776","1.1764","",
"RQI Australian Value - Class A (CFSIL)","FSF0976AU","26 Mar 2026","1.1572","1.1560","1.1548","2.7800",
"RQI Australian Value - Class A (CFSIL)","FSF0976AU","25 Mar 2026","1.1200","1.1190","1.1180","",
""".strip()

    prices, distributions = _parse_first_sentier_history_csv(csv_text, "EXIT PRICE (AUD)")

    assert prices.to_dict(orient="records") == [
        {"date": pd.Timestamp("2026-04-01"), "nav": 1.1764},
        {"date": pd.Timestamp("2026-03-26"), "nav": 1.1548},
        {"date": pd.Timestamp("2026-03-25"), "nav": 1.1180},
    ]
    assert distributions.to_dict(orient="records") == [
        {"date": pd.Timestamp("2026-03-26"), "distribution": pytest.approx(0.0278)}
    ]


def test_parse_lazard_historical_nav_reads_selected_share_class_withdrawal_prices():
    payload = [
        {
            "id": "183",
            "shareClasses": [
                {
                    "id": "251",
                    "data": {
                        "nav": {
                            "historicalNav": [
                                {"navAsOfDate": "2026-04-01", "withdrawalPrice": 1.91},
                            ]
                        }
                    },
                },
                {
                    "id": "254",
                    "data": {
                        "nav": {
                            "historicalNav": [
                                {"navAsOfDate": "2026-04-01", "withdrawalPrice": 1.8133},
                                {"navAsOfDate": "2026-03-31", "withdrawalPrice": 1.7943},
                            ]
                        }
                    },
                },
            ],
        }
    ]

    parsed = _parse_lazard_historical_nav(payload, "254", "withdrawalPrice")

    assert parsed.to_dict(orient="records") == [
        {"date": pd.Timestamp("2026-04-01"), "nav": 1.8133},
        {"date": pd.Timestamp("2026-03-31"), "nav": 1.7943},
    ]


def test_extend_lazard_history_with_performance_anchors_backfills_long_period_targets():
    history = pd.DataFrame(
        {
            "nav": [1.60, 1.65],
            "distribution": [0.0, 0.0],
        },
        index=pd.to_datetime(["2025-04-22", "2026-05-15"]),
    )
    share_class = {
        "data": {
            "performance": {
                "annualized": {
                    "net": {
                        "AUD": [
                            {
                                "threeYears": {"value": 4.0},
                                "fiveYears": {"value": 6.0},
                            }
                        ]
                    }
                }
            }
        }
    }

    extended = _extend_lazard_history_with_performance_anchors(history, share_class, "2026-05-15")

    assert extended.index.strftime("%Y-%m-%d").tolist() == [
        "2021-05-15",
        "2023-05-15",
        "2025-04-22",
        "2026-05-15",
    ]
    assert extended.loc[pd.Timestamp("2021-05-15"), "distribution"] == 0.0
    assert extended.loc[pd.Timestamp("2023-05-15"), "distribution"] == 0.0
    assert extended.loc[pd.Timestamp("2023-05-15"), "nav"] == pytest.approx(
        1.60 * (1.65 / 1.60) / ((1 + 0.04) ** 3)
    )


def test_extend_lazard_history_with_performance_anchors_respects_performance_as_of_date():
    history = pd.DataFrame(
        {
            "nav": [1.60, 1.68, 1.65],
            "distribution": [0.0, 0.0, 0.0],
        },
        index=pd.to_datetime(["2025-04-22", "2026-04-30", "2026-05-15"]),
    )
    share_class = {
        "data": {
            "performance": {
                "annualized": {
                    "asOfDate": "2026-04-30",
                    "net": {"AUD": [{"threeYears": {"value": 4.0}}]},
                }
            }
        }
    }

    extended = _extend_lazard_history_with_performance_anchors(history, share_class, "2026-05-15")

    assert extended.loc[pd.Timestamp("2023-05-15"), "nav"] == pytest.approx(
        1.60 * (1.68 / 1.60) / ((1 + 0.04) ** 3)
    )


def test_parse_lazard_annual_distribution_pdf_text_reads_selected_share_class_block():
    pdf_text = """
    Lazard Select Australian Equity Fund
    Annual Fund Distributions and Fund Payment Information
    for the year ended 30 June 2026
    I Class W Class S Class
    30 Sep 25 31 Dec 25 31 Mar 26 30 Jun 26 30 Sep 25 31 Dec 25 31 Mar 26 30 Jun 26 30 Sep 25 31 Dec 25 31 Mar 26 30 Jun 26
    Cash Distribution 1.8726 1.2124 TBA TBA 1.7730 0.9922 TBA TBA 1.3643 0.8232 TBA TBA
    MIT fund payment amount
    """.strip()

    parsed = _parse_lazard_annual_distribution_pdf_text(pdf_text, "W Class")

    assert parsed.to_dict(orient="records") == [
        {"date": pd.Timestamp("2025-09-30"), "distribution": pytest.approx(0.01773)},
        {"date": pd.Timestamp("2025-12-31"), "distribution": pytest.approx(0.009922)},
    ]


def test_parse_lazard_legacy_distribution_pdf_text_reads_net_cash_distribution_column():
    pdf_text = """
    Lazard Australian Equity Fund
    (I Class)
    (W Class)
    (S Class)
    Net Cash Distribution (cents per unit)
    30-Jun-21 0.04 0.54 0.58 0.02 0.28 0.30 0.06 0.70 0.76
    31-Mar-21 0.03 0.75 0.78 0.02 0.59 0.61 0.04 0.87 0.91
    """.strip()

    parsed = _parse_lazard_legacy_distribution_pdf_text(pdf_text, "W Class")

    assert parsed.to_dict(orient="records") == [
        {"date": pd.Timestamp("2021-06-30"), "distribution": pytest.approx(0.003)},
        {"date": pd.Timestamp("2021-03-31"), "distribution": pytest.approx(0.0061)},
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


def test_find_selector_unit_prices_workbook_url_reads_current_fund_page_link():
    page_html = """
    <a href="https://cdn.prod.website-files.com/current.xlsx">
      Selector High Conviction Equity Fund Unit Prices Spreadsheet
    </a>
    """

    workbook_url = _find_selector_unit_prices_workbook_url(page_html, "https://www.selectorfund.com.au/wholesale-fund")

    assert workbook_url == "https://cdn.prod.website-files.com/current.xlsx"


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


def test_build_allan_gray_fact_sheet_candidates_prefers_fact_sheets_over_reports():
    page_html = """
    <a href="https://www.allangray.com.au/wp-content/uploads/AGA-Documents/Australia-and-New-Zealand/Research-House-Reports/AGA-Equity-Fund-Class-A/Lonsec-Report-2025-Allan-Gray-Australia-Equity-Fund-Oct-2025.pdf">Report</a>
    <a href="https://www.allangray.com.au/wp-content/uploads/AGA-Documents/Australia-and-New-Zealand/Fact-Sheets/AGA-Equity-Fund-Class-A/Allan-Gray-Australia-Equity-Fund-Fact-Sheet-Class-A-March-2026.pdf">Fact Sheet</a>
    """

    candidates = _build_allan_gray_fact_sheet_candidates(page_html, "A")

    assert "Fact-Sheet-Class-A-March-2026.pdf" in candidates[0]


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


def test_parse_allan_gray_fact_sheet_latest_price_converts_nav_to_sell_price():
    pdf_text = """
Allan Gray Australia Equity Fund (Class A)
FUND FACT SHEET 31 MARCH 2026
Price (net asset value) AUD 1.7386
Buy/sell spread +0.2 / -0.2%
""".strip()

    parsed = _parse_allan_gray_fact_sheet_latest_price(pdf_text, "sell")

    assert parsed.to_dict(orient="records") == [
        {"date": pd.Timestamp("2026-03-31"), "nav": pytest.approx(1.7351228)}
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


def test_parse_katana_monthly_prices_preserves_june_pre_and_post_rows():
    html = """
    <div id="monthly-unit-price"></div>
    <div class="col-md-2 col-12">
      <a class="accord-title" href="#">2025</a>
      <div class="accord-body">
        <ul>
          <li>May $1.2590</li>
          <li>Jun Pre $1.2854</li>
          <li>Jun Post $1.1981</li>
          <li>Jul $1.3019</li>
        </ul>
      </div>
    </div>
    <div class="col-md-2 col-12">
      <a class="accord-title" href="#">2026</a>
      <div class="accord-body">
        <ul>
          <li>Jan $1.4445</li>
          <li>Mar $1.3080</li>
        </ul>
      </div>
    </div>
    <div id="annual-distribution"></div>
    """.strip()

    parsed = _parse_katana_monthly_prices(html)

    assert parsed.to_dict(orient="records") == [
        {"date": pd.Timestamp("2025-05-31"), "nav": 1.2590},
        {"date": pd.Timestamp("2025-06-30"), "nav": 1.2854},
        {"date": pd.Timestamp("2025-07-01"), "nav": 1.1981},
        {"date": pd.Timestamp("2025-07-31"), "nav": 1.3019},
        {"date": pd.Timestamp("2026-01-31"), "nav": 1.4445},
        {"date": pd.Timestamp("2026-03-31"), "nav": 1.3080},
    ]


def test_parse_katana_annual_distributions_reads_cpu_rows():
    html = """
    <div>
      <div id="annual-distribution"></div>
      <div class="row">
        <ul>
          <li>June 2025 8.7292 CPU (paid 15/07/2025)</li>
          <li>June 2024 5.9090 CPU (paid 11/07/2024)</li>
        </ul>
      </div>
    </div>
    """.strip()

    parsed = _parse_katana_annual_distributions(html)

    assert parsed.to_dict(orient="records") == [
        {"date": pd.Timestamp("2025-06-30"), "distribution": pytest.approx(0.087292)},
        {"date": pd.Timestamp("2024-06-30"), "distribution": pytest.approx(0.05909)},
    ]


def test_parse_katana_daily_price_reads_latest_posted_price():
    html = "<strong>Daily Price as at 01/04/2026: $1.3512</strong>"

    parsed = _parse_katana_daily_price(html)

    assert parsed.to_dict(orient="records") == [
        {"date": pd.Timestamp("2026-04-01"), "nav": 1.3512}
    ]


def test_parse_dnr_distribution_history_table_reads_multiple_periods_per_year():
    table = pd.DataFrame(
        {
            "Financial year(s)": [
                "Financial Year 2026",
                "APIR code: PIM0028AU",
                "Period end date",
                "Cash distribution amount (CPU)",
                "Financial Year 2025",
                "APIR code: PIM0028AU",
                "Period end date",
                "Cash distribution amount (CPU)",
            ],
            "Unnamed: 1": [
                None,
                None,
                "31/12/2025",
                2.3206,
                None,
                None,
                "31/12/2024",
                2.3480,
            ],
            "Unnamed: 2": [
                None,
                None,
                None,
                None,
                None,
                None,
                "30/06/2025",
                1.4433,
            ],
        }
    )

    parsed = _parse_dnr_distribution_history_table(table)

    assert parsed.to_dict(orient="records") == [
        {"date": pd.Timestamp("2025-12-31"), "distribution": pytest.approx(0.023206)},
        {"date": pd.Timestamp("2024-12-31"), "distribution": pytest.approx(0.02348)},
        {"date": pd.Timestamp("2025-06-30"), "distribution": pytest.approx(0.014433)},
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


def test_build_gsfm_price_and_distribution_frames_uses_ex_date_valuation_price():
    unit_prices = pd.DataFrame(
        {
            "As At Date": ["01-07-2025", "30-06-2025", "27-06-2025"],
            "NAV Price": [1.2255, 1.2854, 1.2774],
            "Exit Price": [1.2224, 1.2822, 1.2742],
        }
    )
    distributions = pd.DataFrame(
        {
            "Period To": ["30-06-2025"],
            "Distribution CPU1": [6.3223],
            "Reinvestment price ($)": [1.2222],
            "Valuation price on ex-date ($)": [1.2191],
        }
    )

    prices, parsed_distributions = _build_gsfm_price_and_distribution_frames(
        unit_prices,
        distributions,
        "NAV Price",
        "Valuation price on ex-date ($)",
    )

    assert prices.to_dict(orient="records") == [
        {"date": pd.Timestamp("2025-07-01"), "nav": 1.2255},
        {"date": pd.Timestamp("2025-06-30"), "nav": 1.2191},
        {"date": pd.Timestamp("2025-06-27"), "nav": 1.2774},
    ]
    assert parsed_distributions.to_dict(orient="records") == [
        {"date": pd.Timestamp("2025-06-30"), "distribution": pytest.approx(0.063223)}
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


def test_parse_vanguard_price_history_reads_nav_price_rows():
    payload = {
        "data": [
            {
                "navPrices": [
                    {"measureTypeCode": "NAV", "asOfDate": "2026-04-02", "price": 2.9477},
                    {"measureTypeCode": "BUY", "asOfDate": "2026-04-02", "price": 2.9500},
                    {"measureTypeCode": "NAV", "asOfDate": "2026-04-01", "price": 2.9808},
                ]
            }
        ]
    }

    parsed = _parse_vanguard_price_history(payload)

    assert parsed.to_dict(orient="records") == [
        {"date": pd.Timestamp("2026-04-02"), "nav": 2.9477},
        {"date": pd.Timestamp("2026-04-01"), "nav": 2.9808},
    ]


def test_parse_vanguard_distribution_history_uses_actual_cash_distribution_only():
    payload = {
        "data": {
            "items": [
                {
                    "exDividendDate": "2026-04-01",
                    "taxDetails": [
                        {
                            "distributionLevelCode": "ACTL",
                            "distributionAmount": 0.00816693,
                            "distributionType": {"distCode": "TCAI"},
                        },
                        {
                            "distributionLevelCode": "ACTL",
                            "distributionAmount": 0.03064767,
                            "distributionType": {"distCode": "GRSS"},
                        },
                        {
                            "distributionLevelCode": "ACTL",
                            "distributionAmount": 0.02248074,
                            "distributionType": {"distCode": "CASH"},
                        },
                        {
                            "distributionLevelCode": "EST",
                            "distributionAmount": 9.99,
                            "distributionType": {"distCode": "CASH"},
                        },
                    ],
                },
                {
                    "recordDate": "2025-12-31",
                    "taxDetails": [
                        {
                            "distributionLevelCode": "ACTL",
                            "distributionAmount": 0.0,
                            "distributionType": {"distCode": "CASH"},
                        },
                    ],
                },
            ]
        }
    }

    parsed = _parse_vanguard_distribution_history(payload)

    assert parsed.to_dict(orient="records") == [
        {"date": pd.Timestamp("2026-04-01"), "distribution": pytest.approx(0.02248074)}
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


def test_build_macquarie_history_url_selects_apir_specific_csv():
    payload = [
        {
            "accountName": "Other Fund",
            "apirCode": "ABC0001AU",
            "historicalPricesFileName": "au_wealth/data/fund/Other.csv",
        },
        {
            "accountName": "Macquarie Australian Shares Fund",
            "apirCode": "MAQ0443AU",
            "historicalPricesFileName": "au_wealth/data/fund/Australian_equities/HCFFND/HCFFND/Macquarie Australian Shares Fund_HN.csv",
        },
    ]

    url = _build_macquarie_history_url(payload, "MAQ0443AU", "https://www.macquarie.com/assets/mam")

    assert url == (
        "https://www.macquarie.com/assets/mam/au_wealth/data/fund/Australian_equities/HCFFND/HCFFND/"
        "Macquarie%20Australian%20Shares%20Fund_HN.csv"
    )


def test_parse_macquarie_historical_price_csv_reconstructs_same_day_ex_prices():
    csv_text = """
Valuation Date,Application price,Redemption price,NAV price,CPU
01 Apr 2026,2.1770,2.1714,2.1742,
31 Mar 2026,2.1385,2.1329,2.1357,0.922306
30 Mar 2026,2.1327,2.1271,2.1299,
31 Dec 2025,2.2989,2.2929,2.2959,1.474021
""".strip()

    parsed = _parse_macquarie_historical_price_csv(csv_text, "Redemption price")

    assert parsed.to_dict(orient="records") == [
        {"date": pd.Timestamp("2026-04-01"), "nav": 2.1714, "distribution": 0.0},
        {"date": pd.Timestamp("2026-03-31"), "nav": pytest.approx(2.12367694), "distribution": pytest.approx(0.00922306)},
        {"date": pd.Timestamp("2026-03-30"), "nav": 2.1271, "distribution": 0.0},
        {"date": pd.Timestamp("2025-12-31"), "nav": pytest.approx(2.27815979), "distribution": pytest.approx(0.01474021)},
    ]


def test_parse_paradice_price_history_csv_prefers_ex_rows_on_distribution_dates():
    csv_text = """
"Unit prices for Paradice Australian Equities Fund",,,,,
"APIR Code - ETL8084AU",,,,,
,,,,,
Date,"App Price ($)","Nav/Mid Price ($)","Red Price ($)",DPU,"Price Type"
01/07/2025,1.2255,1.2224,1.2193,N/A,
30/06/2025,1.4986,1.4956,1.4926,0.09098,EX
30/06/2025,1.5896,1.5866,1.5836,N/A,
27/06/2025,1.4724,1.4694,1.4665,N/A,
""".strip()

    prices, distributions = _parse_paradice_price_history_csv(csv_text, "Red Price ($)")

    assert prices.to_dict(orient="records") == [
        {"date": pd.Timestamp("2025-06-27"), "nav": 1.4665},
        {"date": pd.Timestamp("2025-06-30"), "nav": 1.4926},
        {"date": pd.Timestamp("2025-07-01"), "nav": 1.2193},
    ]
    assert distributions.to_dict(orient="records") == [
        {"date": pd.Timestamp("2025-06-30"), "distribution": pytest.approx(0.09098)}
    ]
