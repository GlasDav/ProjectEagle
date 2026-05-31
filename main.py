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
from teams_delivery import load_teams_webhook_url, send_teams_message_card, teams_webhook_payload_mode
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


@dataclass
class CompetitorSetResult:
    id: str
    title: str
    rows: list[dict[str, Any]]


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

    validate_competitor_sets(config)


def _fund_lookup(funds: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for fund in funds:
        names = [fund.get("name"), *fund.get("aliases", [])]
        for name in names:
            text = str(name or "").strip()
            if text:
                lookup[text.casefold()] = fund
    return lookup


def validate_competitor_sets(config: dict[str, Any]) -> None:
    competitor_sets = config.get("competitor_sets") or []
    if not isinstance(competitor_sets, list):
        raise ValueError("competitor_sets must be a list when provided.")

    funds_by_name = _fund_lookup(config.get("funds") or [])
    seen_ids: set[str] = set()
    for competitor_set in competitor_sets:
        if not isinstance(competitor_set, dict):
            raise ValueError("Each competitor set must be a mapping.")
        set_id = str(competitor_set.get("id") or "").strip()
        title = str(competitor_set.get("title") or "").strip()
        fund_names = competitor_set.get("funds")
        if not set_id or not title or not isinstance(fund_names, list) or not fund_names:
            raise ValueError("Each competitor set requires id, title, and a non-empty funds list.")
        if set_id in seen_ids:
            raise ValueError(f"Duplicate competitor set id: {set_id}")
        seen_ids.add(set_id)

        missing = [str(name) for name in fund_names if str(name).strip().casefold() not in funds_by_name]
        if missing:
            raise ValueError(f"Competitor set '{set_id}' references unknown funds: {', '.join(missing)}")


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
    if config.get("source") == "scraper":
        scraper_id = str(config.get("scraper_id") or "scraper").strip()
        fund_name = str(config["name"]).strip().replace(" ", "_").lower()
        return f"{scraper_id}_{fund_name}"
    return config.get("ticker") or config.get("file") or config["name"].replace(" ", "_").lower()


def format_style_label(style: Any) -> str:
    text = str(style or "").strip()
    return text.capitalize() if text else ""


def is_enabled(config: dict[str, Any]) -> bool:
    return config.get("enabled", True) is not False


def is_default_report_fund(config: dict[str, Any]) -> bool:
    return is_enabled(config) and config.get("default_report", True) is not False


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


def compute_result_from_frame(config: dict[str, Any], frame: pd.DataFrame, as_of_date: pd.Timestamp) -> FundResult:
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


def compute_result(
    config: dict[str, Any],
    as_of_date: pd.Timestamp,
    start_date: str,
    use_cache: bool,
    cache_date: pd.Timestamp,
) -> FundResult:
    frame = fetch_data(config, start_date, as_of_date.strftime("%Y-%m-%d"), use_cache=use_cache, cache_date=cache_date)
    return compute_result_from_frame(config, frame, as_of_date)


def latest_available_date(config: dict[str, Any], frame: pd.DataFrame | None, requested_as_of: pd.Timestamp) -> pd.Timestamp | None:
    if frame is None or frame.empty:
        return None
    tri = build_total_return_index(frame, config["nav_type"])
    if tri.empty:
        return None
    return nearest_on_or_before(tri, requested_as_of)


def select_report_as_of_date(
    fund_configs: list[dict[str, Any]],
    fund_frames: dict[str, pd.DataFrame],
    fallback_as_of: pd.Timestamp,
) -> pd.Timestamp:
    dates: list[pd.Timestamp] = []
    for fund_config in fund_configs:
        if not is_enabled(fund_config):
            continue
        frame = fund_frames.get(str(fund_config["name"]))
        try:
            latest_date = latest_available_date(fund_config, frame, fallback_as_of)
        except Exception as exc:
            LOGGER.warning("Failed to inspect latest date for %s: %s", fund_config["name"], exc)
            continue
        if latest_date is not None:
            dates.append(pd.Timestamp(latest_date).normalize())

    if not dates:
        return fallback_as_of

    counts = pd.Series(dates).value_counts()
    highest_count = counts.max()
    return pd.Timestamp(max(counts[counts == highest_count].index)).normalize()


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


def unavailable_absolute_row(fund_config: dict[str, Any]) -> dict[str, Any]:
    reason = str(fund_config.get("disabled_reason") or "No durable public performance source has been configured.")
    return {
        "Fund": fund_config["name"],
        "Style": format_style_label(fund_config.get("style")),
        "is_benchmark": False,
        "is_disabled": True,
        "disabled_reason": reason,
        "is_stale": False,
        "error": False,
        "stale_days": 0,
        "latest_date": None,
        **{period: None for period in PERIODS},
    }


def unavailable_relative_row(fund_config: dict[str, Any]) -> dict[str, Any]:
    row = unavailable_absolute_row(fund_config)
    row.pop("is_benchmark", None)
    return row


def build_fund_report_rows(
    fund_config: dict[str, Any],
    *,
    benchmark_returns: dict[str, float | None],
    as_of_date: pd.Timestamp,
    start_date: str,
    use_cache: bool,
    cache_date: pd.Timestamp,
    benchmark_tri: pd.Series | None = None,
    fund_frame: pd.DataFrame | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not is_enabled(fund_config):
        return unavailable_absolute_row(fund_config), unavailable_relative_row(fund_config)

    try:
        result = (
            compute_result_from_frame(fund_config, fund_frame, as_of_date)
            if fund_frame is not None
            else compute_result(
                fund_config,
                as_of_date=as_of_date,
                start_date=start_date,
                use_cache=use_cache,
                cache_date=cache_date,
            )
        )
        absolute_row = to_row(result)
        aligned_benchmark_returns = (
            calculate_returns(benchmark_tri, result.latest_date)
            if benchmark_tri is not None and result.latest_date is not None
            else benchmark_returns
        )
        relative = calculate_relative_returns(result.returns, aligned_benchmark_returns)
        relative_row = {
            "Fund": result.name,
            "Style": result.style,
            "is_stale": result.is_stale,
            "error": False,
            "stale_days": result.stale_days,
            "latest_date": result.latest_date,
            **relative,
        }
        return absolute_row, relative_row
    except Exception as exc:
        LOGGER.warning("Failed to process %s: %s", fund_config["name"], exc)
        error_result = FundResult(
            name=fund_config["name"],
            returns={period: None for period in PERIODS},
            style=format_style_label(fund_config.get("style")),
            error=True,
        )
        return to_row(error_result), {
            "Fund": fund_config["name"],
            "Style": format_style_label(fund_config.get("style")),
            "is_stale": False,
            "error": True,
            "stale_days": 0,
            "latest_date": None,
            **{period: None for period in PERIODS},
        }


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


def build_competitor_set_results(
    config: dict[str, Any],
    *,
    benchmark_row: dict[str, Any],
    benchmark_returns: dict[str, float | None],
    as_of_date: pd.Timestamp,
    start_date: str,
    use_cache: bool,
    cache_date: pd.Timestamp,
    benchmark_tri: pd.Series | None = None,
    row_cache: dict[str, tuple[dict[str, Any], dict[str, Any]]] | None = None,
) -> list[CompetitorSetResult]:
    funds_by_name = _fund_lookup(config.get("funds") or [])
    cached_rows = row_cache if row_cache is not None else {}
    results: list[CompetitorSetResult] = []

    for competitor_set in config.get("competitor_sets") or []:
        absolute_rows = [benchmark_row]
        relative_rows: list[dict[str, Any]] = []
        for configured_name in competitor_set["funds"]:
            fund_config = funds_by_name[str(configured_name).strip().casefold()]
            cache_key = str(fund_config["name"])
            if cache_key not in cached_rows:
                cached_rows[cache_key] = build_fund_report_rows(
                    fund_config,
                    benchmark_returns=benchmark_returns,
                    as_of_date=as_of_date,
                    start_date=start_date,
                    benchmark_tri=benchmark_tri,
                    use_cache=use_cache,
                    cache_date=cache_date,
                )
            absolute_row, relative_row = cached_rows[cache_key]
            absolute_rows.append(absolute_row)
            relative_rows.append(relative_row)

        sorted_absolute, sorted_relative = sort_report_rows(absolute_rows, relative_rows)
        table_rows = [sorted_absolute[0], *sorted_relative]
        results.append(
            CompetitorSetResult(
                id=str(competitor_set["id"]),
                title=str(competitor_set["title"]),
                rows=table_rows,
            )
        )
    return results


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
        if not is_default_report_fund(fund):
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
    benchmark_as_of = resolve_as_of_date(benchmark_tri, requested_as_of)

    fund_frames: dict[str, pd.DataFrame] = {}
    for fund_config in fund_configs:
        try:
            fund_frames[str(fund_config["name"])] = fetch_data(
                fund_config,
                start_date,
                benchmark_as_of.strftime("%Y-%m-%d"),
                use_cache=not args.no_cache,
                cache_date=benchmark_as_of,
            )
        except Exception as exc:
            LOGGER.warning("Failed to fetch %s while selecting report date: %s", fund_config["name"], exc)
            fund_frames[str(fund_config["name"])] = pd.DataFrame(columns=["nav", "distribution"])

    as_of_date = select_report_as_of_date(fund_configs, fund_frames, benchmark_as_of)
    if as_of_date != benchmark_as_of:
        LOGGER.info("Using %s as report date because it is the latest date available for the most funds.", as_of_date.date())

    benchmark_returns = calculate_returns(benchmark_tri, as_of_date)
    benchmark_latest_date = nearest_on_or_before(benchmark_tri, as_of_date)
    if benchmark_latest_date is None:
        raise SystemExit("Benchmark fetch failed. Cannot calculate performance for the selected report date.")
    benchmark_stale_days = max((as_of_date - benchmark_latest_date).days, 0)
    benchmark_result = FundResult(
        name=benchmark_config["name"],
        returns=benchmark_returns,
        style="",
        is_benchmark=True,
        is_stale=benchmark_stale_days > int(benchmark_config.get("stale_after_days", 5)),
        stale_days=benchmark_stale_days,
        latest_date=benchmark_latest_date,
    )

    absolute_rows = [to_row(benchmark_result)]
    relative_rows: list[dict[str, Any]] = []
    row_cache: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}

    for fund_config in fund_configs:
        absolute_row, relative_row = build_fund_report_rows(
            fund_config,
            benchmark_returns=benchmark_returns,
            benchmark_tri=benchmark_tri,
            as_of_date=as_of_date,
            start_date=start_date,
            use_cache=not args.no_cache,
            cache_date=benchmark_as_of,
            fund_frame=fund_frames.get(str(fund_config["name"])),
        )
        row_cache[str(fund_config["name"])] = (absolute_row, relative_row)
        absolute_rows.append(absolute_row)
        relative_rows.append(relative_row)

    absolute_rows, relative_rows = sort_report_rows(absolute_rows, relative_rows)
    absolute_average_row = build_average_row(absolute_rows)
    if absolute_average_row is not None:
        absolute_rows.append(absolute_average_row)
    relative_average_row = build_average_row(relative_rows)
    if relative_average_row is not None:
        relative_rows.append(relative_average_row)
    competitor_sets = [] if args.fund else build_competitor_set_results(
        config,
        benchmark_row=to_row(benchmark_result),
        benchmark_returns=benchmark_returns,
        as_of_date=as_of_date,
        start_date=start_date,
        benchmark_tri=benchmark_tri,
        use_cache=not args.no_cache,
        cache_date=benchmark_as_of,
        row_cache=row_cache,
    )
    if competitor_sets:
        render_tables(absolute_rows, relative_rows, as_of_date, competitor_sets=competitor_sets)
    else:
        render_tables(absolute_rows, relative_rows, as_of_date)

    export_formats = resolve_export_formats(args.export)
    output_dir = Path(args.output_dir).resolve()
    exported_paths: dict[str, Path] = {}
    if export_formats:
        output_dir.mkdir(parents=True, exist_ok=True)

    if "xlsx" in export_formats:
        xlsx_path = output_dir / f"fund_performance_{as_of_date:%Y-%m-%d}.xlsx"
        export_to_excel(absolute_rows, relative_rows, as_of_date, xlsx_path, competitor_sets=competitor_sets)
        exported_paths["xlsx"] = xlsx_path
        LOGGER.info("Wrote Excel export to %s", xlsx_path)

    if "html" in export_formats:
        html_path = output_dir / f"fund_performance_{as_of_date:%Y-%m-%d}.html"
        export_to_html(absolute_rows, relative_rows, as_of_date, html_path, competitor_sets=competitor_sets)
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
            text_body=build_plaintext_report(absolute_rows, relative_rows, as_of_date, competitor_sets=competitor_sets),
            html_body=build_html_report(absolute_rows, relative_rows, as_of_date, competitor_sets=competitor_sets),
            attachments=attachments,
        )
        LOGGER.info("Sent report email to %s", ", ".join(recipients))

    if args.send_teams:
        webhook_url = load_teams_webhook_url(args.teams_webhook_url)
        LOGGER.info("Posting Teams report using %s payload mode.", teams_webhook_payload_mode(webhook_url))
        send_teams_message_card(
            webhook_url=webhook_url,
            absolute_rows=absolute_rows,
            relative_rows=relative_rows,
            as_of_date=as_of_date,
            competitor_sets=competitor_sets,
        )
        LOGGER.info("Posted report summary to Teams.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
