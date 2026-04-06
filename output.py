from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Font
from rich.console import Console
from rich.table import Table

from performance import PERIODS


def _format_value(value: float | None, error: bool = False) -> str:
    if error:
        return "[bold red]Error[/bold red]"
    if value is None:
        return "N/A"
    color = "green" if value >= 0 else "red"
    return f"[{color}]{value * 100:.1f}%[/{color}]"


def _format_percent(value: float | None, error: bool = False) -> str:
    if error:
        return "Error"
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def _format_public_date(latest_date) -> str:
    if latest_date is None:
        return "latest public date"
    timestamp = pd.Timestamp(latest_date)
    return f"{timestamp:%Y-%m-%d}"


def _plain_row_label(row: dict) -> str:
    label = str(row["Fund"])
    if _row_is_stale(row):
        label = f"{label} (as of {_format_public_date(row.get('latest_date'))}, stale {row['stale_days']}d)"
    return label


def _safe_period_value(row: dict, period: str) -> float:
    value = row.get(period)
    return float("-inf") if value is None else float(value)


def _row_is_stale(row: dict) -> bool:
    return bool(row.get("is_stale", row.get("stale_days", 0) > 0))


def _average_by_style(rows: list[dict], period: str) -> list[dict[str, object]]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        if row.get("is_benchmark") or row.get("is_average") or row.get("error"):
            continue
        style = str(row.get("Style") or "").strip()
        value = row.get(period)
        if not style or value is None:
            continue
        grouped.setdefault(style, []).append(float(value))

    averages = [
        {"style": style, "count": len(values), "average": sum(values) / len(values)}
        for style, values in grouped.items()
        if values
    ]
    return sorted(averages, key=lambda row: (-float(row["average"]), str(row["style"])))


def _build_style_commentary(absolute_rows: list[dict], relative_rows: list[dict]) -> str:
    absolute_styles = _average_by_style(absolute_rows, "12M")
    relative_styles = _average_by_style(relative_rows, "12M")

    if not absolute_styles and not relative_styles:
        return "No 12M style averages are available yet."

    absolute_leader = absolute_styles[0] if absolute_styles else None
    absolute_trailer = absolute_styles[-1] if len(absolute_styles) > 1 else None
    relative_leader = relative_styles[0] if relative_styles else None

    if absolute_leader and relative_leader and absolute_leader["style"] == relative_leader["style"]:
        commentary = (
            f"On 12M style averages, {absolute_leader['style']} leads both total return "
            f"({_format_percent(float(absolute_leader['average']))}) and excess return "
            f"({_format_percent(float(relative_leader['average']))} versus the benchmark)."
        )
    elif absolute_leader and relative_leader:
        commentary = (
            f"On 12M style averages, {absolute_leader['style']} leads total return at "
            f"{_format_percent(float(absolute_leader['average']))}, while {relative_leader['style']} leads "
            f"excess return at {_format_percent(float(relative_leader['average']))} versus the benchmark."
        )
    elif absolute_leader:
        commentary = (
            f"On 12M style averages, {absolute_leader['style']} leads total return at "
            f"{_format_percent(float(absolute_leader['average']))}."
        )
    else:
        commentary = (
            f"On 12M style averages, {relative_leader['style']} leads excess return at "
            f"{_format_percent(float(relative_leader['average']))} versus the benchmark."
        )

    if absolute_trailer is not None and absolute_leader is not None and absolute_trailer["style"] != absolute_leader["style"]:
        commentary += (
            f" {absolute_trailer['style']} is the weakest total-return cohort at "
            f"{_format_percent(float(absolute_trailer['average']))}."
        )
    return commentary


