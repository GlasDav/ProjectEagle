from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

PerformanceHighlight = Literal["top", "bottom"]

HIGHLIGHT_TOP: PerformanceHighlight = "top"
HIGHLIGHT_BOTTOM: PerformanceHighlight = "bottom"


def build_period_highlights(
    rows: Sequence[Mapping[str, Any]],
    *,
    periods: Sequence[str],
    top_n: int = 3,
    bottom_n: int = 3,
    include_benchmark: bool = False,
) -> dict[tuple[int, str], PerformanceHighlight]:
    """Return per-cell top/bottom performance highlights for rendered tables.

    Highlights are calculated independently for each period over valid rendered
    performance rows. Benchmark and average/summary rows are excluded so they do
    not consume a top/bottom slot, unless a caller explicitly opts benchmarks in.
    If a very small table causes top and bottom selections to overlap, the top
    highlight wins.
    """

    highlights: dict[tuple[int, str], PerformanceHighlight] = {}

    for period in periods:
        values: list[tuple[int, float, str]] = []
        for index, row in enumerate(rows):
            if row.get("is_average") or row.get("error") or (row.get("is_benchmark") and not include_benchmark):
                continue
            value = row.get(period)
            if value is None:
                continue
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue
            values.append((index, numeric_value, str(row.get("Fund") or "")))

        if not values:
            continue

        effective_top_n = _effective_highlight_count(len(values), top_n)
        effective_bottom_n = _effective_highlight_count(len(values), bottom_n)
        top_values = sorted(values, key=lambda item: (-item[1], item[2]))[:effective_top_n]
        bottom_values = sorted(values, key=lambda item: (item[1], item[2]))[:effective_bottom_n]

        for index, _, _ in top_values:
            highlights[(index, period)] = HIGHLIGHT_TOP
        for index, _, _ in bottom_values:
            highlights.setdefault((index, period), HIGHLIGHT_BOTTOM)

    return highlights


def _effective_highlight_count(valid_fund_count: int, requested_count: int) -> int:
    if valid_fund_count <= 0 or requested_count <= 0:
        return 0
    if valid_fund_count < 5:
        dynamic_count = 1
    elif valid_fund_count < 10:
        dynamic_count = 2
    else:
        dynamic_count = 3
    return min(requested_count, dynamic_count, valid_fund_count)
