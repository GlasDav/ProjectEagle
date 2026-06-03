# Current State

This file is the quick onboarding reference for the live PerfSraper configuration.

## As Of June 2, 2026

- Benchmark: S&P/ASX 200 Accumulation via `^AXJT`
- Live funds: 30
- Disabled funds/placeholders: 26
- Live source mix: 29 scraper-backed `ex_distribution` funds, 1 yfinance `adjusted_close` peer-only ETF

## Active Invariants

- All displayed performance must be total return.
- The relative table must reconcile with the benchmark row shown in the absolute table, within normal display rounding.
- `ex_distribution` series should explicitly model distribution timing where the source does not already provide ex-price history on the distribution row.

## Recent Fixes

### Highlight display and Lazard long-period coverage

- Best/worst highlights now exclude the benchmark/index row and average rows. Tables with fewer than five eligible funds highlight one best and one worst result per period, tables with five to nine eligible funds highlight two of each, and larger tables keep three of each.
- Legacy Teams webhook tables now put the green/red marker after the percentage so numeric values remain aligned.
- Lazard's public daily NAV API currently exposes daily rows from `2025-04-22` onward. The Lazard scraper still uses daily NAV plus explicit distribution PDFs for short periods, and now adds long-period calibration anchors from Lazard's official annualized net AUD performance block, respecting that block's `asOfDate`, so 3Y and 5Y values no longer render as `N/A` solely because the daily NAV window is truncated.

### Selector and Allan Gray deactivation

- Selector High Conviction Equity Fund is disabled in the default lineup because the public source mapping appears wrong.
- Allan Gray Australian Equity is disabled in the default lineup because the public daily EQT price feed is stale and the official month-end fact-sheet price is not suitable for daily MTD ranking.

### GitHub Actions schedule reliability

- The daily Teams workflow now uses 10:37 Australia/Sydney-equivalent UTC cron entries and gates on the triggering cron plus Sydney UTC offset.
- This avoids silently skipping the real scheduled send when GitHub starts a scheduled runner late.

### Benchmark-relative Teams delivery

- The Teams card now shows the full benchmark-relative performance table rather than the absolute table.
- The benchmark row is pinned to the top of that Teams table, and the default lineup excludes the four comparison funds that duplicated broad index coverage.
- Forager Australian Value and Perpetual Pure Value are disabled in the default lineup so the main Teams relative table can post as one Adaptive Card within the workflow payload limit.
- Adaptive Teams table rows now omit redundant spacing/alignment metadata to keep the default main table compact, while very large ad hoc tables can still split.
- Oversized Adaptive main tables now fall back to a compact two-column row layout before splitting, preserving every row, style, and period while avoiding the per-cell JSON overhead that can breach Teams workflow payload limits.

### Exact report-date runs

- `--as-of` remains an upper bound that lets the app choose the best-coverage report date.
- `--report-date YYYY-MM-DD` pins calculations to the benchmark date on or before the requested date and skips the best-coverage date selector.
- GitHub Actions manual runs expose an optional `report_date` input, using `--report-date` only when that input is provided.

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
- Hyperion Australian Growth Companies Fund now combines Hyperion's public daily price CSV with distribution breakdown workbooks discovered via the public media API.
- Solaris Core Australian Equity Fund now reads Solaris' public website tables for unit prices and distributions. The publicly reachable history currently begins on `2021-10-18`, so 5Y output can remain `N/A` until Solaris publishes a longer series.
- Allan Gray Australia Equity Fund has a scraper path combining Equity Trustees prices and Allan Gray fact sheet data, but is disabled because current public data does not provide daily MTD coverage.

### Style metadata

- Every live fund now carries `style: value|growth|agnostic` in `config.yaml`.
- The terminal, HTML, Excel, and Teams tables all show `Style` immediately after `Fund`.
- Style is display metadata only. Ranking, summaries, sorting, and total-return calculations are unchanged.

### Firetrail competitor coverage

- `config.yaml` now represents every fund listed in `Firetrail competitors.xlsx`.
- Exact source-backed matches stay on their existing entries, close name variants are captured via `aliases`, and the remaining names are tracked as disabled placeholders with APIR metadata where available.

### First competitor implementation batch

