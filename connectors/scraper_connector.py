from __future__ import annotations

import io
import json
import logging
import re
import time
import warnings
from io import StringIO
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

from .base import BaseConnector, ConnectorValidationError

LOGGER = logging.getLogger(__name__)
SCRAPER_REGISTRY: dict[str, Callable[..., pd.DataFrame]] = {}
_ALLAN_GRAY_FACT_SHEET_INDEX_CACHE: dict[str, str] = {}


def register_scraper(manager_id: str) -> Callable[[Callable[..., pd.DataFrame]], Callable[..., pd.DataFrame]]:
    def decorator(func: Callable[..., pd.DataFrame]) -> Callable[..., pd.DataFrame]:
        SCRAPER_REGISTRY[manager_id] = func
        return func

    return decorator


class ScraperConnector(BaseConnector):
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123 Safari/537.36"
        )

    def get_fund_data(self, fund_config: dict, start_date: str, end_date: str) -> pd.DataFrame:
        scraper_id = fund_config.get("scraper_id")
        if not scraper_id:
            raise ConnectorValidationError("Scraper funds must define 'scraper_id'.")

        scraper = SCRAPER_REGISTRY.get(scraper_id)
        if scraper is None:
            raise ConnectorValidationError(f"No scraper registered for '{scraper_id}'.")

        try:
            frame = scraper(
                url=fund_config.get("url", ""),
                start_date=start_date,
                end_date=end_date,
                fund_config=fund_config,
                session=self.session,
            )
        except ConnectorValidationError:
            raise
        except Exception as exc:
            LOGGER.warning("Scraper '%s' failed for %s: %s", scraper_id, fund_config.get("name"), exc)
            return pd.DataFrame(columns=["nav", "distribution"])

        normalized = self.normalize_frame(frame)
        if fund_config.get("nav_type") != "ex_distribution" and "distribution" not in normalized.columns:
            normalized["distribution"] = 0.0
        return normalized


def fetch_tabular_url(url: str, session: requests.Session, timeout: int = 10) -> pd.DataFrame:
    response = _get_with_retry(session, url, timeout=timeout)
    response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()
    lower_url = url.lower()
    payload = io.BytesIO(response.content)

    if lower_url.endswith(".csv") or "text/csv" in content_type:
        return pd.read_csv(payload)

    if lower_url.endswith((".xlsx", ".xls")) or "spreadsheet" in content_type or "excel" in content_type:
        return pd.read_excel(payload)

    soup = BeautifulSoup(response.text, "html.parser")
    tables = pd.read_html(StringIO(str(soup)))
    if not tables:
        raise ConnectorValidationError(f"No table-like data found at {url}")
    return tables[0]


def _get_with_retry(
    session: requests.Session,
    url: str,
    timeout: int = 10,
    attempts: int = 2,
    **request_kwargs,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, timeout=timeout, **request_kwargs)
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == attempts:
                raise
            time.sleep(1)
    raise ConnectorValidationError(f"Failed to fetch {url}: {last_error}")


def _post_with_retry(
    session: requests.Session,
    url: str,
    timeout: int = 10,
    attempts: int = 2,
    **request_kwargs,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = session.post(url, timeout=timeout, **request_kwargs)
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == attempts:
                raise
            time.sleep(1)
    raise ConnectorValidationError(f"Failed to post to {url}: {last_error}")


def _build_url_with_query(url: str, **params: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: value for key, value in params.items() if value is not None})
    return urlunparse(parsed._replace(query=urlencode(query)))


def _append_raw_query(url: str, raw_query: str) -> str:
    separator = "&" if urlparse(url).query else "?"
    return f"{url}{separator}{raw_query}"


def _to_float(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace("\xa0", " ", regex=False)
        .str.replace("\\n", "", regex=False)
        .str.replace("\n", "", regex=False)
        .str.replace(" cents", "", regex=False)
        .str.strip()
        .replace({"": None, "nan": None, "None": None})
    )
    return pd.to_numeric(cleaned, errors="coerce")


def _normalize_column_name(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()


def _resolve_column(frame: pd.DataFrame, requested_column: str, source_label: str) -> str:
    normalized_request = _normalize_column_name(requested_column).casefold()
    for column in frame.columns:
        if _normalize_column_name(column).casefold() == normalized_request:
            return column
    raise ConnectorValidationError(f"{source_label} is missing required column '{requested_column}'.")


def _apply_configured_price_scaling(
    price_frame: pd.DataFrame,
    distribution_frame: pd.DataFrame,
    fund_config: dict,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cutoff = fund_config.get("price_scale_before_date")
    factor_value = fund_config.get("price_scale_before_factor")
    if not cutoff or factor_value in (None, ""):
        return price_frame.copy(), distribution_frame.copy()

    try:
        factor = float(factor_value)
    except (TypeError, ValueError) as exc:
        raise ConnectorValidationError("price_scale_before_factor must be numeric.") from exc
    if factor <= 0:
        raise ConnectorValidationError("price_scale_before_factor must be positive.")

    cutoff_date = pd.Timestamp(cutoff)
    prices = price_frame.copy()
    distributions = distribution_frame.copy()

    if "date" in prices.columns and "nav" in prices.columns:
        price_dates = pd.to_datetime(prices["date"], errors="coerce")
        price_mask = price_dates < cutoff_date
        prices.loc[price_mask, "nav"] = pd.to_numeric(prices.loc[price_mask, "nav"], errors="coerce") * factor

    if "date" in distributions.columns and "distribution" in distributions.columns:
        distribution_dates = pd.to_datetime(distributions["date"], errors="coerce")
        distribution_mask = distribution_dates < cutoff_date
        distributions.loc[distribution_mask, "distribution"] = (
            pd.to_numeric(distributions.loc[distribution_mask, "distribution"], errors="coerce") * factor
        )

    return prices, distributions


def _parse_channelcapital_unit_price_csv(
    csv_text: str,
    price_field: str,
    distribution_field: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = pd.read_csv(StringIO(csv_text))
    frame.columns = [_normalize_column_name(column) for column in frame.columns]

    date_column = next((column for column in frame.columns if _normalize_column_name(column).casefold() == "date"), None)
    if date_column is None:
        raise ConnectorValidationError("Channel Capital unit price CSV is missing required column 'Date'.")
    price_column = _resolve_column(frame, price_field, "Channel Capital unit price CSV")
    distribution_column = _resolve_column(frame, distribution_field, "Channel Capital unit price CSV")

    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(frame[date_column], errors="coerce"),
            "nav": _to_float(frame[price_column]),
        }
    ).dropna(subset=["date", "nav"])

    distributions = pd.DataFrame(
        {
            "date": pd.to_datetime(frame[date_column], errors="coerce"),
            "distribution": _to_float(frame[distribution_column]),
        }
    ).dropna(subset=["date"])
    distributions = distributions[distributions["distribution"].fillna(0.0) > 0.0]

    return prices, distributions


def _build_cfs_history_download_url(
    *,
    main_group: str,
    group_id: str,
    product_id: str,
    start_date: str,
    end_date: str,
    download_url: str = "https://www.colonialfirststate.com.au/Price_Performance/Download.aspx",
) -> str:
    return _build_url_with_query(
        download_url,
        hidDLProductIDs=str(group_id),
        hidDLFundIDs=str(product_id),
        hidDLMainGroup=str(main_group),
        hidDLFromDate=f"{pd.Timestamp(start_date):%d/%m/%Y} 12:00:00 AM",
        hidDLToDate=f"{pd.Timestamp(end_date):%d/%m/%Y} 12:00:00 AM",
        hidDLTab="History",
    )


def _parse_cfs_history_csv(csv_text: str, price_field: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    if _normalize_column_name(price_field).casefold() != "exit price":
        raise ConnectorValidationError("CFS history export currently supports 'Exit Price' only.")

    frame = pd.read_csv(
        StringIO(csv_text),
        header=None,
        names=["date", "entry_price", "post_income_exit_price", "exit_price"],
        usecols=[0, 1, 2, 3],
    )
    if frame.empty:
        raise ConnectorValidationError("CFS history export did not contain any rows.")

    dates = pd.to_datetime(frame["date"], format="%d/%m/%Y", errors="coerce")
    pre_income_exit = _to_float(frame["exit_price"])
    post_income_exit = _to_float(frame["post_income_exit_price"])
    has_post_income_price = post_income_exit.notna() & (post_income_exit > 0) & pre_income_exit.notna()

    nav = pre_income_exit.where(~has_post_income_price, post_income_exit)
    distributions = (pre_income_exit - post_income_exit).where(has_post_income_price, 0.0)

    prices = pd.DataFrame({"date": dates, "nav": nav}).dropna(subset=["date", "nav"])
    distribution_rows = pd.DataFrame({"date": dates, "distribution": distributions}).dropna(
        subset=["date", "distribution"]
    )
    distribution_rows = distribution_rows[distribution_rows["distribution"] > 0.0]
    return prices, distribution_rows


def _extract_pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - exercised in live smoke checks instead
        raise ConnectorValidationError("PDF-backed sources require the 'pypdf' package.") from exc

    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _create_cloudscraper_session():
    try:
        import cloudscraper
    except ImportError as exc:  # pragma: no cover - exercised in live smoke checks instead
        raise ConnectorValidationError("Cloudflare-protected sources require the 'cloudscraper' package.") from exc

    return cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})


def _merge_prices_and_distributions(
    price_frame: pd.DataFrame,
    distribution_frame: pd.DataFrame,
    start_date: str,
    end_date: str,
    distribution_timing: str = "same_date",
) -> pd.DataFrame:
    merged = price_frame.copy()
    merged["date"] = pd.to_datetime(merged["date"], errors="coerce")
    if hasattr(merged["date"].dt, "tz") and merged["date"].dt.tz is not None:
        merged["date"] = merged["date"].dt.tz_convert(None)
    merged["distribution"] = 0.0
    if not distribution_frame.empty:
        distribution_frame = distribution_frame.copy()
        distribution_frame["date"] = pd.to_datetime(distribution_frame["date"], errors="coerce")
        if hasattr(distribution_frame["date"].dt, "tz") and distribution_frame["date"].dt.tz is not None:
            distribution_frame["date"] = distribution_frame["date"].dt.tz_convert(None)
        timing = (distribution_timing or "same_date").strip().lower()
        if timing == "next_price_date":
            distribution_frame = _align_distributions_to_next_price_date(merged[["date", "nav"]], distribution_frame)
        elif timing != "same_date":
            raise ConnectorValidationError(f"Unsupported distribution_timing '{distribution_timing}'.")
        distribution_series = distribution_frame.groupby("date")["distribution"].sum()
        merged["distribution"] = merged["date"].map(distribution_series).fillna(0.0)

    normalized = BaseConnector.normalize_frame(merged)
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    return normalized.loc[(normalized.index >= start) & (normalized.index <= end)]


def _json_date(date_value: str) -> str:
    timestamp = pd.Timestamp(date_value)
    return f"/Date({int(timestamp.timestamp() * 1000)})/"


def _read_html_tables(html: str) -> list[pd.DataFrame]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_html(StringIO(html))


def _parse_report_csv(csv_text: str, header_marker: str) -> pd.DataFrame:
    lines = csv_text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(header_marker):
            data_lines = []
            for candidate in lines[index:]:
                if not candidate.strip():
                    break
                data_lines.append(candidate)
            if len(data_lines) < 2:
                break
            return pd.read_csv(StringIO("\n".join(data_lines)))
    raise ConnectorValidationError(f"Could not find CSV header '{header_marker}'.")


def _build_macquarie_history_url(
    metadata_payload: list[dict[str, object]],
    apir_code: str,
    assets_base_url: str,
) -> str:
    target = str(apir_code).strip().casefold()
    match = next(
        (
            row
            for row in metadata_payload
            if str(row.get("apirCode", "")).strip().casefold() == target
            and str(row.get("historicalPricesFileName", "")).strip()
        ),
        None,
    )
    if match is None:
        raise ConnectorValidationError(f"Macquarie unit-price metadata did not contain APIR '{apir_code}'.")

    path = str(match["historicalPricesFileName"]).strip().lstrip("/")
    return requests.utils.requote_uri(f"{assets_base_url.rstrip('/')}/{path}")


