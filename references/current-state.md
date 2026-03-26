# Current State

This file is the quick onboarding reference for the live PerfSraper configuration.

## As Of March 26, 2026

- Benchmark: S&P/ASX 200 Accumulation via `^AXJT`
- Live funds: 17
- Disabled placeholders: 8
- Live source mix: 4 `yfinance` funds and 13 scraper-backed `ex_distribution` funds

## Active Invariants

- All displayed performance must be total return.
- The relative table must reconcile with the benchmark row shown in the absolute table, within normal display rounding.
- `ex_distribution` series should explicitly model distribution timing where the source does not already provide ex-price history on the distribution row.

## Recent Fixes

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

## Live Funds

- Vanguard Australian Shares ETF
- iShares Core S&P/ASX 200 ETF
- Magellan Global Fund (Open Class)
- Vanguard MSCI Index International Shares ETF
- Fidelity Australian Equities Fund
- Firetrail High Conviction Fund
- Airlie Australian Share Fund
- Ausbil Active Equity
- Greencape High Conviction
- Greencape Broadcap
- Perpetual SHARE-PLUS Long Short
- Perpetual Industrial
- ECP Growth Companies
- Perpetual Pure Value
- Bennelong Concentrated
- Pendal Australian Focus Fund
- Smallco Broadcap

## Disabled Placeholders

- Regal Australian Long Short Equity Fund
- L1 Capital Catalyst Fund
- Northcape Core
- DNR High Conviction
- Chester High Conviction
- Auscap High Conviction
- Selector High Conviction
- Hyperion Growth

## Verification Baseline

- Regression suite: `py -m pytest -q`
- Useful smoke checks:
  - `py main.py --no-cache --fund "Firetrail"`
  - `py main.py --no-cache --fund "Fidelity"`
  - `py main.py --no-cache --fund "Airlie"`
  - `py main.py --no-cache --fund "Bennelong"`
  - `py main.py --no-cache --fund "Smallco"`
