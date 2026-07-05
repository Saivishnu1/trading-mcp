"""
Pattern strength classifier — upgrades raw "weak" detections based on
volume confirmation, ADX, RSI context, and proximity to S/R levels.
"""
from __future__ import annotations

from .patterns import CandlePattern

_SR_PROXIMITY = 0.005   # 0.5% — within this band of a level = "at level"
_HIGH_VOL = 1.5
_LOW_VOL = 0.8
_ADX_TRENDING = 25.0


def classify_strength(
    pattern: CandlePattern,
    adx: float | None,
    rsi: float | None,
    levels: dict,
) -> str:
    """
    Returns "strong" | "moderate" | "weak" based on:
      - Volume (> 1.5× avg = positive confirmation)
      - ADX (≥ 25 = trending, adds conviction)
      - Proximity to S/R level (within 0.5%)
    """
    score = 0

    # Volume confirmation
    if pattern.volume_ratio >= _HIGH_VOL:
        score += 2
    elif pattern.volume_ratio >= 1.0:
        score += 1

    # Trending market amplifies patterns
    if adx is not None and adx >= _ADX_TRENDING:
        score += 1

    # Proximity to support/resistance
    close = pattern.close
    all_levels = (
        [s["level"] for s in levels.get("supports", [])] +
        [r["level"] for r in levels.get("resistances", [])]
    )
    for lvl in all_levels:
        if lvl > 0 and abs(close - lvl) / lvl <= _SR_PROXIMITY:
            score += 2
            break

    if score >= 4:
        return "strong"
    if score >= 2:
        return "moderate"
    return "weak"


def build_context(
    pattern: CandlePattern,
    levels: dict,
) -> str:
    """Return a short factual context string about S/R proximity."""
    close = pattern.close
    supports = levels.get("supports", [])
    resistances = levels.get("resistances", [])

    nearest_sup = None
    nearest_res = None
    for s in supports:
        lvl = s["level"]
        if lvl < close and abs(close - lvl) / lvl <= _SR_PROXIMITY:
            if nearest_sup is None or abs(close - lvl) < abs(close - nearest_sup):
                nearest_sup = lvl
    for r in resistances:
        lvl = r["level"]
        if lvl > close and abs(lvl - close) / close <= _SR_PROXIMITY:
            if nearest_res is None or abs(close - lvl) < abs(close - nearest_res):
                nearest_res = lvl

    if nearest_sup is not None and nearest_res is not None:
        return f"Near support at {nearest_sup:,.2f} and resistance at {nearest_res:,.2f}"
    if nearest_sup is not None:
        return f"Near support at {nearest_sup:,.2f}"
    if nearest_res is not None:
        return f"Near resistance at {nearest_res:,.2f}"
    return ""
