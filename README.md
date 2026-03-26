# PerfSraper

PerfSraper builds a total-return performance dashboard for a set of Australian equity funds and compares them with the S&P/ASX 200 Accumulation Index.

By default, reports are calculated as of `T-2` so every fund and the benchmark are measured from the same two-business-day-lagged reference point unless you explicitly pass `--as-of`.

## Core Rules

- Every reported number must be a total return.
- The benchmark source of truth is `^AXJT` and should not be swapped for `^AXJO`.
- Relative returns are calculated from the same benchmark return series shown in the absolute table, so visible subtraction should reconcile within rounding.
- `ex_distribution` series must either provide explicit distribution handling or log a fallback warning before price-only returns are used.

## How It Works

1. `main.py` loads `config.yaml`, fetches benchmark and fund history, and builds a total-return index for each series.
2. `total_return.py` rebases direct total-return series to 100 and reinvests distributions for `ex_distribution` series.
3. `performance.py` calculates MTD, 3M, 6M, 12M, 3Y p.a., and 5Y p.a. returns.
4. `output.py` renders absolute and relative tables, can export them to Excel, and can build a polished HTML scorecard for non-technical readers.

## Source Notes

- `yfinance` funds use adjusted close data directly.
- Some scraper-backed funds report distributions on the cum-price row rather than the next ex-price row. Those sources use `distribution_timing: next_price_date` in `config.yaml` so distributions are reinvested against the correct tradable price.
- Airlie historical prices are sourced from a multi-sheet workbook. The scraper reads all sheets and derives distributions from rows flagged as `ex`.
- Scraper-backed funds can lag the report date. When that happens, the rendered tables show the fund row as `as of YYYY-MM-DD, stale Nd` so the return is not mistaken for a same-day value.

## Common Commands

```powershell
py -m pytest -q
py main.py --no-cache
py main.py --no-cache --fund "Firetrail"
py main.py --no-cache --fund "Fidelity"
py main.py --no-cache --fund "Airlie"
py main.py --no-cache --export xlsx
py main.py --no-cache --export html
py main.py --no-cache --export all
py main.py --no-cache --export html --output-dir reports --send-teams
```

## Non-Technical Sharing

For a friendlier audience, PerfSraper can generate a styled HTML report with summary cards, leaderboards, and responsive tables that explain the benchmark context more clearly than the terminal output.

Use this command to create the HTML report locally:

```powershell
py main.py --no-cache --export html --output-dir reports
```

## Teams Delivery

Teams delivery posts an Adaptive Card into a channel webhook with the scorecard summary at the top and the full absolute performance table for all funds at the bottom, while keeping the full HTML report archived locally in `reports/`.

Required environment variable:

- `PERFSRAPER_TEAMS_WEBHOOK_URL`

Example one-off send:

```powershell
$env:PERFSRAPER_TEAMS_WEBHOOK_URL = "https://your-tenant.webhook.office.com/..."
py main.py --no-cache --export html --output-dir reports --send-teams
```

This works well for standard channels because the channel gets a concise daily summary card while the local `reports/` folder keeps the full styled HTML output.

The Teams card and the HTML export both use the same `T-2` as-of date by default, so benchmark and fund returns stay aligned.

Legacy `webhook.office.com` connector URLs automatically use the older MessageCard format for better rendering compatibility, while newer webhook endpoints use Adaptive Cards.

If your webhook URL is an older Microsoft 365 connector URL, plan to replace it with a Teams Workflows webhook before April 30, 2026.

## Daily Automation On Windows

The repo includes `scripts/send_daily_report.ps1`, which refreshes the data, writes the HTML report into `reports/`, and posts the daily summary card to Teams using your webhook URL.

You can schedule it in Windows Task Scheduler with:

1. Program/script: `powershell.exe`
2. Add arguments: `-ExecutionPolicy Bypass -File "C:\Users\David Glasser\OneDrive\Documents\Projects\PerfSraper\scripts\send_daily_report.ps1"`
3. Trigger: Daily at your preferred send time
4. Enable `Run whether user is logged on or not` if you want it to keep sending unattended

## GitHub Actions Automation

For a fully autonomous cloud run, the repo includes `.github/workflows/daily-teams-report.yml`.

What it does:

- runs on GitHub-hosted Linux runners
- posts the Teams summary card from GitHub instead of your PC
- uploads the generated HTML report as a workflow artifact
- calculates the report as of `T-2` in `Australia/Sydney`
- handles Sydney daylight saving by checking the local `Australia/Sydney` hour before sending

Before it can run, add this GitHub Actions secret in your repository:

- `PROJECTEAGLE_TEAMS_WEBHOOK_URL`

After that, the workflow can be run manually from the Actions tab or on its daily schedule.

## Useful Files

- `config.yaml`: live fund list, source metadata, and source-specific handling flags
- `main.py`: pipeline orchestration and table assembly
- `total_return.py`: TRI construction logic
- `performance.py`: period return calculations
- `output.py`: console tables, Excel export, and the HTML scorecard
- `teams_delivery.py`: Teams webhook card generation and posting
- `delivery.py`: SMTP email delivery helpers
- `.github/workflows/daily-teams-report.yml`: fully autonomous GitHub Actions schedule
- `connectors/base.py`: connector contract and normalization
- `connectors/scraper_connector.py`: scraper families and source-specific parsing
- `references/current-state.md`: current source inventory and recent fixes
