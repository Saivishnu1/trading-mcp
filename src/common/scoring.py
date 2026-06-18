"""
Shared scoring primitives — single source of truth (Phase 14.6).

These were previously duplicated across modules and could drift:
  - risk_rating: identical 0-100 → LOW/MODERATE/HIGH/EXTREME bands lived in both
    intelligence/risk.py and catalyst/event_risk.py.
  - apply_size_factors: identical multiply-and-floor logic lived in both
    recommendations/engine.py and sizer/engine.py.

This module has no dependencies on other src packages, so it is safe to import
from anywhere without creating cycles.
"""
from __future__ import annotations

# 0-100 risk/event score → rating band. Used by market risk and event risk.
RATING_BANDS = ((30, "LOW"), (60, "MODERATE"), (80, "HIGH"))


def risk_rating(score: int | float) -> str:
    """Map a 0-100 risk/event score to its rating band."""
    for threshold, label in RATING_BANDS:
        if score < threshold:
            return label
    return "EXTREME"


def apply_size_factors(base_size: int | None, factors: list[float]) -> int | None:
    """Multiply base position size by each factor; floor at 1 (never 0).

    Returns None when base_size is None (no actionable size to scale).
    """
    if base_size is None:
        return None
    result = float(base_size)
    for f in factors:
        result *= f
    return max(1, int(round(result)))