def _report_snapshot(absolute_rows: list[dict], relative_rows: list[dict]) -> dict[str, object]:
    benchmark = next((row for row in absolute_rows if row.get("is_benchmark")), None)
    fund_rows = [row for row in absolute_rows if not row.get("is_benchmark") and not row.get("is_average")]
    fund_relative_rows = [row for row in relative_rows if not row.get("is_average")]
    valid_absolute = [row for row in fund_rows if not row.get("error") and row.get("12M") is not None]
    valid_relative = [row for row in fund_relative_rows if not row.get("error") and row.get("12M") is not None]

    return {
        "benchmark": benchmark,
        "fund_rows": fund_rows,
        "live_count": len(fund_rows),
        "stale_count": sum(1 for row in fund_rows if _row_is_stale(row)),
        "ahead_count": sum(1 for row in valid_relative if float(row["12M"]) > 0),
        "best_absolute": max(valid_absolute, key=lambda row: _safe_period_value(row, "12M"), default=None),
        "best_relative": max(valid_relative, key=lambda row: _safe_period_value(row, "12M"), default=None),
        "leaders": sorted(valid_absolute, key=lambda row: _safe_period_value(row, "12M"), reverse=True)[:5],
        "style_commentary": _build_style_commentary(fund_rows, fund_relative_rows),
    }


def render_tables(absolute_rows: list[dict], relative_rows: list[dict], as_of_date, console: Console | None = None) -> None:
    console = console or Console()
    if any(_row_is_stale(row) for row in absolute_rows + relative_rows):
        console.print(
            "[yellow]Note: rows marked stale use the latest public fund date shown in the row label, not the report date in the title.[/yellow]"
        )
        console.print()
    console.print(build_rich_table(absolute_rows, f"Absolute Total Return Performance ({as_of_date:%Y-%m-%d})"))
    console.print()
    console.print(build_rich_table(relative_rows, f"Relative Total Return Performance ({as_of_date:%Y-%m-%d})"))


def build_rich_table(rows: list[dict], title: str) -> Table:
    table = Table(title=title)
    table.add_column("Fund", style="bold")
    table.add_column("Style")
    for period in PERIODS:
        label = f"{period} (p.a.)" if period in {"3Y", "5Y"} else period
        table.add_column(label, justify="right")

    for row in rows:
        label = row["Fund"]
        if row.get("is_benchmark"):
            label = f"[bold]{label}[/bold]"
        if row.get("is_average"):
            label = f"[bold]{label}[/bold]"
        if _row_is_stale(row):
            latest_date = row.get("latest_date")
            latest_label = latest_date.strftime("%Y-%m-%d") if latest_date is not None else "latest public date"
            label = f"{label} [yellow](as of {latest_label}, stale {row['stale_days']}d)[/yellow]"

        values = [_format_value(row.get(period), error=row.get("error", False)) for period in PERIODS]
        table.add_row(label, str(row.get("Style") or ""), *values)

    return table


def build_plaintext_report(absolute_rows: list[dict], relative_rows: list[dict], as_of_date) -> str:
    snapshot = _report_snapshot(absolute_rows, relative_rows)
    benchmark = snapshot["benchmark"]
    lines = [
        f"Australian Equity Fund Scorecard ({as_of_date:%Y-%m-%d})",
        "",
        "This report shows total returns, with distributions reinvested where needed.",
        "Relative performance is shown versus the S&P/ASX 200 Accumulation benchmark.",
    ]

    if benchmark is not None:
        lines.append(f"Benchmark 12M: {_format_percent(benchmark.get('12M'))}")
        lines.append(f"Benchmark 3Y p.a.: {_format_percent(benchmark.get('3Y'))}")

    lines.extend(
        [
            f"Funds ahead of benchmark over 12M: {snapshot['ahead_count']} of {snapshot['live_count']}",
            f"Funds with stale public data: {snapshot['stale_count']}",
        ]
    )

    best_absolute = snapshot["best_absolute"]
    best_relative = snapshot["best_relative"]
    if best_absolute is not None:
        lines.append(f"Best 12M total return: {best_absolute['Fund']} ({_format_percent(best_absolute.get('12M'))})")
    if best_relative is not None:
        lines.append(f"Best 12M excess return: {best_relative['Fund']} ({_format_percent(best_relative.get('12M'))})")
    lines.append(f"Style lens: {snapshot['style_commentary']}")

    leaders = snapshot["leaders"]
    if leaders:
        lines.extend(["", "Top 12M funds:"])
        for row in leaders:
            lines.append(f"- {_plain_row_label(row)}: {_format_percent(row.get('12M'))}")

    lines.extend(["", "The HTML version of this report includes the full styled tables."])
    return "\n".join(lines)