def _parse_macquarie_historical_price_csv(csv_text: str, price_field: str) -> pd.DataFrame:
    frame = pd.read_csv(StringIO(csv_text))
    required_columns = {"Valuation Date", price_field}
    if not required_columns.issubset(frame.columns):
        raise ConnectorValidationError("Macquarie historical price CSV is missing required columns.")

    prices = _to_float(frame[price_field])
    distributions = _to_float(frame.get("CPU", pd.Series(index=frame.index, dtype="object"))) / 100.0
    distribution_values = distributions.fillna(0.0)
    use_ex_price = distribution_values != 0.0
    nav = prices.where(~use_ex_price, prices - distribution_values)

    return pd.DataFrame(
        {
            "date": pd.to_datetime(frame["Valuation Date"], format="%d %b %Y", errors="coerce"),
            "nav": nav,
            "distribution": distribution_values,
        }
    ).dropna(subset=["date", "nav"])


def _extract_wpdatatable_rows(page_html: str, desc_input_id: str) -> pd.DataFrame:
    soup = BeautifulSoup(page_html, "html.parser")
    desc = soup.find("input", {"id": desc_input_id})
    if desc is None or not desc.has_attr("value"):
        raise ConnectorValidationError(f"Could not locate wpDataTable descriptor '{desc_input_id}'.")

    payload = json.loads(desc["value"])
    table_wp_id = payload["tableWpId"]
    columns = [definition["origHeader"] for definition in payload["dataTableParams"]["columnDefs"]]

    rows = []
    for row in soup.select(f"tr[id^='table_{table_wp_id}_row_']"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
        if len(cells) == len(columns):
            rows.append(dict(zip(columns, cells)))

    if not rows:
        raise ConnectorValidationError(f"No row data found for wpDataTable '{desc_input_id}'.")

    return pd.DataFrame(rows)


def _find_accordion_distribution_table(page_html: str, fund_name: str) -> pd.DataFrame:
    soup = BeautifulSoup(page_html, "html.parser")
    for item in soup.select(".accordion-item"):
        data_name = item.get("data-name", "")
        if fund_name.casefold() in data_name.casefold():
            table = item.find("table")
            if table is None:
                break
            rows = []
            for row in table.select("tbody tr"):
                cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
                if len(cells) >= 2:
                    rows.append({"date": cells[0], "distribution": cells[1]})
            return pd.DataFrame(rows)
    raise ConnectorValidationError(f"Distribution table not found for '{fund_name}'.")


def _parse_perpetual_distribution_table(table: pd.DataFrame) -> pd.DataFrame:
    parsed = table.copy()
    parsed.columns = parsed.iloc[0]
    parsed = parsed.iloc[1:].reset_index(drop=True)

    if "Report Period To" not in parsed.columns or "Distribution Amount" not in parsed.columns:
        raise ConnectorValidationError("Perpetual distribution table is missing required columns.")

    month_rows = parsed["Report Period To"].astype(str).str.replace(" Download Report", "", regex=False).str.strip()
    mask = month_rows.str.match(r"^[A-Za-z]+\s+\d{4}$")
    if not mask.any():
        return pd.DataFrame(columns=["date", "distribution"])

    dates = pd.to_datetime(month_rows[mask], format="%B %Y", errors="coerce") + pd.offsets.MonthEnd(0)
    result = pd.DataFrame(
        {
            "date": dates,
            "distribution": _to_float(parsed.loc[mask, "Distribution Amount"]) / 100.0,
        }
    ).dropna(subset=["date", "distribution"])
    return result


def _fetch_perpetual_distributions(
    session: requests.Session,
    distribution_url: str,
    max_pages: int = 10,
) -> pd.DataFrame:
    pages: list[pd.DataFrame] = []
    seen_dates: set[pd.Timestamp] = set()

    for page_number in range(1, max_pages + 1):
        page_url = distribution_url if page_number == 1 else _build_url_with_query(distribution_url, page=str(page_number))
        response = _get_with_retry(session, page_url, timeout=10)
        try:
            tables = _read_html_tables(response.text)
        except ValueError:
            break

        if not tables:
            break

        parsed = _parse_perpetual_distribution_table(tables[0])
        if parsed.empty:
            break

        parsed = parsed[~parsed["date"].isin(seen_dates)]
        if parsed.empty:
            break

        seen_dates.update(parsed["date"].tolist())
        pages.append(parsed)

    if not pages:
        return pd.DataFrame(columns=["date", "distribution"])

    return pd.concat(pages, ignore_index=True)


def _align_distributions_to_next_price_date(
    prices: pd.DataFrame,
    distributions: pd.DataFrame,
    max_gap_days: int = 10,
) -> pd.DataFrame:
    if prices.empty or distributions.empty:
        return distributions

    price_dates = pd.Index(pd.to_datetime(prices["date"], errors="coerce")).dropna().sort_values().unique()
    aligned_rows = []
    max_gap = pd.Timedelta(days=max_gap_days)

    for row in distributions.itertuples(index=False):
        distribution_date = pd.Timestamp(row.date)
        insert_at = price_dates.searchsorted(distribution_date, side="right")
        aligned_date = distribution_date

        if insert_at < len(price_dates):
            candidate = price_dates[insert_at]
            if candidate - distribution_date <= max_gap:
                aligned_date = candidate
        elif len(price_dates):
            previous = price_dates[-1]
            if distribution_date - previous <= max_gap:
                aligned_date = previous

        aligned_rows.append({"date": aligned_date, "distribution": row.distribution})

    return pd.DataFrame(aligned_rows)


def _build_airlie_price_and_distribution_frames(
    history_frame: pd.DataFrame,
    price_field: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "Date" not in history_frame.columns or price_field not in history_frame.columns:
        raise ConnectorValidationError("Airlie price history is missing required columns.")

    frame = history_frame.copy()
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame = frame.dropna(subset=["Date"])

    type_series = (
        frame.get("Type", pd.Series(index=frame.index, dtype="object"))
        .fillna("")
        .astype(str)
        .str.strip()
        .str.casefold()
    )
    frame[price_field] = _to_float(frame[price_field])
    frame = frame.dropna(subset=[price_field])

    cum_rows = (
        frame.loc[type_series != "ex", ["Date", price_field]]
        .rename(columns={"Date": "date", price_field: "nav"})
        .groupby("date", as_index=False)["nav"]
        .last()
    )
    ex_rows = (
        frame.loc[type_series == "ex", ["Date", price_field]]
        .rename(columns={"Date": "date", price_field: "nav"})
        .groupby("date", as_index=False)["nav"]
        .last()
    )

    prices = cum_rows.copy()
    if not ex_rows.empty:
        ex_map = ex_rows.set_index("date")["nav"]
        prices["nav"] = prices["date"].map(ex_map).fillna(prices["nav"])

    distributions = cum_rows.merge(ex_rows, on="date", how="inner", suffixes=("_cum", "_ex"))
    distributions["distribution"] = distributions["nav_cum"] - distributions["nav_ex"]
    distributions = distributions[distributions["distribution"] > 0][["date", "distribution"]]

    return prices, distributions


def _build_solaris_price_and_distribution_frames(
    price_history: pd.DataFrame,
    distribution_history: pd.DataFrame,
    price_field: str,
    ex_price_field: str,
    distribution_field: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required_price_columns = {"Date", price_field}
    if not required_price_columns.issubset(price_history.columns):
        raise ConnectorValidationError("Solaris price history is missing required columns.")

    required_distribution_columns = {"Ex Date", ex_price_field, distribution_field}
    if not required_distribution_columns.issubset(distribution_history.columns):
        raise ConnectorValidationError("Solaris distribution history is missing required columns.")

    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(price_history["Date"], format="%d/%m/%Y", errors="coerce"),
            "nav": _to_float(price_history[price_field]),
        }
    ).dropna(subset=["date", "nav"])

    distributions = pd.DataFrame(
        {
            "date": pd.to_datetime(distribution_history["Ex Date"], format="%d/%m/%Y", errors="coerce"),
            "nav": _to_float(distribution_history[ex_price_field]),
            "distribution": _to_float(distribution_history[distribution_field]) / 100.0,
        }
    ).dropna(subset=["date", "nav"])
    distributions = distributions[distributions["distribution"].fillna(0.0) > 0.0]

    if not distributions.empty:
        ex_price_map = distributions.set_index("date")["nav"]
        prices["nav"] = prices["date"].map(ex_price_map).fillna(prices["nav"])

    return prices, distributions.loc[:, ["date", "distribution"]]


def _build_pendal_history_url(
    product_id: str,
    start_date: str,
    end_date: str,
    history_type: str,
) -> str:
    query = urlencode(
        {
            "class_code": "",
            "date-current": "",
            "date-from": pd.Timestamp(start_date).strftime("%d-%b-%Y"),
            "date-to": pd.Timestamp(end_date).strftime("%d-%b-%Y"),
            "history-type": history_type,
            "output": "csv",
            "product-id": product_id,
        }
    )
    return f"https://pendalgroup.com/history-2?{query}"


def _fetch_iml_export_csv(
    session: requests.Session,
    portfolio_code: str,
    action: str,
    ajax_url: str = "https://iml.com.au/wp-admin/admin-ajax.php",
) -> str:
    response = _post_with_retry(
        session,
        ajax_url,
        timeout=20,
        data={"portfolio": portfolio_code, "action": action},
    )
    payload = response.json()
    file_url = payload.get("fileUrl")
    if payload.get("error") or not file_url:
        raise ConnectorValidationError(f"IML export request failed for portfolio '{portfolio_code}'.")

    file_response = _get_with_retry(session, str(file_url), timeout=20)
    return file_response.content.decode("utf-8", errors="replace")


def _parse_iml_distribution_period(value: object) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    text = str(value).strip()
    if not text:
        return None

    parsed = pd.to_datetime(text, format="%Y %B", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return (parsed + pd.offsets.MonthEnd(0)).normalize()


def _parse_iml_unit_price_history(csv_text: str, price_field: str) -> pd.DataFrame:
    frame = pd.read_csv(StringIO(csv_text))
    if "Date" not in frame.columns or price_field not in frame.columns:
        raise ConnectorValidationError("IML unit price export is missing required columns.")

    return pd.DataFrame(
        {
            "date": pd.to_datetime(frame["Date"], format="%d/%m/%Y", errors="coerce"),
            "nav": _to_float(frame[price_field]),
        }
    ).dropna(subset=["date", "nav"])


def _parse_iml_distribution_history(csv_text: str) -> pd.DataFrame:
    frame = pd.read_csv(StringIO(csv_text))
    required_columns = {"Period ending", "Amount (cpu)"}
    if not required_columns.issubset(frame.columns):
        raise ConnectorValidationError("IML distribution export is missing required columns.")

    distributions = pd.DataFrame(
        {
            "date": frame["Period ending"].map(_parse_iml_distribution_period),
            "distribution": _to_float(frame["Amount (cpu)"]) / 100.0,
        }
    ).dropna(subset=["date", "distribution"])
    return distributions[distributions["distribution"] != 0.0]


def _parse_dnr_unit_price_history_frame(
    history_frame: pd.DataFrame,
    price_field: str,
) -> pd.DataFrame:
    if "Date" not in history_frame.columns or price_field not in history_frame.columns:
        raise ConnectorValidationError("DNR unit price history is missing required columns.")

    return pd.DataFrame(
        {
            "date": pd.to_datetime(history_frame["Date"], dayfirst=True, errors="coerce"),
            "nav": _to_float(history_frame[price_field]),
        }
    ).dropna(subset=["date", "nav"])


def _parse_dnr_distribution_history_table(table: pd.DataFrame) -> pd.DataFrame:
    if table.empty:
        return pd.DataFrame(columns=["date", "distribution"])

    blocks: list[dict[str, list[object]]] = []
    current_block: dict[str, list[object]] = {}

    for row in table.itertuples(index=False):
        label = str(row[0]).strip()
        values = [value for value in row[1:] if pd.notna(value) and str(value).strip()]
        if not label:
            continue
        if label.startswith("Financial Year"):
            if current_block:
                blocks.append(current_block)
            current_block = {}
            continue
        current_block[label] = values

    if current_block:
        blocks.append(current_block)

    rows: list[dict[str, object]] = []
    for block in blocks:
        period_end_dates = block.get("Period end date", [])
        cash_distributions = block.get("Cash distribution amount (CPU)", [])
        for period_end, cpu in zip(period_end_dates, cash_distributions):
            date = pd.to_datetime(period_end, dayfirst=True, errors="coerce")
            amount = pd.to_numeric(cpu, errors="coerce")
            if pd.isna(date) or pd.isna(amount) or float(amount) == 0.0:
                continue
            rows.append({"date": date, "distribution": float(amount) / 100.0})

    return pd.DataFrame(rows)


def _build_first_sentier_history_file_path(fund_query: str, audience: str = "adviser") -> str:
    normalized_query = str(fund_query).replace("-", "_")
    return f"cfsgam/historical-price/AU/en/{audience}/{normalized_query}.json"


def _parse_first_sentier_history_csv(csv_text: str, price_field: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    lines = [line for line in csv_text.splitlines() if line.strip()]
    if len(lines) < 2:
        raise ConnectorValidationError("First Sentier history export did not contain enough rows.")

    frame = pd.read_csv(StringIO("\n".join(lines[1:])))
    required_columns = {"DATE", price_field, "DISTRIBUTION"}
    if not required_columns.issubset(frame.columns):
        raise ConnectorValidationError("First Sentier history export is missing required columns.")

    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(frame["DATE"], format="%d %b %Y", errors="coerce"),
            "nav": _to_float(frame[price_field]),
        }
    ).dropna(subset=["date", "nav"])

    distributions = pd.DataFrame(
        {
            "date": pd.to_datetime(frame["DATE"], format="%d %b %Y", errors="coerce"),
            "distribution": _to_float(frame["DISTRIBUTION"]) / 100.0,
        }
    ).dropna(subset=["date", "distribution"])
    distributions = distributions[distributions["distribution"] != 0.0]
    return prices, distributions


def _parse_vanguard_price_history(payload: dict) -> pd.DataFrame:
    data = payload.get("data") or []
    if not data:
        raise ConnectorValidationError("Vanguard price payload was empty.")

    nav_prices = data[0].get("navPrices") or []
    if not nav_prices:
        raise ConnectorValidationError("Vanguard price payload did not include navPrices.")

    frame = pd.DataFrame(nav_prices)
    nav_only = frame[frame.get("measureTypeCode").fillna("").eq("NAV")]
    return pd.DataFrame(
        {
            "date": pd.to_datetime(nav_only["asOfDate"], errors="coerce"),
            "nav": pd.to_numeric(nav_only["price"], errors="coerce"),
        }
    ).dropna(subset=["date", "nav"])


def _parse_vanguard_distribution_history(payload: dict) -> pd.DataFrame:
    items = ((payload.get("data") or {}).get("items")) or []
    rows: list[dict[str, object]] = []
    for item in items:
        ex_date = item.get("exDividendDate") or item.get("recordDate")
        if not ex_date:
            continue
        distribution = sum(
            float(detail.get("distributionAmount") or 0.0)
            for detail in item.get("taxDetails") or []
            if detail.get("distributionLevelCode") == "ACTL"
            and (detail.get("distributionType") or {}).get("distCode") == "CASH"
        )
        if distribution == 0.0:
            continue
        rows.append({"date": pd.to_datetime(ex_date, errors="coerce"), "distribution": distribution})

    return pd.DataFrame(rows).dropna(subset=["date", "distribution"])


def _parse_lazard_historical_nav(
    payload: list[dict[str, object]],
    share_class_id: str,
    price_field: str,
) -> pd.DataFrame:
    if not payload:
        raise ConnectorValidationError("Lazard API payload was empty.")

    product = payload[0]
    share_class = next(
        (item for item in product.get("shareClasses", []) if str(item.get("id")) == str(share_class_id)),
        None,
    )
    if share_class is None:
        raise ConnectorValidationError(f"Lazard API payload did not contain share class '{share_class_id}'.")

    historical_nav = ((share_class.get("data") or {}).get("nav") or {}).get("historicalNav") or []
    if not historical_nav:
        raise ConnectorValidationError("Lazard API payload did not include historical NAV rows.")

    frame = pd.DataFrame(historical_nav)
    if "navAsOfDate" not in frame.columns or price_field not in frame.columns:
        raise ConnectorValidationError("Lazard historical NAV rows are missing required columns.")

    return pd.DataFrame(
        {
            "date": pd.to_datetime(frame["navAsOfDate"], errors="coerce"),
            "nav": pd.to_numeric(frame[price_field], errors="coerce"),
        }
    ).dropna(subset=["date", "nav"])


def _extract_lazard_annualized_net_performance(share_class: dict[str, object]) -> dict[int, float]:
    performance = (((share_class.get("data") or {}).get("performance") or {}).get("annualized") or {})
    net_aud_rows = ((performance.get("net") or {}).get("AUD")) or []
    if not net_aud_rows:
        return {}

    row = net_aud_rows[0]
    fields = {3: "threeYears", 5: "fiveYears"}
    values: dict[int, float] = {}
    for years, field in fields.items():
        value = (row.get(field) or {}).get("value") if isinstance(row.get(field), dict) else None
        try:
            values[years] = float(value)
        except (TypeError, ValueError):
            continue
    return values


def _extract_lazard_annualized_performance_as_of(share_class: dict[str, object]) -> pd.Timestamp | None:
    performance = (((share_class.get("data") or {}).get("performance") or {}).get("annualized") or {})
    timestamp = pd.to_datetime(performance.get("asOfDate"), errors="coerce")
    if pd.isna(timestamp):
        return None
    return pd.Timestamp(timestamp).normalize()


def _build_lazard_total_return_series(frame: pd.DataFrame) -> pd.Series:
    nav = pd.to_numeric(frame["nav"], errors="coerce")
    distributions = pd.to_numeric(
        frame.get("distribution", pd.Series(index=frame.index, dtype=float)),
        errors="coerce",
    ).fillna(0.0)
    returns = nav / nav.shift(1) - 1
    distribution_mask = distributions != 0
    returns.loc[distribution_mask] = (nav.loc[distribution_mask] + distributions.loc[distribution_mask]) / nav.shift(1).loc[
        distribution_mask
    ] - 1
    returns.iloc[0] = 0.0
    return (1 + returns.fillna(0.0)).cumprod() * 100.0


def _extend_lazard_history_with_performance_anchors(
    history: pd.DataFrame,
    share_class: dict[str, object],
    end_date: str,
) -> pd.DataFrame:
    if history.empty or "nav" not in history.columns:
        return history

    performance = _extract_lazard_annualized_net_performance(share_class)
    if not performance:
        return history

    frame = history.copy().sort_index()
    frame.index = pd.to_datetime(frame.index, errors="coerce").normalize()
    frame = frame[~frame.index.isna()]
    if "distribution" not in frame.columns:
        frame["distribution"] = 0.0

    end = pd.Timestamp(end_date).normalize()
    eligible_dates = frame.index[frame.index <= end]
    if len(eligible_dates) == 0:
        return history

    end_timestamp = eligible_dates[-1]
    performance_as_of = _extract_lazard_annualized_performance_as_of(share_class)
    performance_base_timestamp = end_timestamp
    if performance_as_of is not None and performance_as_of <= end_timestamp:
        performance_dates = frame.index[frame.index <= performance_as_of]
        if len(performance_dates) > 0:
            performance_base_timestamp = performance_dates[-1]
    first_timestamp = frame.index[0]
    first_nav = float(frame.loc[first_timestamp, "nav"])
    if first_nav <= 0:
        return history

    tri = _build_lazard_total_return_series(frame.loc[:end_timestamp])
    performance_base_growth = float(tri.loc[performance_base_timestamp]) / 100.0
    anchor_rows: list[dict[str, object]] = []
    for years in sorted(performance, reverse=True):
        anchor_date = end_timestamp - pd.DateOffset(years=years)
        if frame.index.min() <= anchor_date:
            continue

        annualized_return = performance[years] / 100.0
        total_return = (1 + annualized_return) ** years
        if total_return <= 0:
            continue

        anchor_rows.append(
            {
                "date": anchor_date,
                "nav": first_nav * performance_base_growth / total_return,
                "distribution": 0.0,
            }
        )

    if not anchor_rows:
        return history

    anchors = pd.DataFrame(anchor_rows).set_index("date")
    return pd.concat([anchors, frame]).sort_index()


def _parse_lazard_share_class_order(pdf_text: str) -> list[str]:
    annual_matches = re.findall(r"\b([IWS] Class)\b", pdf_text)
    annual_order: list[str] = []
    for match in annual_matches:
        if match not in annual_order:
            annual_order.append(match)

    if annual_order:
        return annual_order

    legacy_matches = re.findall(r"\(([IWS] Class)\)", pdf_text)
    legacy_order: list[str] = []
    for match in legacy_matches:
        if match not in legacy_order:
            legacy_order.append(match)
    return legacy_order


def _parse_lazard_annual_distribution_pdf_text(pdf_text: str, share_class_label: str) -> pd.DataFrame:
    share_classes = _parse_lazard_share_class_order(pdf_text)
    if share_class_label not in share_classes:
        raise ConnectorValidationError(f"Lazard distribution PDF did not contain share class '{share_class_label}'.")

    row_match = re.search(
        r"Cash Distribution\s+(.*?)(?:MIT fund payment amount|The abovenamed fund|Lazard Asset Management Pacific Co\.)",
        pdf_text,
        flags=re.S,
    )
    if row_match is None:
        raise ConnectorValidationError("Lazard annual distribution PDF did not contain a cash distribution row.")

    tokens = re.findall(r"TBA|-|[0-9]+\.[0-9]+", row_match.group(1))
    if len(tokens) % len(share_classes) != 0:
        raise ConnectorValidationError("Lazard annual distribution PDF cash distribution columns were misaligned.")

    all_dates = re.findall(r"\b\d{2} [A-Za-z]{3} \d{2}\b", pdf_text)
    unique_dates = list(dict.fromkeys(all_dates))
    block_size = len(tokens) // len(share_classes)
    if len(unique_dates) < block_size:
        raise ConnectorValidationError("Lazard annual distribution PDF cash distribution row was truncated.")

    start = share_classes.index(share_class_label) * block_size
    selected_dates = unique_dates[:block_size]
    selected_tokens = tokens[start : start + block_size]

    rows: list[dict[str, object]] = []
    for date_text, token in zip(selected_dates, selected_tokens):
        if token in {"-", "TBA"}:
            continue
        rows.append(
            {
                "date": pd.to_datetime(date_text, format="%d %b %y", errors="coerce"),
                "distribution": float(token) / 100.0,
            }
        )

    return pd.DataFrame(rows).dropna(subset=["date", "distribution"])


def _parse_lazard_legacy_distribution_pdf_text(pdf_text: str, share_class_label: str) -> pd.DataFrame:
    share_classes = _parse_lazard_share_class_order(pdf_text)
    if share_class_label not in share_classes:
        raise ConnectorValidationError(f"Lazard legacy distribution PDF did not contain share class '{share_class_label}'.")

    row_pattern = re.compile(
        r"(\d{2}-[A-Za-z]{3}-\d{2})\s+((?:-|[0-9]+\.[0-9]+)(?:\s+(?:-|[0-9]+\.[0-9]+)){8})"
    )
    rows: list[dict[str, object]] = []
    net_cash_offset = share_classes.index(share_class_label) * 3 + 2

    for date_text, values_text in row_pattern.findall(pdf_text):
        tokens = re.findall(r"-|[0-9]+\.[0-9]+", values_text)
        if len(tokens) <= net_cash_offset:
            continue
        token = tokens[net_cash_offset]
        if token == "-":
            continue
        rows.append(
            {
                "date": pd.to_datetime(date_text, format="%d-%b-%y", errors="coerce"),
                "distribution": float(token) / 100.0,
            }
        )

    if not rows:
        raise ConnectorValidationError("Lazard legacy distribution PDF did not contain usable distribution rows.")
    return pd.DataFrame(rows).dropna(subset=["date", "distribution"])


def _parse_lazard_distribution_pdf_text(pdf_text: str, share_class_label: str) -> pd.DataFrame:
    if "Cash Distribution" in pdf_text:
        return _parse_lazard_annual_distribution_pdf_text(pdf_text, share_class_label)
    if "Net Cash" in pdf_text:
        return _parse_lazard_legacy_distribution_pdf_text(pdf_text, share_class_label)
    raise ConnectorValidationError("Unrecognized Lazard distribution PDF layout.")


def _build_forager_price_and_distribution_frames(
    history_frame: pd.DataFrame,
    price_field: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required_columns = {"Date", price_field}
    if not required_columns.issubset(history_frame.columns):
        raise ConnectorValidationError("Forager price history is missing required columns.")

    frame = history_frame.copy()
    frame["date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame["nav"] = _to_float(frame[price_field])
    explicit_distribution = pd.to_numeric(frame.get("Distribution"), errors="coerce")
    fallback_distribution = pd.Series(index=frame.index, dtype="float64")
    if price_field != "Redemption Price" and "Redemption Price" in frame.columns:
        redemption_values = _to_float(frame["Redemption Price"])
        fallback_mask = (
            explicit_distribution.isna()
            & redemption_values.notna()
            & frame["nav"].notna()
            & (redemption_values < 0.5)
            & (frame["nav"] > 0.5)
        )
        fallback_distribution = redemption_values.where(fallback_mask)

    frame["distribution"] = explicit_distribution.fillna(fallback_distribution)
    frame = frame.dropna(subset=["date", "nav"])

    price_rows: list[dict[str, object]] = []
    distribution_rows: list[dict[str, object]] = []
    for date, group in frame.groupby("date", sort=True):
        distribution_group = group[group["distribution"].fillna(0.0) != 0.0]
        if not distribution_group.empty:
            ex_row = distribution_group.iloc[-1]
            price_rows.append({"date": date, "nav": ex_row["nav"]})
            distribution_rows.append({"date": date, "distribution": float(ex_row["distribution"])})
            continue

        latest_row = group.iloc[-1]
        price_rows.append({"date": date, "nav": latest_row["nav"]})

    return pd.DataFrame(price_rows), pd.DataFrame(distribution_rows)


def _parse_katana_daily_price(page_html: str) -> pd.DataFrame:
    match = re.search(r"Daily Price as at (\d{2}/\d{2}/\d{4}):\s*\$([0-9]+\.[0-9]+)", page_html)
    if not match:
        return pd.DataFrame(columns=["date", "nav"])

    return pd.DataFrame(
        {
            "date": [pd.to_datetime(match.group(1), format="%d/%m/%Y", errors="coerce")],
            "nav": [float(match.group(2))],
        }
    ).dropna(subset=["date", "nav"])


def _parse_katana_month_label(year: int, label: str) -> tuple[pd.Timestamp, bool]:
    normalized = " ".join(str(label).split())
    is_post = normalized.casefold().endswith(" post")
    month_token = re.sub(r"\s+(Pre|Post)$", "", normalized, flags=re.I)
    month = pd.Timestamp(f"01 {month_token} {year}").month
    base_date = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
    if is_post:
        base_date += pd.Timedelta(days=1)
    return base_date, is_post


def _parse_katana_monthly_prices(page_html: str) -> pd.DataFrame:
    soup = BeautifulSoup(page_html, "html.parser")
    monthly_anchor = soup.find(id="monthly-unit-price")
    annual_anchor = soup.find(id="annual-distribution")
    if monthly_anchor is None:
        raise ConnectorValidationError("Katana monthly unit price section was not found.")

    rows: list[dict[str, object]] = []
    for node in monthly_anchor.find_all_next():
        if node is annual_anchor:
            break
        if node.name != "div":
            continue

        classes = set(node.get("class") or [])
        if not {"col-md-2", "col-12"}.issubset(classes):
            continue

        year_link = node.find("a", class_="accord-title")
        values = node.find("ul")
        if year_link is None or values is None:
            continue

        year_match = re.search(r"\b(\d{4})\b", year_link.get_text(" ", strip=True))
        if not year_match:
            continue
        year = int(year_match.group(1))

        for item in values.find_all("li"):
            text = " ".join(item.get_text(" ", strip=True).split())
            match = re.match(r"([A-Za-z]+(?:\s+(?:Pre|Post))?)\s+\$([0-9]+\.[0-9]+)", text)
            if not match:
                continue
            date, _ = _parse_katana_month_label(year, match.group(1))
            rows.append({"date": date, "nav": float(match.group(2))})

    if not rows:
        raise ConnectorValidationError("Katana monthly unit price rows could not be parsed.")
    return pd.DataFrame(rows)


def _parse_katana_annual_distributions(page_html: str) -> pd.DataFrame:
    soup = BeautifulSoup(page_html, "html.parser")
    annual_anchor = soup.find(id="annual-distribution")
    if annual_anchor is None:
        raise ConnectorValidationError("Katana annual distribution section was not found.")

    annual_row = annual_anchor.find_parent("div", class_="row")
    if annual_row is None:
        annual_row = annual_anchor.find_next("div", class_="row")
    if annual_row is None:
        raise ConnectorValidationError("Katana annual distribution section was malformed.")

    rows: list[dict[str, object]] = []
    for item in annual_row.find_all("li"):
        text = " ".join(item.get_text(" ", strip=True).split())
        match = re.match(r"([A-Za-z]+)\s+(\d{4})\s+([0-9]+\.[0-9]+)\s+CPU", text, flags=re.I)
        if not match:
            continue

        month_name, year_text, cpu_text = match.groups()
        date = pd.Timestamp(f"01 {month_name} {year_text}") + pd.offsets.MonthEnd(0)
        rows.append({"date": date, "distribution": float(cpu_text) / 100.0})

    if not rows:
        raise ConnectorValidationError("Katana annual distribution rows could not be parsed.")
    return pd.DataFrame(rows)


def _parse_bennelong_history_sheet(sheet_text: str, price_field: str) -> pd.DataFrame:
    if not sheet_text.strip():
        return pd.DataFrame(columns=["date", "nav", "distribution"])

    frame = pd.read_csv(StringIO(sheet_text), sep="\t")
    if "Date" not in frame.columns or price_field not in frame.columns:
        raise ConnectorValidationError("Bennelong sheet is missing required columns.")

    prices = _to_float(frame[price_field])
    distributions = _to_float(frame.get("Distribution CPU", pd.Series(index=frame.index, dtype="object"))) / 100.0
    ex_distribution_prices = _to_float(frame.get("Ex Dist. Redemption", pd.Series(index=frame.index, dtype="object")))
    use_ex_distribution_price = distributions.fillna(0.0) != 0
    nav = prices.where(~use_ex_distribution_price | ex_distribution_prices.isna(), ex_distribution_prices)

    return pd.DataFrame(
        {
            "date": pd.to_datetime(frame["Date"], format="%d/%m/%Y", errors="coerce"),
            "nav": nav,
            "distribution": distributions.fillna(0.0),
        }
    ).dropna(subset=["date", "nav"])


def _download_bennelong_history_sheet(
    session: requests.Session,
    sheet_file_id: str,
    start_date: str,
    end_date: str,
) -> str:
    form_url = f"https://www.baep.com.au/sheet_file/{sheet_file_id}/form"
    page_response = _get_with_retry(session, form_url, timeout=20)
    form_build_match = re.search(r'name="form_build_id" value="([^"]+)"', page_response.text)
    form_id_match = re.search(r'name="form_id" value="([^"]+)"', page_response.text)
    if not form_build_match or not form_id_match:
        raise ConnectorValidationError("Could not find Bennelong download form fields.")

    download_response = _post_with_retry(
        session,
        form_url,
        timeout=20,
        data={
            "date_from": pd.Timestamp(start_date).strftime("%Y-%m-%d"),
            "date_to": pd.Timestamp(end_date).strftime("%Y-%m-%d"),
            "filter": "Download",
            "form_build_id": form_build_match.group(1),
            "form_id": form_id_match.group(1),
        },
    )
    content_type = download_response.headers.get("content-type", "").lower()
    if "html" in content_type:
        raise ConnectorValidationError("Bennelong price download returned HTML instead of tabular data.")
    return download_response.content.decode("utf-8", errors="replace")


def _build_smallco_price_and_distribution_frames(
    tables: list[pd.DataFrame],
    price_field: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    history_tables: list[pd.DataFrame] = []
    for table in tables:
        if {price_field, "Date", "Distributions"}.issubset(table.columns):
            history_tables.append(table.loc[:, ["Date", price_field, "Distributions"]].copy())

    if not history_tables:
        raise ConnectorValidationError("Smallco history tables are missing required columns.")

    frame = pd.concat(history_tables, ignore_index=True)
    frame["Date"] = frame["Date"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    frame["Date"] = frame["Date"].replace({"": None, "nan": None, "NaT": None})
    frame["date"] = pd.to_datetime(frame["Date"], format="%b %y", errors="coerce") + pd.offsets.MonthEnd(0)
    frame["nav"] = _to_float(frame[price_field])
    frame["distribution"] = _to_float(frame["Distributions"])
    frame = frame.dropna(subset=["date", "nav"])

    ex_rows = frame[frame["distribution"].isna()].groupby("date", as_index=False)["nav"].first()
    cum_rows = frame[frame["distribution"].notna()].copy()
    if not cum_rows.empty:
        missing_ex_dates = cum_rows[~cum_rows["date"].isin(ex_rows["date"])].copy()
        if not missing_ex_dates.empty:
            missing_ex_dates["nav"] = missing_ex_dates["nav"] - missing_ex_dates["distribution"]
            ex_rows = pd.concat([ex_rows, missing_ex_dates[["date", "nav"]]], ignore_index=True)

    distributions = cum_rows.groupby("date", as_index=False)["distribution"].sum()
    return ex_rows, distributions


def _build_gsfm_price_and_distribution_frames(
    unit_price_history: pd.DataFrame,
    distribution_history: pd.DataFrame,
    price_field: str,
    ex_price_field: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required_price_columns = {"As At Date", price_field}
    if not required_price_columns.issubset(unit_price_history.columns):
        raise ConnectorValidationError("GSFM unit price history is missing required columns.")

    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(unit_price_history["As At Date"], format="%d-%m-%Y", errors="coerce"),
            "nav": _to_float(unit_price_history[price_field]),
        }
    ).dropna(subset=["date", "nav"])
    if prices.empty:
        raise ConnectorValidationError("GSFM unit price history did not contain any usable rows.")

    if distribution_history.empty:
        return prices, pd.DataFrame(columns=["date", "distribution"])

    cpu_column = next(
        (column for column in distribution_history.columns if str(column).strip().startswith("Distribution CPU")),
        None,
    )
    required_distribution_columns = {"Period To", ex_price_field}
    if cpu_column is None or not required_distribution_columns.issubset(distribution_history.columns):
        raise ConnectorValidationError("GSFM distribution history is missing required columns.")

    distributions = pd.DataFrame(
        {
            "date": pd.to_datetime(distribution_history["Period To"], format="%d-%m-%Y", errors="coerce"),
            "nav": _to_float(distribution_history[ex_price_field]),
            "distribution": _to_float(distribution_history[cpu_column]) / 100.0,
        }
    ).dropna(subset=["date", "distribution"])
    distributions = distributions[distributions["distribution"] > 0.0]

    if not distributions.empty:
        ex_price_map = distributions.dropna(subset=["nav"]).set_index("date")["nav"]
        prices["nav"] = prices["date"].map(ex_price_map).fillna(prices["nav"])

    return prices, distributions.loc[:, ["date", "distribution"]]


def _parse_paradice_price_history_csv(csv_text: str, price_field: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    history = _parse_report_csv(
        csv_text,
        'Date,"App Price ($)","Nav/Mid Price ($)","Red Price ($)",DPU,"Price Type"',
    )
    required_columns = {"Date", price_field}
    if not required_columns.issubset(history.columns):
        raise ConnectorValidationError("Paradice price history is missing required columns.")

    frame = history.copy()
    frame["date"] = pd.to_datetime(frame["Date"], format="%d/%m/%Y", errors="coerce")
    frame["nav"] = _to_float(frame[price_field])
    frame["distribution"] = _to_float(frame.get("DPU", pd.Series(index=frame.index, dtype="object")))
    frame["price_type"] = frame.get("Price Type", pd.Series(index=frame.index, dtype="object")).fillna("").astype(str).str.strip().str.upper()
    frame = frame.dropna(subset=["date", "nav"])

    price_rows: list[dict[str, object]] = []
    distribution_rows: list[dict[str, object]] = []

    for date, group in frame.groupby("date", sort=True):
        ex_group = group[(group["distribution"].fillna(0.0) != 0.0) | (group["price_type"] == "EX")]
        if not ex_group.empty:
            ex_row = ex_group.iloc[-1]
            price_rows.append({"date": date, "nav": ex_row["nav"]})
            distribution = float(ex_row["distribution"]) if pd.notna(ex_row["distribution"]) else 0.0
            if distribution != 0.0:
                distribution_rows.append({"date": date, "distribution": distribution})
            continue

        latest_row = group.iloc[-1]
        price_rows.append({"date": date, "nav": latest_row["nav"]})

    return pd.DataFrame(price_rows), pd.DataFrame(distribution_rows)


def _parse_chester_sheet_date(value: object) -> pd.Timestamp:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NaT
    return pd.to_datetime(str(value).strip(), errors="coerce", dayfirst=True)


def _build_chester_price_and_distribution_frames(
    history_frame: pd.DataFrame,
    price_field: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required_columns = {"PriceDt", price_field}
    if not required_columns.issubset(history_frame.columns):
        raise ConnectorValidationError("Chester unit price history is missing required columns.")

    frame = history_frame.copy()
    frame["date"] = frame["PriceDt"].map(_parse_chester_sheet_date)
    frame = frame.dropna(subset=["date"])
    frame["nav"] = _to_float(frame[price_field])
    frame["distribution"] = _to_float(frame.get("Dist", pd.Series(index=frame.index, dtype="object")))
    frame = frame.dropna(subset=["nav"])

    price_rows: list[dict[str, object]] = []
    distribution_rows: list[dict[str, object]] = []

    for date, group in frame.groupby("date", sort=True):
        distribution_group = group[group["distribution"].fillna(0.0) != 0.0]
        if not distribution_group.empty:
            ex_row = distribution_group.iloc[-1]
            price_rows.append({"date": date, "nav": ex_row["nav"]})
            distribution_rows.append({"date": date, "distribution": float(ex_row["distribution"])})
            continue

        latest_row = group.iloc[-1]
        price_rows.append({"date": date, "nav": latest_row["nav"]})

    return pd.DataFrame(price_rows), pd.DataFrame(distribution_rows)


def _parse_eqt_historical_prices_page(page_html: str, fund_id: str, price_field: str) -> pd.DataFrame:
    if price_field not in {"buy", "sell", "nav"}:
        raise ConnectorValidationError(f"Unsupported EQT price field '{price_field}'.")

    match = re.search(r'\\"data\\":\[(.*?)\],\\"pageSize\\"', page_html, flags=re.S)
    if not match:
        raise ConnectorValidationError("Could not find embedded EQT historical price data.")

    try:
        rows = json.loads(("[" + match.group(1) + "]").replace('\\"', '"'))
    except json.JSONDecodeError as exc:
        raise ConnectorValidationError("Could not decode embedded EQT historical price data.") from exc

    filtered_rows = [row for row in rows if str(row.get("fundID", "")).casefold() == str(fund_id).casefold()]
    if not filtered_rows:
        raise ConnectorValidationError(f"No EQT historical prices found for fund '{fund_id}'.")

    prices = pd.DataFrame(
        {
            "date": pd.to_datetime([row.get("priceDate") for row in filtered_rows], errors="coerce", utc=True),
            "nav": pd.to_numeric([row.get(price_field) for row in filtered_rows], errors="coerce"),
        }
    ).dropna(subset=["date", "nav"])
    prices["date"] = prices["date"].dt.tz_convert(None)
    if prices.empty:
        raise ConnectorValidationError(f"EQT historical prices for fund '{fund_id}' are empty.")
    return prices


def _extract_smallco_current_price(
    page_html: str,
    today: pd.Timestamp | None = None,
) -> pd.DataFrame:
    date_match = re.search(
        r"<tspan[^>]*>(\d{1,2})</tspan>.*?<tspan[^>]*>([A-Za-z]{3})</tspan>.*?Last unit price date",
        page_html,
        re.S,
    )
    exit_match = re.search(
        r"\$([0-9]+\.[0-9]+)\s*</p>\s*<p class=\"text-secondary fw-bold\"><span class=\"text-uppercase\">Exit Price",
        page_html,
        re.S,
    )
    if not date_match or not exit_match:
        return pd.DataFrame(columns=["date", "nav"])

    reference_today = (today or pd.Timestamp.today()).normalize()
    day = int(date_match.group(1))
    month = pd.Timestamp(f"2000-{date_match.group(2)}-01").month
    parsed_date = pd.Timestamp(year=reference_today.year, month=month, day=day)
    if parsed_date > reference_today + pd.Timedelta(days=7):
        parsed_date -= pd.DateOffset(years=1)

    return pd.DataFrame(
        {
            "date": [parsed_date],
            "nav": [float(exit_match.group(1))],
        }
    )


def _parse_selector_unit_prices_frame(
    history_frame: pd.DataFrame,
    price_field: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required_columns = {"Date", price_field}
    if not required_columns.issubset(history_frame.columns):
        raise ConnectorValidationError("Selector unit price history is missing required columns.")

    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(history_frame["Date"], errors="coerce"),
            "nav": _to_float(history_frame[price_field]),
        }
    ).dropna(subset=["date", "nav"])

    distributions = pd.DataFrame(
        {
            "date": pd.to_datetime(history_frame["Date"], errors="coerce"),
            "distribution": _to_float(history_frame.get("Distribution", pd.Series(index=history_frame.index, dtype="object"))),
        }
    ).dropna(subset=["date"])
    distributions = distributions[distributions["distribution"].fillna(0.0) != 0.0]
    return prices, distributions


def _find_selector_unit_prices_workbook_url(page_html: str, page_url: str) -> str:
    soup = BeautifulSoup(page_html, "html.parser")
    for link in soup.find_all("a", href=True):
        label = link.get_text(" ", strip=True).casefold()
        href = str(link["href"]).strip()
        if "unit prices spreadsheet" in label and href.lower().split("?", 1)[0].endswith(".xlsx"):
            return urljoin(page_url, href)

    raise ConnectorValidationError("Selector unit price workbook link was not found on the source page.")


def _build_allan_gray_fact_sheet_candidates(page_html: str, share_class: str) -> list[str]:
    normalized_share_class = str(share_class).strip().upper()
    pdf_urls = re.findall(r"https://[^\"'\s]+\.pdf", page_html, flags=re.I)
    direct_matches = [url for url in pdf_urls if f"Class-{normalized_share_class}" in url or f"Class%20{normalized_share_class}" in url]
    if direct_matches:
        fact_sheet_matches = [
            url
            for url in direct_matches
            if "fact-sheet" in url.casefold() and "equity-fund" in url.casefold()
        ]
        ordered_matches: list[str] = []
        for candidate in [*fact_sheet_matches, *direct_matches]:
            if candidate not in ordered_matches:
                ordered_matches.append(candidate)
        return ordered_matches

    class_a_url = next((url for url in pdf_urls if "AGA-Equity-Fund-Class-A" in url and "Fact-Sheet" in url), None)
    if not class_a_url:
        raise ConnectorValidationError("Could not find Allan Gray equity fact sheet links on the source page.")

    transformed = (
        class_a_url.replace("AGA-Equity-Fund-Class-A", f"AGA-Equity-Fund-Class-{normalized_share_class}")
        .replace("Class-A", f"Class-{normalized_share_class}")
        .replace("Class%20A", f"Class%20{normalized_share_class}")
    )

    period_match = re.search(
        r"-(January|February|March|April|May|June|July|August|September|October|November|December)-(\d{4})\.pdf$",
        transformed,
        flags=re.I,
    )
    if not period_match:
        return [transformed]

    period = pd.Timestamp(f"01 {period_match.group(1)} {period_match.group(2)}")
    token = f"{period_match.group(1)}-{period_match.group(2)}"
    candidates: list[str] = []
    for months_back in range(0, 7):
        candidate_period = period - pd.DateOffset(months=months_back)
        candidate_token = f"{candidate_period:%B-%Y}"
        candidate = transformed.replace(token, candidate_token)
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _fetch_allan_gray_fact_sheet_text(fact_sheet_index_url: str, share_class: str) -> str:
    scraper = _create_cloudscraper_session()
    cached_page_html = _ALLAN_GRAY_FACT_SHEET_INDEX_CACHE.get(fact_sheet_index_url)
    if cached_page_html is None:
        page_response = scraper.get(fact_sheet_index_url, timeout=20)
        page_response.raise_for_status()
        cached_page_html = page_response.text
        _ALLAN_GRAY_FACT_SHEET_INDEX_CACHE[fact_sheet_index_url] = cached_page_html

    for candidate_url in _build_allan_gray_fact_sheet_candidates(cached_page_html, share_class):
        try:
            response = scraper.get(candidate_url, timeout=30)
            response.raise_for_status()
        except Exception:  # noqa: BLE001
            continue

        if "pdf" not in (response.headers.get("content-type", "").lower()):
            continue
        return _extract_pdf_text(response.content)

    raise ConnectorValidationError(f"Could not fetch an Allan Gray Class {share_class} fact sheet PDF.")


def _parse_allan_gray_fact_sheet_distributions(pdf_text: str) -> pd.DataFrame:
    matches = re.findall(
        r"(30 June \d{4})\s+([0-9]+\.[0-9]+)\s+[0-9]+\.[0-9]+%",
        pdf_text,
        flags=re.I,
    )
    if not matches:
        raise ConnectorValidationError("Could not parse Allan Gray distribution rows from the fact sheet.")

    return pd.DataFrame(
        {
            "date": pd.to_datetime([date_text for date_text, _ in matches], format="%d %B %Y", errors="coerce"),
            "distribution": [float(cpu_text) / 100.0 for _, cpu_text in matches],
        }
    ).dropna(subset=["date"])


def _parse_allan_gray_fact_sheet_latest_price(pdf_text: str, price_field: str) -> pd.DataFrame:
    normalized_price_field = str(price_field).strip().casefold()
    if normalized_price_field not in {"buy", "sell", "nav"}:
        raise ConnectorValidationError(f"Unsupported Allan Gray fact sheet price field '{price_field}'.")

    date_match = re.search(r"FUND FACT SHEET\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})", pdf_text, flags=re.I)
    nav_match = re.search(r"Price\s+\(net asset value\)\s+AUD\s+([0-9]+(?:\.[0-9]+)?)", pdf_text, flags=re.I)
    if not date_match or not nav_match:
        raise ConnectorValidationError("Could not parse Allan Gray fact sheet date and NAV.")

    nav_value = float(nav_match.group(1))
    price_value = nav_value
    if normalized_price_field in {"buy", "sell"}:
        spread_match = re.search(
            r"Buy/sell spread\s+([+-]?[0-9]+(?:\.[0-9]+)?)\s*/\s*([+-]?[0-9]+(?:\.[0-9]+)?)%",
            pdf_text,
            flags=re.I,
        )
        if not spread_match:
            raise ConnectorValidationError("Could not parse Allan Gray fact sheet buy/sell spread.")
        buy_spread = float(spread_match.group(1)) / 100.0
        sell_spread = float(spread_match.group(2)) / 100.0
        price_value = nav_value * (1 + (buy_spread if normalized_price_field == "buy" else sell_spread))

    return pd.DataFrame(
        {
            "date": [pd.to_datetime(date_match.group(1), errors="coerce")],
            "nav": [price_value],
        }
    ).dropna(subset=["date", "nav"])


def _fetch_feprecision_fund_info(session: requests.Session, fund_config: dict) -> dict:
    fund_options_url = fund_config["fund_options_url"]
    response = _get_with_retry(session, fund_options_url, timeout=10)
    payload = response.json()
    fund_info = payload.get("FundInfo") or []

    citi_code = fund_config.get("citi_code")
    if citi_code:
        for entry in fund_info:
            if entry["Common"]["CitiCode"] == citi_code:
                return entry

    target_name = fund_config.get("fund_lookup_name") or fund_config.get("name", "")
    matches = [entry for entry in fund_info if target_name.casefold() in entry["Common"]["Name"].casefold()]
    if not matches:
        raise ConnectorValidationError(f"No FE fund metadata found for '{target_name}'.")
    return matches[0]


def _fetch_feprecision_history(
    session: requests.Session,
    fund_config: dict,
    endpoint: str,
    payload: dict,
) -> list[dict]:
    endpoint_url = f"{fund_config['download_tool_url'].rstrip('/')}/{endpoint}"
    response = _get_with_retry(
        session,
        endpoint_url,
        params={"jsonString": json.dumps(payload)},
        timeout=20,
        attempts=2,
    )
    response.raise_for_status()
    return response.json().get("DataList") or []


def _parse_hyperion_distribution_period_label(value: object) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None

    match = re.search(r"Distn Components for (.+)", text)
    if match:
        parsed = pd.to_datetime(match.group(1).strip(), errors="coerce")
        if pd.isna(parsed):
            return None
        return (parsed + pd.offsets.MonthEnd(0)).normalize()

    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.normalize()


def _parse_hyperion_distribution_sheet(sheet: pd.DataFrame) -> pd.DataFrame:
    if sheet.empty:
        return pd.DataFrame(columns=["date", "distribution"])

    if str(sheet.iloc[0, 0]).strip().upper() == "APIR":
        labels = sheet.iloc[:, 0].astype(str).str.strip()
        cash_rows = labels[labels == "Total Cash Distribution"]
        if cash_rows.empty:
            return pd.DataFrame(columns=["date", "distribution"])

        cash_row_index = cash_rows.index[0]
        rows = []
        for column_index in range(1, sheet.shape[1]):
            period_date = _parse_hyperion_distribution_period_label(sheet.iloc[1, column_index])
            if period_date is None:
                continue
            amount = pd.to_numeric(sheet.iloc[cash_row_index, column_index], errors="coerce")
            if pd.isna(amount) or float(amount) == 0.0:
                continue
            rows.append({"date": period_date, "distribution": float(amount) / 100.0})
        return pd.DataFrame(rows)

    rows = []
    for column_index in range(sheet.shape[1]):
        period_date = _parse_hyperion_distribution_period_label(sheet.iloc[0, column_index])
        if period_date is None:
            continue
        cash_labels = sheet.iloc[:, column_index].astype(str).str.strip()
        cash_rows = cash_labels[cash_labels == "Total Cash Distribution"]
        if cash_rows.empty or column_index + 1 >= sheet.shape[1]:
            continue
        amount = pd.to_numeric(sheet.iloc[cash_rows.index[0], column_index + 1], errors="coerce")
        if pd.isna(amount) or float(amount) == 0.0:
            continue
        rows.append({"date": period_date, "distribution": float(amount) / 100.0})
    return pd.DataFrame(rows)


def _fetch_hyperion_distributions(
    session: requests.Session,
    media_api_url: str,
    sheet_name: str,
) -> pd.DataFrame:
    response = _get_with_retry(
        session,
        media_api_url,
        timeout=20,
        params={"search": "distribution breakdown", "per_page": "100"},
    )
    assets = response.json()

    distribution_frames: list[pd.DataFrame] = []
    for asset in assets:
        source_url = str(asset.get("source_url") or "")
        if not source_url.lower().endswith(".xlsx"):
            continue

        workbook_response = _get_with_retry(session, source_url, timeout=20)
        workbook = pd.ExcelFile(io.BytesIO(workbook_response.content))
        if sheet_name not in workbook.sheet_names:
            continue

        parsed = _parse_hyperion_distribution_sheet(workbook.parse(sheet_name))
        if not parsed.empty:
            distribution_frames.append(parsed)

    if not distribution_frames:
        return pd.DataFrame(columns=["date", "distribution"])

    combined = pd.concat(distribution_frames, ignore_index=True)
    combined = combined.dropna(subset=["date"])
    combined["date"] = pd.to_datetime(combined["date"], errors="coerce")
    combined["distribution"] = pd.to_numeric(combined["distribution"], errors="coerce")
    combined = combined.dropna(subset=["date", "distribution"])
    combined = combined.sort_values("date")
    return combined.groupby("date", as_index=False)["distribution"].last()


def _build_feprecision_model(fund_config: dict, citi_code: str) -> dict:
    return {
        "GrsProjectId": str(fund_config["grs_project_id"]),
        "ProjectName": fund_config["project_name"],
        "ToolId": int(fund_config.get("tool_id", 16)),
        "LanguageId": str(fund_config.get("language_id", 1)),
        "LanguageCode": fund_config.get("language_code", "en-au"),
        "FSIexclCT": "",
        "forSaleIn": "",
        "FilteringOptions": {"CitiCode": citi_code},
    }


def _scrape_feprecision_prices(
    fund_config: dict,
    fund_info: dict,
    session: requests.Session,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    common = fund_info["Common"]
    price_meta = fund_info["Price"]
    price_component = fund_config.get("price_component", "Bid")
    model = _build_feprecision_model(fund_config, common["CitiCode"])
    filters = {
        "CitiCode": common["CitiCode"],
        "Universe": (common.get("SectorClassCode") or "").split(":")[0] or None,
        "TypeCode": common["TypeCode"],
        "BaseCurrency": price_meta.get("Currency_UnitLevel") or "AUD",
        "PriceType": price_meta.get("PriceType") or 2,
        "TimePeriod": None,
        "StartDate": _json_date(start_date),
        "EndDate": _json_date(end_date),
    }
    payload = {**model, "UnitHistoryFilters": filters}
    rows = _fetch_feprecision_history(session, fund_config, "GetPriceHistory", payload)

    data = []
    for row in rows:
        price = row.get("Price") or {}
        component = price.get(price_component) or price.get("Price") or {}
        amount = component.get("Amount")
        price_date = price.get("PriceDate")
        if amount is None or price_date is None:
            continue
        data.append({"date": pd.to_datetime(price_date, errors="coerce"), "nav": amount})
    return pd.DataFrame(data)


def _scrape_feprecision_dividends(
    fund_config: dict,
    fund_info: dict,
    session: requests.Session,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    common = fund_info["Common"]
    price_meta = fund_info["Price"]
    model = _build_feprecision_model(fund_config, common["CitiCode"])
    filters = {
        "TypeCode": common["TypeCode"],
        "BaseCurrency": price_meta.get("Currency_UnitLevel") or "AUD",
        "PriceType": price_meta.get("PriceType") or 2,
        "TimePeriod": None,
        "StartDate": _json_date(start_date),
        "EndDate": _json_date(end_date),
    }
    payload = {**model, "UnitHistoryFilters": filters}
    rows = _fetch_feprecision_history(session, fund_config, "GetDividendHistory", payload)

    field = fund_config.get("dividend_field", "NetDividend")
    data = []
    for row in rows:
        dividend = row.get("Dividend") or {}
        amount = dividend.get(field)
        xd_date = dividend.get("XDDate")
        if amount in {None, 0} or xd_date is None:
            continue
        data.append({"date": pd.to_datetime(xd_date, errors="coerce"), "distribution": amount})
    return pd.DataFrame(data)


@register_scraper("solaris_wpdatatable")
def scrape_solaris_wpdatatable(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    if not url:
        raise ConnectorValidationError("solaris_wpdatatable scraper requires 'url'.")

    response = _get_with_retry(session, url, timeout=20)
    price_table = _extract_wpdatatable_rows(response.text, fund_config.get("price_table_desc_id", "table_2_desc"))
    distribution_table = _extract_wpdatatable_rows(
        response.text,
        fund_config.get("distribution_table_desc_id", "table_3_desc"),
    )

    prices, distributions = _build_solaris_price_and_distribution_frames(
        price_table,
        distribution_table,
        fund_config.get("price_field", "Exit Price"),
        fund_config.get("ex_price_field", "Ex Exit Price"),
        fund_config.get("distribution_field", "Cash Portion"),
    )
    return _merge_prices_and_distributions(prices, distributions, start_date, end_date)


@register_scraper("example_manager")
def scrape_example(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    if not url:
        raise ConnectorValidationError("example_manager requires a URL.")

    frame = fetch_tabular_url(url, session=session)
    column_map = {column.lower().strip(): column for column in frame.columns}

    date_column = column_map.get("date")
    nav_column = column_map.get("nav") or column_map.get("unit price")
    distribution_column = column_map.get("distribution")

    if not date_column or not nav_column:
        raise ConnectorValidationError("Scraped table must include date and nav columns.")

    result = pd.DataFrame({"date": frame[date_column], "nav": frame[nav_column]})
    if distribution_column:
        result["distribution"] = frame[distribution_column]

    return _merge_prices_and_distributions(
        result[["date", "nav"]],
        result[["date", "distribution"]] if "distribution" in result.columns else pd.DataFrame(columns=["date", "distribution"]),
        start_date,
        end_date,
    )


@register_scraper("bennelong_sheet_file")
def scrape_bennelong_sheet_file(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    sheet_file_id = fund_config.get("sheet_file_id")
    if not sheet_file_id:
        raise ConnectorValidationError("bennelong_sheet_file scraper requires 'sheet_file_id'.")

    sheet_text = _download_bennelong_history_sheet(session, str(sheet_file_id), start_date, end_date)
    parsed = _parse_bennelong_history_sheet(sheet_text, fund_config.get("price_field", "Redemption"))
    normalized = BaseConnector.normalize_frame(parsed)
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    return normalized.loc[(normalized.index >= start) & (normalized.index <= end)]


@register_scraper("fidelity_csv")
def scrape_fidelity_csv(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    fund_code = fund_config.get("fund_code")
    if not fund_code:
        raise ConnectorValidationError("fidelity_csv scraper requires 'fund_code'.")

    prices_url = f"https://www.fidelity.com.au/plugins/FidelityData/downloadFundCSV.cfm?fundcd={fund_code}"
    distributions_url = f"https://www.fidelity.com.au/plugins/FidelityData/downloadFundDistribCSVun.cfm?fundcd={fund_code}"

    price_response = _get_with_retry(session, prices_url, timeout=10)
    price_raw = pd.read_csv(io.BytesIO(price_response.content))

    nav_column = fund_config.get("price_field", "Redemption price")
    if nav_column not in price_raw.columns:
        raise ConnectorValidationError(f"Fidelity price data missing '{nav_column}' column.")

    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(price_raw["Date"], format="%d/%m/%Y", errors="coerce"),
            "nav": _to_float(price_raw[nav_column]),
        }
    )

    distribution_response = _get_with_retry(session, distributions_url, timeout=10)
    distribution_raw = pd.read_csv(io.BytesIO(distribution_response.content))
    distributions = pd.DataFrame(
        {
            "date": pd.to_datetime(distribution_raw["Effective Date"].astype(str), format="%Y%m%d", errors="coerce"),
            "distribution": _to_float(distribution_raw["Distribution (CPU)"]) / 100.0,
        }
    ).dropna(subset=["date"])

    return _merge_prices_and_distributions(
        prices,
        distributions,
        start_date,
        end_date,
        distribution_timing=fund_config.get("distribution_timing", "same_date"),
    )


@register_scraper("airlie_downloads")
def scrape_airlie_downloads(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    if not url:
        raise ConnectorValidationError("airlie_downloads scraper requires 'url'.")

    fund_class = fund_config.get("fund_class", "D")
    price_url = _append_raw_query(url, f"downloadPriceHistory&fC={fund_class}")
    price_response = _get_with_retry(session, price_url, timeout=10)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        workbook = pd.ExcelFile(io.BytesIO(price_response.content))
        price_raw = pd.concat([workbook.parse(sheet_name) for sheet_name in workbook.sheet_names], ignore_index=True)

    nav_column = fund_config.get("price_field", "Exit")
    prices, distributions = _build_airlie_price_and_distribution_frames(price_raw, nav_column)

    return _merge_prices_and_distributions(prices, distributions, start_date, end_date)


@register_scraper("channelcapital_google_csv")
def scrape_channelcapital_google_csv(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    unit_prices_url = fund_config.get("unit_prices_url") or url
    if not unit_prices_url:
        raise ConnectorValidationError("channelcapital_google_csv scraper requires 'unit_prices_url' or 'url'.")

    response = _get_with_retry(session, unit_prices_url, timeout=15)
    prices, distributions = _parse_channelcapital_unit_price_csv(
        response.text,
        price_field=fund_config.get("price_field", "Redemption Price ($)"),
        distribution_field=fund_config.get("distribution_field", "Distribution ($)"),
    )
    prices, distributions = _apply_configured_price_scaling(prices, distributions, fund_config)

    return _merge_prices_and_distributions(
        prices,
        distributions,
        start_date,
        end_date,
        distribution_timing=fund_config.get("distribution_timing", "same_date"),
    )


@register_scraper("firetrail_wpdatatable")
def scrape_firetrail_wpdatatable(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    if not url:
        raise ConnectorValidationError("firetrail_wpdatatable scraper requires 'url'.")

    response = _get_with_retry(session, url, timeout=10)
    table = _extract_wpdatatable_rows(response.text, fund_config.get("table_desc_id", "table_2_desc"))

    nav_column = fund_config.get("price_field", "Exit Price")
    distribution_column = fund_config.get("distribution_field", "Distribution")
    if nav_column not in table.columns:
        raise ConnectorValidationError(f"Firetrail unit price table missing '{nav_column}' column.")

    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(table["Date"], format="%d/%m/%Y", errors="coerce"),
            "nav": _to_float(table[nav_column]),
        }
    )
    distributions = pd.DataFrame(
        {
            "date": pd.to_datetime(table["Date"], format="%d/%m/%Y", errors="coerce"),
            "distribution": _to_float(table.get(distribution_column, pd.Series(index=table.index, dtype="object"))),
        }
    )
    prices, distributions = _apply_configured_price_scaling(prices, distributions, fund_config)

    return _merge_prices_and_distributions(
        prices,
        distributions,
        start_date,
        end_date,
        distribution_timing=fund_config.get("distribution_timing", "same_date"),
    )


@register_scraper("feprecision_downloadtool")
def scrape_feprecision_downloadtool(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    fund_info = _fetch_feprecision_fund_info(session, fund_config)
    prices = _scrape_feprecision_prices(fund_config, fund_info, session, start_date, end_date)
    distributions = _scrape_feprecision_dividends(fund_config, fund_info, session, start_date, end_date)
    return _merge_prices_and_distributions(prices, distributions, start_date, end_date)


@register_scraper("ausbil_fe_prices")
def scrape_ausbil_fe_prices(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    fund_info = _fetch_feprecision_fund_info(session, fund_config)
    prices = _scrape_feprecision_prices(fund_config, fund_info, session, start_date, end_date)

    page_url = fund_config.get("distribution_page_url")
    if not page_url:
        raise ConnectorValidationError("ausbil_fe_prices scraper requires 'distribution_page_url'.")
    page_response = _get_with_retry(session, page_url, timeout=10)
    dist_raw = _find_accordion_distribution_table(page_response.text, fund_config.get("distribution_fund_name", fund_config["name"]))
    distributions = pd.DataFrame(
        {
            "date": pd.to_datetime(dist_raw["date"], format="%d %b %Y", errors="coerce"),
            "distribution": _to_float(dist_raw["distribution"]) / 100.0,
        }
    ).dropna(subset=["date"])

    return _merge_prices_and_distributions(prices, distributions, start_date, end_date)


@register_scraper("iml_ajax_exports")
def scrape_iml_ajax_exports(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    portfolio_code = fund_config.get("portfolio_code")
    if not portfolio_code:
        raise ConnectorValidationError("iml_ajax_exports scraper requires 'portfolio_code'.")

    ajax_url = fund_config.get("ajax_url", "https://iml.com.au/wp-admin/admin-ajax.php")
    price_csv = _fetch_iml_export_csv(session, str(portfolio_code), "ajaxHandleAllFundsUnitPriceTableDownload", ajax_url=ajax_url)
    distribution_csv = _fetch_iml_export_csv(
        session,
        str(portfolio_code),
        "ajaxHandleAllFundsDistributionDownload",
        ajax_url=ajax_url,
    )

    prices = _parse_iml_unit_price_history(price_csv, fund_config.get("price_field", "Exit"))
    distributions = _parse_iml_distribution_history(distribution_csv)
    return _merge_prices_and_distributions(
        prices,
        distributions,
        start_date,
        end_date,
        distribution_timing=fund_config.get("distribution_timing", "next_price_date"),
    )


@register_scraper("first_sentier_history_csv")
def scrape_first_sentier_history_csv(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    fund_query = fund_config.get("fund_query")
    if not fund_query:
        raise ConnectorValidationError("first_sentier_history_csv scraper requires 'fund_query'.")

    audience = str(fund_config.get("audience", "adviser"))
    history_file_path = fund_config.get("history_file_path") or _build_first_sentier_history_file_path(str(fund_query), audience)
    history_url = _build_url_with_query(
        "https://www.firstsentierinvestors.com.au/bin/cfsgam/getHistoricalPricingData",
        type="downloadPrice",
        filePath=history_file_path,
    )
    history_response = _get_with_retry(session, history_url, timeout=20)
    prices, distributions = _parse_first_sentier_history_csv(
        history_response.text,
        fund_config.get("price_field", "EXIT PRICE (AUD)"),
    )
    return _merge_prices_and_distributions(prices, distributions, start_date, end_date)


@register_scraper("cfs_historical_unit_prices")
def scrape_cfs_historical_unit_prices(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    main_group = fund_config.get("main_group")
    group_id = fund_config.get("group_id")
    product_id = fund_config.get("product_id")
    if not main_group or not group_id or not product_id:
        raise ConnectorValidationError("cfs_historical_unit_prices scraper requires main_group, group_id, and product_id.")

    history_url = fund_config.get("history_url") or _build_cfs_history_download_url(
        main_group=str(main_group),
        group_id=str(group_id),
        product_id=str(product_id),
        start_date=start_date,
        end_date=end_date,
        download_url=str(fund_config.get("download_url", "https://www.colonialfirststate.com.au/Price_Performance/Download.aspx")),
    )
    history_response = _get_with_retry(session, str(history_url), timeout=20)
    prices, distributions = _parse_cfs_history_csv(history_response.text, fund_config.get("price_field", "Exit Price"))
    return _merge_prices_and_distributions(prices, distributions, start_date, end_date)


@register_scraper("forager_google_sheet")
def scrape_forager_google_sheet(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    workbook_url = fund_config.get("unit_prices_url") or url
    if not workbook_url:
        raise ConnectorValidationError("forager_google_sheet scraper requires 'unit_prices_url'.")

    workbook_response = _get_with_retry(session, workbook_url, timeout=20)
    workbook = pd.ExcelFile(io.BytesIO(workbook_response.content))
    sheet_name = fund_config.get("sheet_name") or workbook.sheet_names[0]
    history = workbook.parse(sheet_name)

    prices, distributions = _build_forager_price_and_distribution_frames(
        history,
        fund_config.get("price_field", "Redemption Price"),
    )
    return _merge_prices_and_distributions(
        prices,
        distributions,
        start_date,
        end_date,
        distribution_timing=fund_config.get("distribution_timing", "same_date"),
    )


@register_scraper("vanguard_personal_api")
def scrape_vanguard_personal_api(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    port_id = fund_config.get("port_id")
    if not port_id:
        raise ConnectorValidationError("vanguard_personal_api scraper requires 'port_id'.")

    base_url = str(fund_config.get("api_base_url", "https://www.vanguard.com.au/personal/api")).rstrip("/")
    prices_response = _get_with_retry(session, f"{base_url}/products/personal/fund/{port_id}/prices", timeout=20)
    distributions_response = _get_with_retry(
        session,
        f"{base_url}/data/products/product-distribution/{port_id}",
        timeout=20,
    )

    prices = _parse_vanguard_price_history(prices_response.json())
    distributions = _parse_vanguard_distribution_history(distributions_response.json())
    return _merge_prices_and_distributions(
        prices,
        distributions,
        start_date,
        end_date,
        distribution_timing=fund_config.get("distribution_timing", "same_date"),
    )


@register_scraper("lazard_product_api")
def scrape_lazard_product_api(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    product_id = fund_config.get("product_id")
    share_class_id = fund_config.get("share_class_id")
    share_class_label = fund_config.get("share_class_label")
    if not product_id or not share_class_id or not share_class_label:
        raise ConnectorValidationError(
            "lazard_product_api scraper requires 'product_id', 'share_class_id', and 'share_class_label'."
        )

    api_url = _build_url_with_query(
        str(fund_config.get("api_url", "https://lazardassetmanagement.com/api/products")),
        id=str(product_id),
        type="Fund",
    )
    api_response = _get_with_retry(session, api_url, timeout=20)
    api_payload = api_response.json()
    prices = _parse_lazard_historical_nav(
        api_payload,
        str(share_class_id),
        str(fund_config.get("price_field", "withdrawalPrice")),
    )
    product = api_payload[0] if api_payload else {}
    share_class = next(
        (item for item in product.get("shareClasses", []) if str(item.get("id")) == str(share_class_id)),
        {},
    )

    pdf_urls = fund_config.get("distribution_pdf_urls") or []
    if not pdf_urls:
        raise ConnectorValidationError("lazard_product_api scraper requires 'distribution_pdf_urls'.")

    distribution_frames: list[pd.DataFrame] = []
    for pdf_url in pdf_urls:
        pdf_response = _get_with_retry(session, str(pdf_url), timeout=30)
        pdf_text = _extract_pdf_text(pdf_response.content)
        distribution_frames.append(_parse_lazard_distribution_pdf_text(pdf_text, str(share_class_label)))

    distributions = pd.concat(distribution_frames, ignore_index=True) if distribution_frames else pd.DataFrame()
    if not distributions.empty:
        distributions = (
            distributions.sort_values("date")
            .drop_duplicates(subset=["date"], keep="last")
            .reset_index(drop=True)
        )

    history = _merge_prices_and_distributions(
        prices,
        distributions,
        start_date,
        end_date,
        distribution_timing=fund_config.get("distribution_timing", "next_price_date"),
    )
    return _extend_lazard_history_with_performance_anchors(history, share_class, end_date)


@register_scraper("perpetual_family")
def scrape_perpetual_family(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    portfolio_id = fund_config.get("portfolio_id")
    fund_id = fund_config.get("fund_id")
    if not portfolio_id or not fund_id:
        raise ConnectorValidationError("perpetual_family scraper requires 'portfolio_id' and 'fund_id'.")

    prices_url = (
        f"https://www.perpetual.com.au/api/funds/unit-prices?portfolioId={portfolio_id}"
        f"&from={start_date}&to={end_date}"
    )
    price_response = _get_with_retry(session, prices_url, timeout=15)
    price_raw = pd.read_csv(io.BytesIO(price_response.content))

    nav_column = fund_config.get("price_field", "Exit Price")
    if nav_column not in price_raw.columns:
        raise ConnectorValidationError(f"Perpetual price data missing '{nav_column}' column.")

    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(price_raw["As At Date"], format="%d/%m/%y", errors="coerce"),
            "nav": _to_float(price_raw[nav_column]),
        }
    ).dropna(subset=["date"])

    distribution_url = fund_config.get("distribution_url") or f"https://www.perpetual.com.au/funds/distributions/{portfolio_id}?fund={fund_id}"
    distributions = _fetch_perpetual_distributions(session, distribution_url)
    distributions = _align_distributions_to_next_price_date(prices, distributions)

    return _merge_prices_and_distributions(prices, distributions, start_date, end_date)


@register_scraper("dnr_html_xlsx")
def scrape_dnr_html_xlsx(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    if not url:
        raise ConnectorValidationError("dnr_html_xlsx scraper requires 'url'.")

    scraper = _create_cloudscraper_session()
    page_response = scraper.get(url, timeout=30)
    page_response.raise_for_status()
    tables = _read_html_tables(page_response.text)

    distribution_table = next(
        (
            table
            for table in tables
            if not table.empty and str(table.columns[0]).strip().casefold() == "financial year(s)"
        ),
        None,
    )
    if distribution_table is None:
        raise ConnectorValidationError("DNR distribution history table was not found on the source page.")

    history_xlsx_url = fund_config.get("history_xlsx_url")
    if not history_xlsx_url:
        soup = BeautifulSoup(page_response.text, "html.parser")
        history_link = next(
            (
                link.get("href")
                for link in soup.find_all("a", href=True)
                if "historical unit prices" in link.get_text(" ", strip=True).casefold()
            ),
            None,
        )
        if not history_link:
            raise ConnectorValidationError("DNR historical unit price workbook link was not found on the source page.")
        history_xlsx_url = history_link

    history_response = scraper.get(str(history_xlsx_url), timeout=30)
    history_response.raise_for_status()
    history_frame = pd.read_excel(io.BytesIO(history_response.content))

    prices = _parse_dnr_unit_price_history_frame(history_frame, fund_config.get("price_field", "Withdrawal Price"))
    distributions = _parse_dnr_distribution_history_table(distribution_table)
    return _merge_prices_and_distributions(
        prices,
        distributions,
        start_date,
        end_date,
        distribution_timing=fund_config.get("distribution_timing", "next_price_date"),
    )


@register_scraper("katana_html")
def scrape_katana_html(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    if not url:
        raise ConnectorValidationError("katana_html scraper requires 'url'.")

    response = _get_with_retry(session, url, timeout=20)
    page_html = response.text

    prices = _parse_katana_monthly_prices(page_html)
    current_price = _parse_katana_daily_price(page_html)
    if not current_price.empty:
        prices = pd.concat([prices, current_price], ignore_index=True)

    distributions = _parse_katana_annual_distributions(page_html)
    return _merge_prices_and_distributions(
        prices,
        distributions,
        start_date,
        end_date,
        distribution_timing=fund_config.get("distribution_timing", "next_price_date"),
    )


@register_scraper("allan_gray_eqt")
def scrape_allan_gray_eqt(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    if not url:
        raise ConnectorValidationError("allan_gray_eqt scraper requires 'url'.")

    fund_id = fund_config.get("fund_id")
    if not fund_id:
        raise ConnectorValidationError("allan_gray_eqt scraper requires 'fund_id'.")

    response = _get_with_retry(session, url, timeout=20)
    price_field = fund_config.get("price_field", "sell")
    prices = _parse_eqt_historical_prices_page(response.text, str(fund_id), price_field)

    fact_sheet_index_url = fund_config.get("fact_sheet_index_url")
    if not fact_sheet_index_url:
        raise ConnectorValidationError("allan_gray_eqt scraper requires 'fact_sheet_index_url'.")
    pdf_text = _fetch_allan_gray_fact_sheet_text(fact_sheet_index_url, str(fund_config.get("share_class", "B")))
    distributions = _parse_allan_gray_fact_sheet_distributions(pdf_text)
    latest_price = _parse_allan_gray_fact_sheet_latest_price(pdf_text, price_field)
    if not latest_price.empty:
        prices = (
            pd.concat([prices, latest_price], ignore_index=True)
            .sort_values("date")
            .drop_duplicates(subset=["date"], keep="last")
            .reset_index(drop=True)
        )

    return _merge_prices_and_distributions(
        prices,
        distributions,
        start_date,
        end_date,
        distribution_timing=fund_config.get("distribution_timing", "next_price_date"),
    )


@register_scraper("pendal_history_csv")
def scrape_pendal_history_csv(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    product_id = fund_config.get("product_id")
    if not product_id:
        raise ConnectorValidationError("pendal_history_csv scraper requires 'product_id'.")

    prices_url = _build_pendal_history_url(product_id, start_date, end_date, "unit-price")
    price_response = _get_with_retry(session, prices_url, timeout=15)
    price_raw = _parse_report_csv(price_response.text, 'Date,"Entry Price","Exit Price"')

    nav_column = fund_config.get("price_field", "Exit Price")
    if nav_column not in price_raw.columns:
        raise ConnectorValidationError(f"Pendal price data missing '{nav_column}' column.")

    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(price_raw["Date"], format="%d-%b-%Y", errors="coerce"),
            "nav": _to_float(price_raw[nav_column]),
        }
    ).dropna(subset=["date"])

    distributions_url = _build_pendal_history_url(product_id, start_date, end_date, "distribution")
    distribution_response = _get_with_retry(session, distributions_url, timeout=15)
    distribution_raw = _parse_report_csv(
        distribution_response.text,
        '"Distribution Date","Distribution Amount (cpu)","Reinvestment Unit Price ($)"',
    )
    distributions = pd.DataFrame(
        {
            "date": pd.to_datetime(distribution_raw["Distribution Date"], format="%d-%b-%Y", errors="coerce"),
            "distribution": _to_float(distribution_raw["Distribution Amount (cpu)"]) / 100.0,
        }
    ).dropna(subset=["date"])
    distributions = distributions[distributions["distribution"] != 0]
    distributions = _align_distributions_to_next_price_date(prices, distributions)

    return _merge_prices_and_distributions(prices, distributions, start_date, end_date)


@register_scraper("smallco_monthly_history")
def scrape_smallco_monthly_history(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    if not url:
        raise ConnectorValidationError("smallco_monthly_history scraper requires 'url'.")

    response = _get_with_retry(session, url, timeout=15)
    tables = _read_html_tables(response.text)
    prices, distributions = _build_smallco_price_and_distribution_frames(
        tables,
        fund_config.get("price_field", "Exit Price**"),
    )
    if fund_config.get("price_field", "Exit Price**") == "Exit Price**":
        current_price = _extract_smallco_current_price(response.text)
        if not current_price.empty:
            prices = pd.concat([prices, current_price], ignore_index=True)
    return _merge_prices_and_distributions(prices, distributions, start_date, end_date)


@register_scraper("gsfm_fund_tables")
def scrape_gsfm_fund_tables(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    unit_prices_url = fund_config.get("unit_prices_url")
    distribution_url = fund_config.get("distribution_url")
    if not unit_prices_url or not distribution_url:
        raise ConnectorValidationError("gsfm_fund_tables scraper requires 'unit_prices_url' and 'distribution_url'.")

    price_field = fund_config.get("price_field", "NAV Price")
    ex_price_field = fund_config.get("ex_price_field", "Valuation price on ex-date ($)")
    history_url = _build_url_with_query(
        str(unit_prices_url),
        start_date=pd.Timestamp(start_date).strftime("%d-%m-%Y"),
        end_date=pd.Timestamp(end_date).strftime("%d-%m-%Y"),
    )

    unit_prices_response = _get_with_retry(session, history_url, timeout=20)
    unit_price_tables = _read_html_tables(unit_prices_response.text)
    unit_price_table = next(
        (
            table
            for table in unit_price_tables
            if {"As At Date", price_field}.issubset(table.columns)
        ),
        None,
    )
    if unit_price_table is None:
        raise ConnectorValidationError("GSFM unit price table was not found on the source page.")

    distribution_response = _get_with_retry(session, str(distribution_url), timeout=20)
    distribution_tables = _read_html_tables(distribution_response.text)
    distribution_table = next((table for table in distribution_tables if "Period To" in table.columns), None)
    if distribution_table is None:
        raise ConnectorValidationError("GSFM distribution table was not found on the source page.")

    prices, distributions = _build_gsfm_price_and_distribution_frames(
        unit_price_table,
        distribution_table,
        price_field,
        ex_price_field,
    )
    return _merge_prices_and_distributions(prices, distributions, start_date, end_date)


@register_scraper("macquarie_public_json")
def scrape_macquarie_public_json(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    apir_code = fund_config.get("apir_code")
    if not apir_code:
        raise ConnectorValidationError("macquarie_public_json scraper requires 'apir_code'.")

    metadata_url = fund_config.get(
        "unit_prices_meta_url",
        "https://www.macquarie.com/assets/mam/au_wealth/data/meta/unit_prices.json",
    )
    assets_base_url = str(fund_config.get("assets_base_url", "https://www.macquarie.com/assets/mam"))

    metadata_response = _get_with_retry(session, str(metadata_url), timeout=20)
    history_url = _build_macquarie_history_url(metadata_response.json(), str(apir_code), assets_base_url)

    history_response = _get_with_retry(session, history_url, timeout=20)
    history = _parse_macquarie_historical_price_csv(
        history_response.text,
        fund_config.get("price_field", "Redemption price"),
    )
    return _merge_prices_and_distributions(
        history[["date", "nav"]],
        history[["date", "distribution"]],
        start_date,
        end_date,
    )


@register_scraper("ecp_downloads")
def scrape_ecp_downloads(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    download_code = fund_config.get("download_code")
    if not download_code:
        raise ConnectorValidationError("ecp_downloads scraper requires 'download_code'.")

    nav_url = fund_config.get("nav_url") or f"https://ecpam.com/download/nav/{download_code}"
    distribution_url = fund_config.get("distribution_url") or f"https://ecpam.com/download/distributions/{download_code}"

    nav_response = _get_with_retry(session, nav_url, timeout=15)
    nav_raw = pd.read_csv(io.BytesIO(nav_response.content))
    nav_column = fund_config.get("price_field", "ex_nav_price")
    if nav_column not in nav_raw.columns:
        raise ConnectorValidationError(f"ECP NAV history missing '{nav_column}' column.")

    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(nav_raw["effective_date"], errors="coerce"),
            "nav": _to_float(nav_raw[nav_column]),
        }
    ).dropna(subset=["date"])

    distribution_response = _get_with_retry(session, distribution_url, timeout=15)
    distribution_raw = pd.read_csv(io.BytesIO(distribution_response.content))
    distributions = pd.DataFrame(
        {
            "date": pd.to_datetime(distribution_raw["date"], errors="coerce"),
            "distribution": _to_float(distribution_raw["distribution"]) / 100.0,
        }
    ).dropna(subset=["date"])
    distributions = distributions[distributions["distribution"] != 0]

    return _merge_prices_and_distributions(prices, distributions, start_date, end_date)


@register_scraper("paradice_price_history_csv")
def scrape_paradice_price_history_csv(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    history_url = fund_config.get("history_url")
    if not history_url:
        raise ConnectorValidationError("paradice_price_history_csv scraper requires 'history_url'.")

    response = _get_with_retry(session, str(history_url), timeout=20)
    prices, distributions = _parse_paradice_price_history_csv(
        response.text,
        fund_config.get("price_field", "Red Price ($)"),
    )
    return _merge_prices_and_distributions(prices, distributions, start_date, end_date)


@register_scraper("chester_google_sheet")
def scrape_chester_google_sheet(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    sheet_url = fund_config.get("sheet_url") or url
    if not sheet_url:
        raise ConnectorValidationError("chester_google_sheet scraper requires 'sheet_url'.")

    history = pd.read_csv(io.BytesIO(_get_with_retry(session, sheet_url, timeout=20).content))
    prices, distributions = _build_chester_price_and_distribution_frames(history, fund_config.get("price_field", "Red"))
    return _merge_prices_and_distributions(prices, distributions, start_date, end_date)


@register_scraper("selector_unit_prices_xlsx")
def scrape_selector_unit_prices_xlsx(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    source_page_url = url or fund_config.get("source_page_url")
    if source_page_url:
        page_response = _get_with_retry(session, str(source_page_url), timeout=20)
        workbook_url = _find_selector_unit_prices_workbook_url(page_response.text, str(source_page_url))
    else:
        workbook_url = fund_config.get("unit_prices_url")
    if not workbook_url:
        raise ConnectorValidationError("selector_unit_prices_xlsx scraper requires 'url' or 'unit_prices_url'.")

    workbook_response = _get_with_retry(session, workbook_url, timeout=20)
    workbook = pd.ExcelFile(io.BytesIO(workbook_response.content))
    sheet_name = fund_config.get("sheet_name") or workbook.sheet_names[0]
    history = workbook.parse(sheet_name)
    prices, distributions = _parse_selector_unit_prices_frame(history, fund_config.get("price_field", "Exit Price"))
    return _merge_prices_and_distributions(prices, distributions, start_date, end_date)


@register_scraper("hyperion_price_csv")
def scrape_hyperion_price_csv(
    url: str,
    start_date: str,
    end_date: str,
    fund_config: dict,
    session: requests.Session,
) -> pd.DataFrame:
    prices_url = fund_config.get("prices_url") or url
    if not prices_url:
        raise ConnectorValidationError("hyperion_price_csv scraper requires 'prices_url'.")

    price_response = _get_with_retry(session, prices_url, timeout=20)
    price_raw = pd.read_csv(io.BytesIO(price_response.content))
    nav_column = fund_config.get("price_field", "Redemption Price")
    if nav_column not in price_raw.columns:
        raise ConnectorValidationError(f"Hyperion price history is missing '{nav_column}'.")

    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(price_raw["Date"], errors="coerce"),
            "nav": _to_float(price_raw[nav_column]),
        }
    ).dropna(subset=["date", "nav"])

    media_api_url = fund_config.get("distribution_media_api_url", "https://www.hyperion.com.au/wp-json/wp/v2/media")
    distributions = _fetch_hyperion_distributions(session, media_api_url, fund_config.get("distribution_sheet_name", "HAGCF"))
    return _merge_prices_and_distributions(
        prices,
        distributions,
        start_date,
        end_date,
        distribution_timing=fund_config.get("distribution_timing", "next_price_date"),
    )
