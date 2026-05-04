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
) -> dict[tuple[int, str], PerformanceHighlight]:
    """Return per-cell top/bottom performance highlights for rendered tables.

    Highlights are calculated independently for each period over valid rendered
    performance rows. Average/summary rows are excluded so they do not consume a
    top/bottom slot; benchmark rows remain eligible when they are part of the
    rendered table. If a very small table causes top and bottom selections to
    overlap, the top highlight wins.
    """

    highlights: dict[tuple[int, str], PerformanceHighlight] = {}

    for period in periods:
        values: list[tuple[int, float, str]] = []
        for index, row in enumerate(rows):
            if row.get("is_average") or row.get("error"):
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

        top_values = sorted(values, key=lambda item: (-item[1], item[2]))[:top_n]
        bottom_values = sorted(values, key=lambda item: (item[1], item[2]))[:bottom_n]

        for index, _, _ in top_values:
            highlights[(index, period)] = HIGHLIGHT_TOP
        for index, _, _ in bottom_values:
            highlights.setdefault((index, period), HIGHLIGHT_BOTTOM)

    return highlights