- Wavestone Australian Share Fund now rides the existing Fidante / FE Precision family via Citi code `L1L7`.
- DNR High Conviction now scrapes the public DNR price-history workbook plus the distribution-history table on the fund page.
- Investors Mutual Australian Share Fund now uses IML's public WordPress AJAX export endpoints for price and distribution history.
- Perpetual Concentrated Equity Fund now uses the existing Perpetual family endpoints with the public fund page's price and distribution history IDs.

### Second competitor implementation batch

- Forager Australian Value now reads the public Google Sheets workbook behind Forager's Australian Shares Fund download, using `Mid Price` as the durable historical NAV field and preserving explicit distribution rows across the workbook's older and newer layouts.
- Katana Australian Equity Fund now reads the public Katana fund page's monthly unit-price accordions, annual distribution list, and latest daily price banner, aligning June distributions to the following ex-price row.

### Third competitor implementation batch

- Vanguard Australian Shares Index now uses Vanguard Australia's public Personal Investor API for daily NAV history and distribution history via managed-fund port `8100`.
- RQI Australian Value (formerly Realindex) now uses the First Sentier / RQI public historical-price download family, which exposes a full CSV with exit prices and inline distribution amounts.
- First Sentier FSI Geared Australian Share Fund now uses that same First Sentier public history family, mapped to the current complex ETF page and its live history feed.
- Dimensional Australian Value now rides the ASX-listed dual-access ETF ticker `DAVA.AX`, which gives total-return coverage through adjusted closes while preserving the managed-fund name via aliases.
- Dimensional Aust Core Equity now does the same through `DACE.AX`.

### Fourth competitor implementation batch

- Lazard Select Australian Equity now combines Lazard's public `api/products?id=183&type=Fund` NAV history with official annual and legacy distribution PDFs for the W class, aligned to the next available price date.
- Lazard Australian Equity (Benchmark Unconstrained) now uses the same Lazard public source family, mapped to the closest publicly exposed Australian Equity W class feed (`product_id: 182`) because Lazard's benchmark-unconstrained strategy page does not publish its own unit-price history.
- Allan Gray Australian Equity has an exact EQT Class A historical-price feed (`ETL0060`) plus Allan Gray Class A fact-sheet distributions, with the older `Allan Gray Australia Equity Fund` name retained as an alias, but remains disabled until a durable daily source is available.

### Fifth competitor implementation batch

- AuscapAM Auscap Ex-20 Australian Equities Fund now reads GSFM's public unit-price history and distribution tables, using the published ex-date valuation price on distribution rows so the series stays explicitly ex-distribution. The live source uses GSFM APIR `ASX6179AU` rather than the older competitor-sheet code.
- Paradice Australian Equities now reads Paradice's official downloadable price-history CSV, using the inline `DPU` field and the `EX` row on distribution dates instead of the same-day cum row. The current public feed uses APIR `ETL8084AU`.

### Sixth competitor implementation batch

- Macquarie Australian Shares now reads Macquarie's public unit-price metadata feed to discover the current historical CSV path, then reconstructs same-date ex prices by subtracting inline `CPU` from the cum redemption-price history on distribution rows. The live public source currently uses APIR `MAQ0443AU` and the published history begins on `2024-10-28`, so `3Y` and `5Y` can remain `N/A` until Macquarie exposes a longer file.

### Peer-set scraper repair

