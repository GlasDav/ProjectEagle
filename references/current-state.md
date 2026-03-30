# Current State

This file is the quick onboarding reference for the live PerfSraper configuration.

## As Of March 29, 2026

- Benchmark: S&P/ASX 200 Accumulation via `^AXJT`
- Live funds: 17
- Disabled placeholders: 5
- Live source mix: 17 scraper-backed `ex_distribution` funds

## Active Invariants

- All displayed performance must be total return.
- The relative table must reconcile with the benchmark row shown in the absolute table, within normal display rounding.
- `ex_distribution` series should explicitly model distribution timing where the source does not already provide ex-price history on the distribution row.

## Recent Fixes

### Benchmark-relative Teams delivery

- The Teams card now shows the full benchmark-relative performance table rather than the absolute table.
- The benchmark row is pinned to the top of that Teams table, and the default lineup excludes the four comparison funds that duplicated broad index coverage.

### Distribution timing

- Firetrail High Conviction Fund and Fidelity Australian Equities Fund now use `distribution_timing: next_price_date`.
- This prevents distributions reported on the cum-price row from being reinvested one row too early, which previously understated returns.

### Airlie history coverage

- Airlie Australian Share Fund now reads every sheet in the historical workbook rather than only the first sheet.
- Distributions are derived from workbook rows marked `ex`, which restores the missing multi-period history and aligns the series with the manager's public data structure.

### Relative return reconciliation

- Relative returns are now calculated from the same benchmark return series shown in the absolute benchmark row.
- This keeps MTD, 3M, 6M, 12M, 3Y, and 5Y excess returns visually reconcilable from the rendered tables.

### Stale-date visibility

- Rows with delayed public source data now show their actual latest public date in the rendered label, for example `as of 2026-03-24, stale 2d`.
- This avoids reading a stale fund return as though it were calculated on the report date shown in the table title.

### New live manager sources

- Bennelong Concentrated now downloads the public Bennelong daily unit-price sheet and uses the published distribution CPU plus ex-distribution redemption price on distribution rows.
- Smallco Broadcap now reads the public Smallco monthly history tables and reconstructs ex-distribution month-end rows from the paired pre and post distribution entries.
- Chester High Conviction Fund now reads Chester's public Google Sheet and preserves the ex-price row on distribution dates instead of the same-day `CUM` row.
- Selector High Conviction Equity Fund now reads Selector's public wholesale unit-price workbook, including the embedded distribution column.
- Hyperion Australian Growth Companies Fund now combines Hyperion's public daily price CSV with distribution breakdown workbooks discovered via the public media API.
- Solaris Core Australian Equity Fund now reads Solaris' public website tables for unit prices and distributions. The publicly reachable history currently begins on `2021-10-18`, so 5Y output can remain `N/A` until Solaris publishes a longer series.
- Allan Gray Australia Equity Fund now combines the official Equity Trustees Class B historical-prices page with annual distributions parsed from the Allan Gray Class B fact sheet. The source uses `distribution_timing: next_price_date` because the published EQT distribution row is cum-distribution.

### Style metadata

- Every live fund now carries `style: value|growth|agnostic` in `config.yaml`.
- The terminal, HTML, Excel, and Teams tables all show `Style` immediately after `Fund`.
- Style is display metadata only. Ranking, summaries, sorting, and total-return calculations are unchanged.

### APIR and Morningstar investigation

- APIR remains useful as a stable identifier layer, but the public material points to an API-keyed ADS service rather than a plug-and-play free historical price endpoint. See [APIR ADS API docs](https://www.apir.com.au/documentations/adsapiv2) and [How APIR Codes can be used](https://support.apir.com.au/hc/en-us/articles/14019438886543-How-can-APIR-Codes-be-used).
- Morningstar Australia public pages expose internal IDs and frontend references to `graphapi.prd.morningstar.com.au/graphql`, but direct backend access was Cloudflare-blocked during testing. That makes Morningstar more useful for discovery and source tracing than for a durable default connector today.

## Live Funds

- Fidelity Australian Equities Fund
- Firetrail High Conviction Fund
- Airlie Australian Share Fund
- Ausbil Active Equity
- Greencape High Conviction
- Greencape Broadcap
- Perpetual Industrial
- ECP Growth Companies
- Perpetual Pure Value
- Bennelong Concentrated
- Pendal Australian Focus Fund
- Smallco Broadcap
- Chester High Conviction Fund
- Selector High Conviction Equity Fund
- Hyperion Australian Growth Companies Fund
- Solaris Core Australian Equity Fund
- Allan Gray Australia Equity Fund

## Disabled Placeholders

- Regal Australian Long Short Equity Fund
- L1 Capital Catalyst Fund
- Northcape Core
- DNR High Conviction
- Auscap High Conviction

## Verification Baseline

- Regression suite: `py -m pytest -q`
- Useful smoke checks:
  - `py main.py --no-cache --fund "Firetrail"`
  - `py main.py --no-cache --fund "Fidelity"`
  - `py main.py --no-cache --fund "Airlie"`
  - `py main.py --no-cache --fund "Bennelong"`
  - `py main.py --no-cache --fund "Smallco"`
  - `py main.py --no-cache --fund "Chester"`
  - `py main.py --no-cache --fund "Selector"`
  - `py main.py --no-cache --fund "Hyperion"`
  - `py main.py --no-cache --fund "Solaris"`
  - `py main.py --no-cache --fund "Allan Gray"`
