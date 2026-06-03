from __future__ import annotations

import pandas as pd
import pytest
import yaml

import main


def test_default_as_of_date_uses_t_minus_2():
    assert main.default_as_of_date(pd.Timestamp("2026-03-26")) == pd.Timestamp("2026-03-24")


def test_pipeline_smoke(tmp_path, monkeypatch):
    benchmark_csv = tmp_path / "benchmark.csv"
    benchmark_csv.write_text("date,nav\n2024-01-01,100\n2024-02-01,101\n2024-03-01,102\n2024-04-01,103\n", encoding="utf-8")

    fund_csv = tmp_path / "fund.csv"
    fund_csv.write_text(
        "date,nav,distribution\n2024-01-01,10,0\n2024-02-01,10.1,0\n2024-03-01,9.8,0.4\n2024-04-01,10.0,0\n",
        encoding="utf-8",
    )

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "benchmark": {
                    "name": "Benchmark",
                    "source": "csv",
                    "file": str(benchmark_csv),
                    "nav_type": "total_return",
                },
                "funds": [
                    {
                        "name": "Fund A",
                        "source": "csv",
                        "file": str(fund_csv),
                        "nav_type": "ex_distribution",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--config", str(config_path), "--as-of", "2024-04-01", "--no-cache"],
    )

    assert main.main() == 0


def test_relative_performance_uses_benchmark_returns_aligned_to_fund_latest_date(tmp_path, monkeypatch):
    benchmark_csv = tmp_path / "benchmark.csv"
    benchmark_csv.write_text(
        "date,nav\n2024-01-01,100\n2024-02-01,100\n2024-03-01,100\n2024-04-01,90\n2024-04-03,80\n",
        encoding="utf-8",
    )

    fund_csv = tmp_path / "fund.csv"
    fund_csv.write_text("date,nav\n2024-01-01,100\n2024-02-01,100\n2024-03-01,100\n2024-04-01,100\n", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "benchmark": {
                    "name": "Benchmark",
                    "source": "csv",
                    "file": str(benchmark_csv),
                    "nav_type": "total_return",
                },
                "funds": [
                    {
                        "name": "Fund A",
                        "source": "csv",
                        "file": str(fund_csv),
                        "nav_type": "total_return",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, list[dict]] = {}

    def capture_render_tables(absolute_rows, relative_rows, as_of_date):
        captured["absolute_rows"] = absolute_rows
        captured["relative_rows"] = relative_rows
        captured["as_of_date"] = as_of_date

    monkeypatch.setattr(main, "render_tables", capture_render_tables)
    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--config", str(config_path), "--as-of", "2024-04-03", "--no-cache"],
    )

    assert main.main() == 0
    assert captured["as_of_date"] == pd.Timestamp("2024-04-01")
    assert captured["absolute_rows"][0]["3M"] == pytest.approx(-0.10)
    assert captured["absolute_rows"][1]["3M"] == pytest.approx(0.0)
    assert captured["relative_rows"][0]["latest_date"] == pd.Timestamp("2024-04-01")
    assert captured["relative_rows"][0]["3M"] == pytest.approx(0.10)


def test_build_fund_report_rows_accepts_prefetched_fund_frame():
    fund_config = {"name": "Fund A", "source": "csv", "nav_type": "total_return"}
    frame = pd.DataFrame({"nav": [100.0, 102.0]}, index=pd.to_datetime(["2024-04-01", "2024-04-03"]))

    absolute_row, relative_row = main.build_fund_report_rows(
        fund_config,
        benchmark_returns={period: 0.0 for period in main.PERIODS},
        as_of_date=pd.Timestamp("2024-04-03"),
        start_date="2024-04-01",
        use_cache=False,
        cache_date=pd.Timestamp("2024-04-03"),
        fund_frame=frame,
    )

    assert absolute_row["Fund"] == "Fund A"
    assert absolute_row["latest_date"] == pd.Timestamp("2024-04-03")
    assert relative_row["MTD"] == absolute_row["MTD"]


def test_report_date_uses_date_available_for_most_funds(tmp_path, monkeypatch):
    benchmark_csv = tmp_path / "benchmark.csv"
    benchmark_csv.write_text("date,nav\n2024-04-01,100\n2024-04-02,101\n2024-04-03,102\n", encoding="utf-8")

    fund_a_csv = tmp_path / "fund_a.csv"
    fund_a_csv.write_text("date,nav\n2024-04-01,100\n2024-04-02,101\n", encoding="utf-8")
    fund_b_csv = tmp_path / "fund_b.csv"
    fund_b_csv.write_text("date,nav\n2024-04-01,100\n2024-04-02,102\n", encoding="utf-8")
    fund_c_csv = tmp_path / "fund_c.csv"
    fund_c_csv.write_text("date,nav\n2024-04-01,100\n2024-04-03,103\n", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "benchmark": {
                    "name": "Benchmark",
                    "source": "csv",
                    "file": str(benchmark_csv),
                    "nav_type": "total_return",
                },
                "funds": [
                    {"name": "Fund A", "source": "csv", "file": str(fund_a_csv), "nav_type": "total_return"},
                    {"name": "Fund B", "source": "csv", "file": str(fund_b_csv), "nav_type": "total_return"},
                    {"name": "Fund C", "source": "csv", "file": str(fund_c_csv), "nav_type": "total_return"},
                ],
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def capture_render_tables(absolute_rows, relative_rows, as_of_date):
        captured["absolute_rows"] = absolute_rows
        captured["as_of_date"] = as_of_date

    monkeypatch.setattr(main, "render_tables", capture_render_tables)
    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--config", str(config_path), "--as-of", "2024-04-03", "--no-cache"],
    )

    assert main.main() == 0
    assert captured["as_of_date"] == pd.Timestamp("2024-04-02")
    assert next(row for row in captured["absolute_rows"] if row["Fund"] == "Fund C")["latest_date"] == pd.Timestamp("2024-04-01")


def test_report_date_option_skips_best_coverage_date_selection(tmp_path, monkeypatch):
    benchmark_csv = tmp_path / "benchmark.csv"
    benchmark_csv.write_text("date,nav\n2024-04-01,100\n2024-04-02,101\n2024-04-03,102\n", encoding="utf-8")

    fund_a_csv = tmp_path / "fund_a.csv"
    fund_a_csv.write_text("date,nav\n2024-04-01,100\n2024-04-02,101\n", encoding="utf-8")
    fund_b_csv = tmp_path / "fund_b.csv"
    fund_b_csv.write_text("date,nav\n2024-04-01,100\n2024-04-02,102\n", encoding="utf-8")
    fund_c_csv = tmp_path / "fund_c.csv"
    fund_c_csv.write_text("date,nav\n2024-04-01,100\n2024-04-03,103\n", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "benchmark": {
                    "name": "Benchmark",
                    "source": "csv",
                    "file": str(benchmark_csv),
                    "nav_type": "total_return",
                },
                "funds": [
                    {"name": "Fund A", "source": "csv", "file": str(fund_a_csv), "nav_type": "total_return"},
                    {"name": "Fund B", "source": "csv", "file": str(fund_b_csv), "nav_type": "total_return"},
                    {"name": "Fund C", "source": "csv", "file": str(fund_c_csv), "nav_type": "total_return"},
                ],
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def capture_render_tables(absolute_rows, relative_rows, as_of_date):
        captured["absolute_rows"] = absolute_rows
        captured["as_of_date"] = as_of_date

    monkeypatch.setattr(main, "render_tables", capture_render_tables)
    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--config", str(config_path), "--report-date", "2024-04-03", "--no-cache"],
    )

    assert main.main() == 0
    assert captured["as_of_date"] == pd.Timestamp("2024-04-03")
    fund_a = next(row for row in captured["absolute_rows"] if row["Fund"] == "Fund A")
    assert fund_a["latest_date"] == pd.Timestamp("2024-04-02")
    assert fund_a["stale_days"] == 1


def test_as_of_and_report_date_are_mutually_exclusive(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--as-of", "2024-04-03", "--report-date", "2024-04-03"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main.main()

    assert "Use either --as-of or --report-date" in str(exc_info.value)


def test_report_rows_ranked_by_mtd_descending(tmp_path, monkeypatch):
    benchmark_csv = tmp_path / "benchmark.csv"
    benchmark_csv.write_text("date,nav\n2024-04-01,100\n2024-04-03,100\n", encoding="utf-8")

    fund_a_csv = tmp_path / "fund_a.csv"
    fund_a_csv.write_text("date,nav\n2024-04-01,100\n2024-04-03,101\n", encoding="utf-8")

    fund_b_csv = tmp_path / "fund_b.csv"
    fund_b_csv.write_text("date,nav\n2024-04-01,100\n2024-04-03,105\n", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "benchmark": {
                    "name": "Benchmark",
                    "source": "csv",
                    "file": str(benchmark_csv),
                    "nav_type": "total_return",
                },
                "funds": [
                    {
                        "name": "Fund A",
                        "source": "csv",
                        "file": str(fund_a_csv),
                        "nav_type": "total_return",
                    },
                    {
                        "name": "Fund B",
                        "source": "csv",
                        "file": str(fund_b_csv),
                        "nav_type": "total_return",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, list[dict]] = {}

    def capture_render_tables(absolute_rows, relative_rows, as_of_date):
        captured["absolute_rows"] = absolute_rows
        captured["relative_rows"] = relative_rows

    monkeypatch.setattr(main, "render_tables", capture_render_tables)
    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--config", str(config_path), "--as-of", "2024-04-03", "--no-cache"],
    )

    assert main.main() == 0
    assert [row["Fund"] for row in captured["absolute_rows"]] == ["Benchmark", "Fund B", "Fund A", "Average"]
    assert [row["Fund"] for row in captured["relative_rows"]] == ["Fund B", "Fund A", "Average"]


def test_average_rows_are_appended_to_both_tables(tmp_path, monkeypatch):
    benchmark_csv = tmp_path / "benchmark.csv"
    benchmark_csv.write_text("date,nav\n2024-04-01,100\n2024-04-03,100\n", encoding="utf-8")

    fund_a_csv = tmp_path / "fund_a.csv"
    fund_a_csv.write_text("date,nav\n2024-04-01,100\n2024-04-03,101\n", encoding="utf-8")

    fund_b_csv = tmp_path / "fund_b.csv"
    fund_b_csv.write_text("date,nav\n2024-04-01,100\n2024-04-03,103\n", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "benchmark": {
                    "name": "Benchmark",
                    "source": "csv",
                    "file": str(benchmark_csv),
                    "nav_type": "total_return",
                },
                "funds": [
                    {
                        "name": "Fund A",
                        "source": "csv",
                        "file": str(fund_a_csv),
                        "nav_type": "total_return",
                    },
                    {
                        "name": "Fund B",
                        "source": "csv",
                        "file": str(fund_b_csv),
                        "nav_type": "total_return",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, list[dict]] = {}

    def capture_render_tables(absolute_rows, relative_rows, as_of_date):
        captured["absolute_rows"] = absolute_rows
        captured["relative_rows"] = relative_rows

    monkeypatch.setattr(main, "render_tables", capture_render_tables)
    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--config", str(config_path), "--as-of", "2024-04-03", "--no-cache"],
    )

    assert main.main() == 0
    assert captured["absolute_rows"][-1]["Fund"] == "Average"
    assert captured["absolute_rows"][-1]["MTD"] == pytest.approx(0.02)
    assert captured["relative_rows"][-1]["Fund"] == "Average"
    assert captured["relative_rows"][-1]["MTD"] == pytest.approx(0.02)


def test_competitor_sets_can_mix_relative_and_absolute_performance_modes():
    benchmark_row = {
        "Fund": "Benchmark",
        "Style": "",
        "is_benchmark": True,
        "is_stale": False,
        "error": False,
        "stale_days": 0,
        "latest_date": pd.Timestamp("2024-04-03"),
        **{period: 0.10 for period in main.PERIODS},
    }
    long_absolute = {
        "Fund": "Long Fund",
        "Style": "Agnostic",
        "is_benchmark": False,
        "is_stale": False,
        "error": False,
        "stale_days": 0,
        "latest_date": pd.Timestamp("2024-04-03"),
        **{period: 0.30 for period in main.PERIODS},
    }
    long_relative = {
        "Fund": "Long Fund",
        "Style": "Agnostic",
        "is_stale": False,
        "error": False,
        "stale_days": 0,
        "latest_date": pd.Timestamp("2024-04-03"),
        **{period: 0.20 for period in main.PERIODS},
    }
    absolute_absolute = {
        "Fund": "Absolute Fund",
        "Style": "Agnostic",
        "is_benchmark": False,
        "is_stale": False,
        "error": False,
        "stale_days": 0,
        "latest_date": pd.Timestamp("2024-04-03"),
        **{period: 0.40 for period in main.PERIODS},
    }
    absolute_relative = {
        "Fund": "Absolute Fund",
        "Style": "Agnostic",
        "is_stale": False,
        "error": False,
        "stale_days": 0,
        "latest_date": pd.Timestamp("2024-04-03"),
        **{period: 0.30 for period in main.PERIODS},
    }
    config = {
        "funds": [
            {"name": "Long Fund"},
            {"name": "Absolute Fund"},
        ],
        "competitor_sets": [
            {
                "id": "long_short_funds",
                "title": "Long-short funds",
                "performance_mode": "relative",
                "funds": ["Long Fund"],
            },
            {
                "id": "market_neutral_funds",
                "title": "Absolute return funds",
                "performance_mode": "absolute",
                "funds": ["Absolute Fund"],
            },
        ],
    }

    results = main.build_competitor_set_results(
        config,
        benchmark_row=benchmark_row,
        benchmark_returns={period: 0.10 for period in main.PERIODS},
        as_of_date=pd.Timestamp("2024-04-03"),
        start_date="2024-04-01",
        use_cache=False,
        cache_date=pd.Timestamp("2024-04-03"),
        row_cache={
            "Long Fund": (long_absolute, long_relative),
            "Absolute Fund": (absolute_absolute, absolute_relative),
        },
    )

    long_short, absolute_return = results
    assert long_short.performance_mode == "relative"
    assert long_short.rows[0]["is_benchmark"] is True
    assert long_short.rows[1]["Fund"] == "Long Fund"
    assert long_short.rows[1]["MTD"] == pytest.approx(0.20)
    assert absolute_return.performance_mode == "absolute"
    assert absolute_return.rows[0]["is_benchmark"] is True
    assert absolute_return.rows[1]["Fund"] == "Absolute Fund"
    assert absolute_return.rows[1]["MTD"] == pytest.approx(0.40)


def test_staleness_respects_configured_threshold(tmp_path, monkeypatch):
    benchmark_csv = tmp_path / "benchmark.csv"
    benchmark_csv.write_text("date,nav\n2024-04-01,100\n2024-04-10,101\n", encoding="utf-8")

    fund_csv = tmp_path / "fund.csv"
    fund_csv.write_text("date,nav\n2024-04-01,100\n", encoding="utf-8")
    current_fund_csv = tmp_path / "current_fund.csv"
    current_fund_csv.write_text("date,nav\n2024-04-01,100\n2024-04-10,101\n", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "benchmark": {
                    "name": "Benchmark",
                    "source": "csv",
                    "file": str(benchmark_csv),
                    "nav_type": "total_return",
                },
                "funds": [
                    {
                        "name": "Fund A",
                        "source": "csv",
                        "file": str(fund_csv),
                        "nav_type": "total_return",
                        "stale_after_days": 15,
                    },
                    {
                        "name": "Fund B",
                        "source": "csv",
                        "file": str(current_fund_csv),
                        "nav_type": "total_return",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, list[dict]] = {}

    def capture_render_tables(absolute_rows, relative_rows, as_of_date):
        captured["absolute_rows"] = absolute_rows

    monkeypatch.setattr(main, "render_tables", capture_render_tables)
    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--config", str(config_path), "--as-of", "2024-04-10", "--no-cache"],
    )

    assert main.main() == 0
    fund_row = next(row for row in captured["absolute_rows"] if row["Fund"] == "Fund A")
    assert fund_row["stale_days"] == 9
    assert fund_row["is_stale"] is False


def test_style_propagates_to_absolute_and_relative_rows(tmp_path, monkeypatch):
    benchmark_csv = tmp_path / "benchmark.csv"
    benchmark_csv.write_text("date,nav\n2024-04-01,100\n2024-04-03,100\n", encoding="utf-8")

    fund_csv = tmp_path / "fund.csv"
    fund_csv.write_text("date,nav\n2024-04-01,100\n2024-04-03,101\n", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "benchmark": {
                    "name": "Benchmark",
                    "source": "csv",
                    "file": str(benchmark_csv),
                    "nav_type": "total_return",
                },
                "funds": [
                    {
                        "name": "Fund A",
                        "source": "csv",
                        "file": str(fund_csv),
                        "nav_type": "total_return",
                        "style": "growth",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, list[dict]] = {}

    def capture_render_tables(absolute_rows, relative_rows, as_of_date):
        captured["absolute_rows"] = absolute_rows
        captured["relative_rows"] = relative_rows

    monkeypatch.setattr(main, "render_tables", capture_render_tables)
    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--config", str(config_path), "--as-of", "2024-04-03", "--no-cache"],
    )

    assert main.main() == 0
    assert captured["absolute_rows"][0]["Style"] == ""
    assert captured["absolute_rows"][1]["Style"] == "Growth"
    assert captured["relative_rows"][0]["Style"] == "Growth"
