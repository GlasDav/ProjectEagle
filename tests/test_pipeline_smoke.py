from __future__ import annotations

import pytest
import yaml

import main


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


def test_relative_performance_matches_displayed_benchmark_returns(tmp_path, monkeypatch):
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

    monkeypatch.setattr(main, "render_tables", capture_render_tables)
    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--config", str(config_path), "--as-of", "2024-04-03", "--no-cache"],
    )

    assert main.main() == 0
    assert captured["absolute_rows"][0]["3M"] == pytest.approx(-0.20)
    assert captured["absolute_rows"][1]["3M"] == pytest.approx(0.0)
    assert captured["relative_rows"][0]["3M"] == pytest.approx(0.20)
