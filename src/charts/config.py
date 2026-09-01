from __future__ import annotations

from typing import TypedDict


class ChartSpec(TypedDict):
    figsize: tuple[float, float]
    dpi: int
    panels: list[str]
    panel_ratios: list[int]


CHART_SPECS: dict[str, ChartSpec] = {
    "price": {
        "figsize":    (14, 8),
        "dpi":        150,
        "panels":     ["price", "volume"],
        "panel_ratios": [3, 1]
    },
    "indicator": {
        "figsize":    (14, 10),
        "dpi":        150,
        "panels":     ["price", "macd", "rsi"],
        "panel_ratios": [3, 1, 1]
    },
    "option": {
        "figsize":    (14, 6),
        "dpi":        150,
        "panels":     ["oi"],
        "panel_ratios": [1]
    },
    "combined": {
        "figsize":    (14, 12),
        "dpi":        150,
        "panels":     ["price", "volume", "macd", "rsi"],
        "panel_ratios": [3, 1, 1, 1]
    }
}
