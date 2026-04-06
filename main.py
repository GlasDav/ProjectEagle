from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from cache import load_cached_frame, save_cached_frame
from connectors import CSVConnector, ConnectorValidationError, ScraperConnector, YFinanceConnector
from delivery import load_email_settings, parse_recipients, send_report_email
from output import build_html_report, build_plaintext_report, export_to_excel, export_to_html, render_tables
from performance import PERIODS, calculate_relative_returns, calculate_returns, nearest_on_or_before
from teams_delivery import load_teams_webhook_url, send_teams_message_card
from total_return import build_total_return_index

LOGGER = logging.getLogger(__name__)
DEFAULT_REPORT_LAG_DAYS = 2


@dataclass
class FundResult:
    name: str
    returns: dict[str, float | None]
    style: str = ""
    is_benchmark: bool = False
    error: bool = False
    is_stale: bool = False
    stale_days: int = 0
    latest_date: pd.Timestamp | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fund total-return performance dashboard")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--as-of", dest="as_of", help="Reference date for calculations (YYYY-MM-DD)")
    parser.add_argument("--export", choices=["xlsx", "html", "all"], help="Export the report to Excel, HTML, or both")
    parser.add_argument("--output-dir", default=".", help="Directory for exported report files")
    parser.add_argument("--no-cache", action="store_true", help="Force refresh all data")
    parser.add_argument("--fund", help="Run for a single fund only (case-insensitive substring match)")
    parser.add_argument("--send-email", action="store_true", help="Send the report by email using SMTP environment variables")
    parser.add_argument("--email-to", help="Comma-separated recipient email addresses")
    parser.add_argument("--email-from", help="Override the sender email address")
    parser.add_argument("--email-subject", help="Override the email subject line")
    parser.add_argument("--send-teams", action="store_true", help="Post the report summary to a Teams channel webhook")
    parser.add_argument("--teams-webhook-url", help="Override the Teams webhook URL")
    return parser.parse_args()