- Firetrail Alpha Plus Fund Complex ETF now reads Firetrail's public unit-price table rather than ASX adjusted closes. The source changed unit scale before ASX quotation, so rows before `2026-01-22` are scaled by `9.03995` to keep the TRI series continuous.
- Firetrail Absolute Return Fund now uses the same Firetrail public unit-price table family, with exit price plus inline distributions.
- Scraper cache keys now include the fund identity as well as the scraper family, so peer-set funds sharing a scraper implementation do not reuse another fund's cached rows.
- Sage Capital Equity Plus Fund and Sage Capital Absolute Return Fund now use Channel Capital's public Google-Sheet CSV feeds with explicit dollar distributions.
- Vinva Australian Equity Alpha Extension Fund now uses the public Magellan/Vinva price-history workbook and derives distributions from workbook `ex` rows through the existing Airlie-style parser.
- Acadian Australian Equity Long Short Fund now reads Colonial First State's public historical unit-price download for Class A (`WF`, group `120`, product `75`). CFS exposes pre-income and post-income exit prices on distribution rows, so the scraper uses the post-income exit price as ex-distribution NAV and reinvests the pre/post difference.
- Ten Cap Alpha Plus Complex ETF now uses `TCAP.AX` adjusted closes. The public history starts on `2025-11-24`, so 6M, 12M, 3Y, and 5Y output can remain `N/A` until the listed history lengthens.
- Regal Australian Long Short Equity Fund, Acadian Wholesale Australian Market Neutral Fund, Regal Tasman Market Neutral Fund, and Bennelong Market Neutral Fund remain disabled because no durable unauthenticated daily unit-price and distribution history feed has been validated. Bennelong's official page still directs users to email Client Experience for daily unit-price information.
- Peer-set appendices now include only source-backed funds; disabled placeholders remain in `config.yaml` for source tracking but are not rendered as all-`N/A` table rows.

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
- Bennelong Concentrated
- Pendal Australian Focus Fund
- Chester High Conviction Fund
- Hyperion Australian Growth Companies Fund
- Solaris Core Australian Equity Fund
- Wavestone Australian Share Fund
- DNR High Conviction
- Perpetual Concentrated Equity Fund
- Katana Australian Equity Fund
- AuscapAM Auscap Ex-20 Australian Equities Fund
- Lazard Select Australian Equity
- Lazard Australian Equity (Benchmark Unconstrained)
- Macquarie Australian Shares
- Paradice Australian Equities
- Firetrail Alpha Plus Fund Complex ETF
- Ten Cap Alpha Plus Complex ETF
- Firetrail Absolute Return Fund
- Sage Capital Equity Plus Fund
- Perpetual SHARE-PLUS Long-Short Fund
- Acadian Australian Equity Long Short Fund
- Vinva Australian Equity Alpha Extension Fund
- Sage Capital Absolute Return Fund

## Disabled Placeholders

- Legacy placeholders carried forward from earlier source work: Regal Australian Long Short Equity Fund, L1 Capital Catalyst Fund, Northcape Core, and Auscap High Conviction.
- Firetrail competitor-sheet placeholders awaiting durable public sources: Schroder Australian Equity Fund, Chester Opportunities Fund, Martin Currie Australia Value Equity, and AB Concentrated Australian Equities.
- Peer-set appendices are configured for long-short and market-neutral competitors. Firetrail Alpha Plus, Ten Cap Alpha Plus, Firetrail Absolute Return, Sage Equity Plus, Perpetual SHARE-PLUS, Acadian Long Short, Vinva Alpha Extension, and Sage Absolute Return have computable public sources. Regal Long Short, Acadian Wholesale Market Neutral, Regal Tasman Market Neutral, and Bennelong Market Neutral remain disabled placeholders until durable public history is validated.
- Selector High Conviction Equity Fund is disabled because the public source mapping appears wrong.
- Vanguard Australian Shares Index is disabled because it closely tracks the benchmark index; its Vanguard API distribution parser now uses the `CASH` tax detail only rather than summing taxable components.
- Smallco Broadcap, Investors Mutual Australian Share Fund, RQI Australian Value (formerly Realindex), First Sentier FSI Geared Australian Share Fund, Dimensional Australian Value, Dimensional Aust Core Equity, Forager Australian Value, and Perpetual Pure Value are represented in config but removed from the default report list.
- Allan Gray Australian Equity is disabled because the official daily price feed currently stops at `2026-03-09`; the month-end fact sheet is useful for longer-period history but not daily MTD ranking.

## Verification Baseline

- Regression suite: `py -m pytest -q`
- Useful smoke checks:
  - `py main.py --no-cache --fund "Firetrail"`
  - `py main.py --no-cache --fund "Fidelity"`
  - `py main.py --no-cache --fund "Airlie"`
  - `py main.py --no-cache --fund "Bennelong"`
  - `py main.py --no-cache --fund "Chester"`
  - `py main.py --no-cache --fund "Hyperion"`
  - `py main.py --no-cache --fund "Solaris"`
  - `py main.py --no-cache --fund "Auscap"`
  - `py main.py --no-cache --fund "Lazard Select"`
  - `py main.py --no-cache --fund "Lazard Australian Equity"`
  - `py main.py --no-cache --fund "Macquarie"`
  - `py main.py --no-cache --fund "Paradice"`