def build_html_report(absolute_rows: list[dict], relative_rows: list[dict], as_of_date) -> str:
    snapshot = _report_snapshot(absolute_rows, relative_rows)
    benchmark = snapshot["benchmark"]
    best_absolute = snapshot["best_absolute"]
    best_relative = snapshot["best_relative"]

    summary_cards = [
        ("Live funds", str(snapshot["live_count"]), "Managers currently included in the daily report."),
        (
            "Funds ahead of benchmark (12M)",
            f"{snapshot['ahead_count']} / {snapshot['live_count']}",
            "How many live funds are ahead of the benchmark over the last 12 months.",
        ),
        (
            "Benchmark 12M",
            _format_percent(None if benchmark is None else benchmark.get("12M")),
            "S&P/ASX 200 Accumulation return over the last 12 months.",
        ),
        (
            "Stale sources",
            str(snapshot["stale_count"]),
            "Funds whose latest public data is older than the report date.",
        ),
    ]

    leaders_html = "".join(
        f"""
        <li>
          <span class="leader-name">{escape(str(row["Fund"]))}</span>
          <span class="leader-value">{escape(_format_percent(row.get("12M")))}</span>
        </li>
        """
        for row in snapshot["leaders"]
    )
    if not leaders_html:
        leaders_html = "<li><span class=\"leader-name\">No 12M leaders available</span><span class=\"leader-value\">N/A</span></li>"

    benchmark_blurb = (
        f"{escape(_format_percent(benchmark.get('MTD')))} MTD and {escape(_format_percent(benchmark.get('12M')))} over 12 months."
        if benchmark is not None
        else "Benchmark data unavailable."
    )
    best_absolute_blurb = (
        f"{escape(str(best_absolute['Fund']))} is the strongest 12M total-return result at {escape(_format_percent(best_absolute.get('12M')))}."
        if best_absolute is not None
        else "No 12M absolute leader is available."
    )
    best_relative_blurb = (
        f"{escape(str(best_relative['Fund']))} leads on 12M excess return at {escape(_format_percent(best_relative.get('12M')))}."
        if best_relative is not None
        else "No 12M relative leader is available."
    )

    cards_html = "".join(
        f"""
        <article class="stat-card">
          <p class="stat-label">{escape(label)}</p>
          <p class="stat-value">{escape(value)}</p>
          <p class="stat-note">{escape(note)}</p>
        </article>
        """
        for label, value, note in summary_cards
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Australian Equity Fund Scorecard | {as_of_date:%Y-%m-%d}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg-top: #f2ebe0;
      --bg-bottom: #eef5ef;
      --panel: rgba(255, 255, 255, 0.9);
      --panel-strong: rgba(255, 255, 255, 0.96);
      --ink: #17352f;
      --muted: #5d6b66;
      --border: #d5dccf;
      --accent: #1f6a5b;
      --accent-soft: #dbece7;
      --warm: #bb6d43;
      --warm-soft: #f0dfd4;
      --green: #1f7d4b;
      --green-soft: #def1e5;
      --red: #b24f3e;
      --red-soft: #f6dfd9;
      --neutral: #58656a;
      --neutral-soft: #edf1f2;
      --shadow: 0 18px 40px rgba(25, 47, 42, 0.12);
      --radius-lg: 26px;
      --radius-md: 18px;
      --radius-sm: 999px;
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0;
      font-family: "Aptos", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(187, 109, 67, 0.16), transparent 35%),
        radial-gradient(circle at top right, rgba(31, 106, 91, 0.18), transparent 35%),
        linear-gradient(180deg, var(--bg-top), var(--bg-bottom));
    }}
    .shell {{
      width: min(1200px, calc(100% - 32px));
      margin: 0 auto;
      padding: 32px 0 40px;
    }}
    .hero {{
      padding: 32px;
      border: 1px solid rgba(255, 255, 255, 0.55);
      border-radius: var(--radius-lg);
      background: linear-gradient(135deg, rgba(21, 54, 47, 0.92), rgba(31, 106, 91, 0.88));
      color: #f7f3eb;
      box-shadow: var(--shadow);
      overflow: hidden;
      position: relative;
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: auto -10% -35% auto;
      width: 320px;
      height: 320px;
      border-radius: 50%;
      background: rgba(255, 255, 255, 0.08);
    }}
    .eyebrow {{
      margin: 0 0 10px;
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-size: 12px;
      opacity: 0.78;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(34px, 5vw, 54px);
      line-height: 1.02;
      max-width: 12ch;
    }}
    .lede {{
      margin: 16px 0 0;
      max-width: 760px;
      font-size: 17px;
      line-height: 1.6;
      color: rgba(247, 243, 235, 0.9);
    }}
    .hero-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 22px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      padding: 10px 14px;
      border-radius: var(--radius-sm);
      background: rgba(255, 255, 255, 0.12);
      border: 1px solid rgba(255, 255, 255, 0.18);
      font-size: 14px;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 16px;
      margin-top: 22px;
    }}
    .stat-card {{
      padding: 22px;
      border-radius: var(--radius-md);
      background: var(--panel);
      border: 1px solid rgba(255, 255, 255, 0.6);
      box-shadow: var(--shadow);
      backdrop-filter: blur(6px);
    }}
    .stat-label {{
      margin: 0;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 12px;
    }}
    .stat-value {{
      margin: 10px 0 8px;
      font-size: 34px;
      font-weight: 700;
      line-height: 1.05;
    }}
    .stat-note {{
      margin: 0;
      color: var(--muted);
      line-height: 1.5;
      font-size: 14px;
    }}
    .insights {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
      margin-top: 16px;
    }}
    .insight-card,
    .table-card {{
      padding: 24px;
      border-radius: var(--radius-lg);
      background: var(--panel-strong);
      border: 1px solid rgba(255, 255, 255, 0.65);
      box-shadow: var(--shadow);
    }}
    .insight-kicker {{
      margin: 0 0 10px;
      color: var(--warm);
      text-transform: uppercase;
      letter-spacing: 0.1em;
      font-size: 12px;
    }}
    .insight-card h2,
    .table-card h2 {{
      margin: 0;
      font-size: 24px;
      line-height: 1.2;
    }}
    .insight-card p,
    .table-card p {{
      margin: 10px 0 0;
      color: var(--muted);
      line-height: 1.6;
    }}
    .leader-list {{
      list-style: none;
      margin: 18px 0 0;
      padding: 0;
      display: grid;
      gap: 10px;
    }}
    .leader-list li {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      padding: 12px 14px;
      border-radius: 16px;
      background: #f8faf7;
      border: 1px solid var(--border);
    }}
    .leader-name {{
      font-weight: 600;
    }}
    .leader-value {{
      white-space: nowrap;
      color: var(--accent);
      font-weight: 700;
    }}
    .table-card {{
      margin-top: 16px;
    }}
    .table-wrap {{
      margin-top: 18px;
      overflow-x: auto;
      border-radius: 18px;
      border: 1px solid var(--border);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 760px;
      background: white;
    }}
    th,
    td {{
      padding: 14px 16px;
      text-align: left;
      border-bottom: 1px solid #eef1ec;
      vertical-align: top;
    }}
    th {{
      position: sticky;
      top: 0;
      z-index: 1;
      background: #f5f7f2;
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    th:first-child,
    td:first-child {{
      position: sticky;
      left: 0;
      z-index: 1;
      background: inherit;
    }}
    tbody tr:nth-child(odd) {{
      background: #fbfcfa;
    }}
    tbody tr.benchmark-row {{
      background: #f0f6f2;
    }}
    tbody tr.benchmark-row td:first-child {{
      background: #f0f6f2;
    }}
    tbody tr.summary-row {{
      background: #eef5ef;
    }}
    tbody tr.summary-row td {{
      font-weight: 700;
    }}
    tbody tr.summary-row td:first-child {{
      background: #eef5ef;
    }}
    tbody tr:hover {{
      background: #f4f8f6;
    }}
    tbody tr:hover td:first-child {{
      background: #f4f8f6;
    }}
    .fund-name {{
      font-weight: 700;
      color: var(--ink);
    }}
    .fund-meta {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 13px;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 76px;
      padding: 8px 10px;
      border-radius: var(--radius-sm);
      font-weight: 700;
      font-size: 14px;
      white-space: nowrap;
    }}
    .pill.positive {{
      color: var(--green);
      background: var(--green-soft);
    }}
    .pill.negative {{
      color: var(--red);
      background: var(--red-soft);
    }}
    .pill.neutral {{
      color: var(--neutral);
      background: var(--neutral-soft);
    }}
    .pill.error {{
      color: var(--red);
      background: var(--red-soft);
    }}
    .style-label {{
      color: var(--muted);
      font-weight: 600;
    }}
    .footer {{
      margin-top: 16px;
      padding: 18px 24px;
      border-radius: 20px;
      background: rgba(255, 255, 255, 0.72);
      border: 1px solid rgba(255, 255, 255, 0.7);
      color: var(--muted);
      line-height: 1.6;
      font-size: 14px;
    }}
    @media (max-width: 960px) {{
      .stats,
      .insights {{
        grid-template-columns: 1fr 1fr;
      }}
    }}
    @media (max-width: 680px) {{
      .shell {{
        width: min(100% - 18px, 1200px);
        padding-top: 18px;
      }}
      .hero,
      .stat-card,
      .insight-card,
      .table-card {{
        padding: 18px;
      }}
      .stats,
      .insights {{
        grid-template-columns: 1fr;
      }}
      th:first-child,
      td:first-child {{
        position: static;
      }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <p class="eyebrow">Daily distribution-aware performance snapshot</p>
      <h1>Australian Equity Fund Scorecard</h1>
      <p class="lede">
        A cleaner, more approachable view of manager performance for non-technical readers.
        All figures are total return, and relative numbers are shown against the S&amp;P/ASX 200 Accumulation benchmark.
      </p>
      <div class="hero-meta">
        <span class="badge">As of {as_of_date:%Y-%m-%d}</span>
        <span class="badge">{snapshot['live_count']} live funds</span>
        <span class="badge">{snapshot['stale_count']} stale public sources</span>
      </div>
    </section>

    <section class="stats">
      {cards_html}
    </section>

    <section class="insights">
      <article class="insight-card">
        <p class="insight-kicker">Benchmark pulse</p>
        <h2>S&amp;P/ASX 200 Accumulation</h2>
        <p>{benchmark_blurb}</p>
      </article>
      <article class="insight-card">
        <p class="insight-kicker">Strongest total return</p>
        <h2>Best 12M performer</h2>
        <p>{best_absolute_blurb}</p>
      </article>
      <article class="insight-card">
        <p class="insight-kicker">Strongest excess return</p>
        <h2>Best 12M versus benchmark</h2>
        <p>{best_relative_blurb}</p>
      </article>
    </section>

    <section class="table-card">
      <p class="insight-kicker">Style lens</p>
      <h2>How styles are tracking</h2>
      <p>{escape(str(snapshot['style_commentary']))}</p>
    </section>

    <section class="table-card">
      <p class="insight-kicker">Leaderboard</p>
      <h2>Top 12M funds</h2>
      <p>The strongest trailing-12-month total-return results among live managers.</p>
      <ul class="leader-list">
        {leaders_html}
      </ul>
    </section>

    <section class="table-card">
      <p class="insight-kicker">Absolute performance</p>
      <h2>Total return table</h2>
      <p>Returns shown after reinvesting distributions where required. Green values are positive, red values are negative.</p>
      <div class="table-wrap">
        {_build_html_table(absolute_rows, include_benchmark_marker=True)}
      </div>
    </section>

    <section class="table-card">
      <p class="insight-kicker">Relative performance</p>
      <h2>Return above or below benchmark</h2>
      <p>Relative performance shows each fund's excess return against the S&amp;P/ASX 200 Accumulation index.</p>
      <div class="table-wrap">
        {_build_html_table(relative_rows, include_benchmark_marker=False)}
      </div>
    </section>

    <section class="footer">
      Rows marked stale use the latest public fund date shown in the row, not the headline report date.
      Average rows are the simple mean of live fund returns excluding the benchmark. Three-year and five-year figures are annualized.
    </section>
  </main>
</body>
</html>"""


def _build_html_table(rows: list[dict], include_benchmark_marker: bool) -> str:
    header_cells = "".join(
        f"<th>{escape(f'{period} (p.a.)' if period in {'3Y', '5Y'} else period)}</th>" for period in PERIODS
    )

    body_rows = []
    for row in rows:
        row_classes: list[str] = []
        if include_benchmark_marker and row.get("is_benchmark"):
            row_classes.append("benchmark-row")
        if row.get("is_average"):
            row_classes.append("summary-row")
        latest_date = row.get("latest_date")
        stale_meta = ""
        if _row_is_stale(row):
            stale_meta = (
                f"<div class=\"fund-meta\">Public data through {_format_public_date(latest_date)} "
                f"({int(row['stale_days'])} day{'s' if int(row['stale_days']) != 1 else ''} stale)</div>"
            )
        elif latest_date is not None:
            stale_meta = f"<div class=\"fund-meta\">Public data through {_format_public_date(latest_date)}</div>"

        cells = "".join(_build_html_value_cell(row.get(period), error=row.get("error", False)) for period in PERIODS)
        body_rows.append(
            f"""
            <tr class="{' '.join(row_classes)}">
              <td>
                <div class="fund-name">{escape(str(row["Fund"]))}</div>
                {stale_meta}
              </td>
              <td><span class="style-label">{escape(str(row.get("Style") or ""))}</span></td>
              {cells}
            </tr>
            """
        )

    return f"""
    <table>
      <thead>
        <tr>
          <th>Fund</th>
          <th>Style</th>
          {header_cells}
        </tr>
      </thead>
      <tbody>
        {''.join(body_rows)}
      </tbody>
    </table>
    """


def _build_html_value_cell(value: float | None, error: bool = False) -> str:
    classes = ["pill"]
    if error:
        classes.append("error")
    elif value is None:
        classes.append("neutral")
    elif value >= 0:
        classes.append("positive")
    else:
        classes.append("negative")

    label = escape(_format_percent(value, error=error))
    return f"<td><span class=\"{' '.join(classes)}\">{label}</span></td>"


def export_to_excel(absolute_rows: list[dict], relative_rows: list[dict], as_of_date, output_path: str | Path) -> Path:
    output = Path(output_path)
    absolute_df = _rows_to_dataframe(absolute_rows)
    relative_df = _rows_to_dataframe(relative_rows)

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        absolute_df.to_excel(writer, sheet_name="Absolute", index=False)
        relative_df.to_excel(writer, sheet_name="Relative", index=False)

    workbook = load_workbook(output)
    for sheet_name in ("Absolute", "Relative"):
        worksheet = workbook[sheet_name]
        worksheet["A1"].font = Font(bold=True)
        header_to_column = {worksheet.cell(row=1, column=index).value: index for index in range(1, worksheet.max_column + 1)}
        period_start_column = header_to_column.get(PERIODS[0], worksheet.max_column)

        for row in worksheet.iter_rows(min_col=period_start_column, min_row=2):
            for cell in row:
                if isinstance(cell.value, (int, float)):
                    cell.number_format = "0.0%"

        if worksheet.max_row >= 2 and worksheet.max_column >= 2:
            start_column = worksheet.cell(row=1, column=period_start_column).column_letter
            last_column = worksheet.cell(row=1, column=worksheet.max_column).column_letter
            data_range = f"{start_column}2:{last_column}{worksheet.max_row}"
            worksheet.conditional_formatting.add(
                data_range,
                CellIsRule(operator="greaterThanOrEqual", formula=["0"], font=Font(color="008000")),
            )
            worksheet.conditional_formatting.add(
                data_range,
                CellIsRule(operator="lessThan", formula=["0"], font=Font(color="9C0006")),
            )

        for column in worksheet.columns:
            max_length = max(len(str(cell.value or "")) for cell in column)
            worksheet.column_dimensions[column[0].column_letter].width = max_length + 2

    workbook.save(output)
    return output


def export_to_html(absolute_rows: list[dict], relative_rows: list[dict], as_of_date, output_path: str | Path) -> Path:
    output = Path(output_path)
    output.write_text(build_html_report(absolute_rows, relative_rows, as_of_date), encoding="utf-8")
    return output


def _rows_to_dataframe(rows: list[dict]):
    records = []
    for row in rows:
        latest_date = row.get("latest_date")
        record = {
            "Fund": row["Fund"],
            "Style": row.get("Style") or "",
            "As Of": None if latest_date is None else str(pd.Timestamp(latest_date).date()),
        }
        for period in PERIODS:
            record[period] = None if row.get("error") else row.get(period)
        records.append(record)
    return pd.DataFrame(records)