def load_config(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    validate_config(config, base_path=Path(path).resolve().parent)
    return config


def validate_config(config: dict[str, Any], base_path: Path) -> None:
    if "benchmark" not in config or "funds" not in config:
        raise ValueError("config.yaml must contain 'benchmark' and 'funds'.")

    all_entries = [config["benchmark"], *config["funds"]]
    for entry in all_entries:
        if entry.get("enabled", True) is False:
            continue
        if "name" not in entry or "source" not in entry or "nav_type" not in entry:
            raise ValueError(f"Entry is missing required fields: {entry}")
        if entry["source"] == "yfinance" and "ticker" not in entry:
            raise ValueError(f"yfinance entry requires ticker: {entry['name']}")
        if entry["source"] == "csv":
            if "file" not in entry:
                raise ValueError(f"csv entry requires file: {entry['name']}")
            file_path = Path(entry["file"])
            if not file_path.is_absolute():
                file_path = base_path / file_path
            if entry["nav_type"] == "ex_distribution" and file_path.exists():
                header = pd.read_csv(file_path, nrows=0)
                if "distribution" not in header.columns:
                    raise ValueError(f"{entry['name']} requires a distribution column in {file_path}")


def get_connector(source: str):
    connectors = {
        "yfinance": YFinanceConnector(),
        "csv": CSVConnector(),
        "scraper": ScraperConnector(),
    }
    if source not in connectors:
        raise ValueError(f"Unsupported source '{source}'.")
    return connectors[source]


def build_identifier(config: dict[str, Any]) -> str:
    return config.get("ticker") or config.get("scraper_id") or config.get("file") or config["name"].replace(" ", "_").lower()


def format_style_label(style: Any) -> str:
    text = str(style or "").strip()
    return text.capitalize() if text else ""


def fetch_data(
    config: dict[str, Any],
    start_date: str,
    end_date: str,
    use_cache: bool,
    cache_date: pd.Timestamp,
) -> pd.DataFrame:
    source = config["source"]
    identifier = build_identifier(config)
    if use_cache:
        cached = load_cached_frame(source, identifier, cache_date=cache_date)
        if cached is not None:
            return cached

    connector = get_connector(source)
    frame = connector.get_fund_data(config, start_date, end_date)
    if use_cache and frame is not None and not frame.empty:
        save_cached_frame(frame, source, identifier, cache_date=cache_date)
    return frame


def default_as_of_date(reference_date: pd.Timestamp | None = None) -> pd.Timestamp:
    anchor = (reference_date or pd.Timestamp.today()).normalize()
    return anchor - pd.Timedelta(days=DEFAULT_REPORT_LAG_DAYS)


def resolve_requested_as_of_date(requested_as_of: str | None) -> pd.Timestamp:
    if requested_as_of:
        return pd.Timestamp(requested_as_of).normalize()
    return default_as_of_date()


def resolve_as_of_date(benchmark_tri: pd.Series, requested_as_of: pd.Timestamp) -> pd.Timestamp:
    if benchmark_tri.empty:
        raise RuntimeError("Benchmark series is empty.")

    resolved = nearest_on_or_before(benchmark_tri, requested_as_of)
    if resolved is None:
        raise RuntimeError("No benchmark data available on or before the requested as-of date.")
    return resolved


def compute_result(
    config: dict[str, Any],
    as_of_date: pd.Timestamp,
    start_date: str,
    use_cache: bool,
    cache_date: pd.Timestamp,
) -> FundResult:
    frame = fetch_data(config, start_date, as_of_date.strftime("%Y-%m-%d"), use_cache=use_cache, cache_date=cache_date)
    if frame is None or frame.empty:
        raise RuntimeError("No data returned.")

    tri = build_total_return_index(frame, config["nav_type"])
    if tri.empty:
        raise RuntimeError("Total return index is empty.")

    returns = calculate_returns(tri, as_of_date)
    latest_date = nearest_on_or_before(tri, as_of_date)
    if latest_date is None:
        raise RuntimeError("No data on or before as-of date.")

    stale_after_days = int(config.get("stale_after_days", 5))
    stale_days = max((as_of_date - latest_date).days, 0)
    is_stale = stale_days > stale_after_days
    if is_stale:
        LOGGER.warning("%s is stale by %s days as of %s", config["name"], stale_days, as_of_date.date())

    return FundResult(
        name=config["name"],
        returns=returns,
        style=format_style_label(config.get("style")),
        is_stale=is_stale,
        stale_days=stale_days,
        latest_date=latest_date,
    )


def to_row(result: FundResult) -> dict[str, Any]:
    row: dict[str, Any] = {
        "Fund": result.name,
        "Style": result.style or "",
        "is_benchmark": result.is_benchmark,
        "is_stale": result.is_stale,
        "error": result.error,
        "stale_days": result.stale_days,
        "latest_date": result.latest_date,
    }
    row.update(result.returns)
    return row


def resolve_export_formats(export: str | None) -> set[str]:
    if export == "all":
        return {"xlsx", "html"}
    if export:
        return {export}
    return set()


def _fund_sort_key(row: dict[str, Any]) -> tuple[int, float, str]:
    mtd = row.get("MTD")
    if row.get("error") or mtd is None:
        return (1, 0.0, str(row["Fund"]))
    return (0, -float(mtd), str(row["Fund"]))


def sort_report_rows(absolute_rows: list[dict[str, Any]], relative_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    benchmark_rows = [row for row in absolute_rows if row.get("is_benchmark")]
    fund_rows = [row for row in absolute_rows if not row.get("is_benchmark")]
    ranked_funds = sorted(fund_rows, key=_fund_sort_key)
    relative_by_fund = {row["Fund"]: row for row in relative_rows}
    ranked_relative = [relative_by_fund[row["Fund"]] for row in ranked_funds if row["Fund"] in relative_by_fund]
    return [*benchmark_rows, *ranked_funds], ranked_relative


def build_average_row(rows: list[dict[str, Any]], label: str = "Average") -> dict[str, Any] | None:
    fund_rows = [
        row
        for row in rows
        if not row.get("is_benchmark") and not row.get("is_average") and not row.get("error")
    ]
    if not fund_rows:
        return None

    average_row: dict[str, Any] = {
        "Fund": label,
        "Style": "",
        "is_benchmark": False,
        "is_average": True,
        "is_stale": False,
        "error": False,
        "stale_days": 0,
        "latest_date": None,
    }
    for period in PERIODS:
        values = [float(row[period]) for row in fund_rows if row.get(period) is not None]
        average_row[period] = sum(values) / len(values) if values else None
    return average_row


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    base_path = config_path.parent

    benchmark_config = config["benchmark"].copy()
    if benchmark_config.get("file"):
        benchmark_config["file"] = str((base_path / benchmark_config["file"]).resolve())

    fund_configs = []
    for fund in config["funds"]:
        if fund.get("enabled", True) is False:
            continue
        candidate = fund.copy()
        if candidate.get("file"):
            candidate["file"] = str((base_path / candidate["file"]).resolve())
        fund_configs.append(candidate)

    if args.fund:
        filter_term = args.fund.casefold()
        fund_configs = [fund for fund in fund_configs if filter_term in fund["name"].casefold()]
        if not fund_configs:
            raise SystemExit(f"No fund names matched '{args.fund}'.")

    requested_as_of = resolve_requested_as_of_date(args.as_of)
    start_date = (requested_as_of - pd.DateOffset(years=5, months=1)).strftime("%Y-%m-%d")

    benchmark_frame = fetch_data(
        benchmark_config,
        start_date,
        requested_as_of.strftime("%Y-%m-%d"),
        use_cache=not args.no_cache,
        cache_date=requested_as_of,
    )
    if benchmark_frame is None or benchmark_frame.empty:
        raise SystemExit("Benchmark fetch failed. Cannot calculate relative performance without benchmark data.")

    benchmark_tri = build_total_return_index(benchmark_frame, benchmark_config["nav_type"])
    as_of_date = resolve_as_of_date(benchmark_tri, requested_as_of)
    benchmark_returns = calculate_returns(benchmark_tri, as_of_date)
    benchmark_result = FundResult(
        name=benchmark_config["name"],
        returns=benchmark_returns,
        style="",
        is_benchmark=True,
        is_stale=max((as_of_date - benchmark_tri.index[-1]).days, 0) > int(benchmark_config.get("stale_after_days", 5)),
        stale_days=max((as_of_date - benchmark_tri.index[-1]).days, 0),
        latest_date=benchmark_tri.index[-1],
    )

    absolute_rows = [to_row(benchmark_result)]
    relative_rows: list[dict[str, Any]] = []

    for fund_config in fund_configs:
        try:
            result = compute_result(
                fund_config,
                as_of_date=as_of_date,
                start_date=start_date,
                use_cache=not args.no_cache,
                cache_date=as_of_date,
            )
            absolute_rows.append(to_row(result))
            relative = calculate_relative_returns(result.returns, benchmark_returns)
            relative_rows.append(
                {
                    "Fund": result.name,
                    "Style": result.style,
                    "is_stale": result.is_stale,
                    "error": False,
                    "stale_days": result.stale_days,
                    "latest_date": result.latest_date,
                    **relative,
                }
            )
        except Exception as exc:
            LOGGER.warning("Failed to process %s: %s", fund_config["name"], exc)
            error_result = FundResult(
                name=fund_config["name"],
                returns={period: None for period in PERIODS},
                style=format_style_label(fund_config.get("style")),
                error=True,
            )
            absolute_rows.append(to_row(error_result))
            relative_rows.append(
                {
                    "Fund": fund_config["name"],
                    "Style": format_style_label(fund_config.get("style")),
                    "is_stale": False,
                    "error": True,
                    "stale_days": 0,
                    "latest_date": None,
                    **{period: None for period in PERIODS},
                }
            )

    absolute_rows, relative_rows = sort_report_rows(absolute_rows, relative_rows)
    absolute_average_row = build_average_row(absolute_rows)
    if absolute_average_row is not None:
        absolute_rows.append(absolute_average_row)
    relative_average_row = build_average_row(relative_rows)
    if relative_average_row is not None:
        relative_rows.append(relative_average_row)
    render_tables(absolute_rows, relative_rows, as_of_date)

    export_formats = resolve_export_formats(args.export)
    output_dir = Path(args.output_dir).resolve()
    exported_paths: dict[str, Path] = {}
    if export_formats:
        output_dir.mkdir(parents=True, exist_ok=True)

    if "xlsx" in export_formats:
        xlsx_path = output_dir / f"fund_performance_{as_of_date:%Y-%m-%d}.xlsx"
        export_to_excel(absolute_rows, relative_rows, as_of_date, xlsx_path)
        exported_paths["xlsx"] = xlsx_path
        LOGGER.info("Wrote Excel export to %s", xlsx_path)

    if "html" in export_formats:
        html_path = output_dir / f"fund_performance_{as_of_date:%Y-%m-%d}.html"
        export_to_html(absolute_rows, relative_rows, as_of_date, html_path)
        exported_paths["html"] = html_path
        LOGGER.info("Wrote HTML export to %s", html_path)

    if args.send_email:
        recipients = parse_recipients(args.email_to or os.getenv("PERFSRAPER_EMAIL_TO"))
        if not recipients:
            raise ValueError("Email delivery requires --email-to or PERFSRAPER_EMAIL_TO.")

        subject = args.email_subject or f"Australian Equity Fund Scorecard | {as_of_date:%Y-%m-%d}"
        settings = load_email_settings(sender=args.email_from)
        attachments = [path for key, path in exported_paths.items() if key != "html"]
        send_report_email(
            settings=settings,
            recipients=recipients,
            subject=subject,
            text_body=build_plaintext_report(absolute_rows, relative_rows, as_of_date),
            html_body=build_html_report(absolute_rows, relative_rows, as_of_date),
            attachments=attachments,
        )
        LOGGER.info("Sent report email to %s", ", ".join(recipients))

    if args.send_teams:
        webhook_url = load_teams_webhook_url(args.teams_webhook_url)
        send_teams_message_card(
            webhook_url=webhook_url,
            absolute_rows=absolute_rows,
            relative_rows=relative_rows,
            as_of_date=as_of_date,
        )
        LOGGER.info("Posted report summary to Teams.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
