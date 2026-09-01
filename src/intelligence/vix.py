"""
India VIX — Phase 10.

Fetches ^INDIAVIX via the existing market service (yfinance-backed).
Returns current level, 52-week percentile, and a plain-English interpretation.

Cache TTL: 300 s (5 min).
"""
from __future__ import annotations

import threading
import time
from datetime import date, timedelta

from src.market import get_market

_TTL = 300
_CACHE: dict[str, tuple[dict, float]] = {}
_LOCK = threading.Lock()

_VIX_TICKER = "^INDIAVIX"
_LOOKBACK_DAYS = 375  # enough for 252+ trading days


def _interpretation(level: float) -> str:
    if level < 12:
        return "Complacency — historically precedes corrections"
    if level < 15:
        return "Calm — low fear, normal conditions"
    if level < 20:
        return "Mild uncertainty — some hedging activity"
    if level < 25:
        return "Elevated fear — market stress, increase caution"
    return "Extreme fear — major event or systemic stress"


def _caution_level(level: float) -> str:
    if level < 15:
        return "LOW"
    if level < 20:
        return "MODERATE"
    if level < 25:
        return "HIGH"
    return "EXTREME"


def _percentile(current: float, history: list[float]) -> int:
    """Rank of current VIX vs historical closes. 0 = lowest ever, 100 = highest."""
    if not history:
        return 50
    below = sum(1 for v in history if v <= current)
    return round(below / len(history) * 100)


def get_india_vix() -> dict:
    """Return India VIX snapshot with level, 52-week stats, and interpretation."""
    cache_key = "india_vix"
    with _LOCK:
        if cache_key in _CACHE:
            result, ts = _CACHE[cache_key]
            if time.monotonic() - ts < _TTL:
                return result

    try:
        today = date.today()
        start = (today - timedelta(days=_LOOKBACK_DAYS)).isoformat()
        end = (today + timedelta(days=1)).isoformat()
        candles = get_market().get_historical(_VIX_TICKER, start, end, "1d")
        if not candles:
            return {"error": "no VIX data — ^INDIAVIX unavailable"}

        closes = [c["close"] for c in candles if c.get("close") is not None]
        if not closes:
            return {"error": "no VIX data — ^INDIAVIX unavailable"}

        current = round(closes[-1], 2)
        prev = round(closes[-2], 2) if len(closes) >= 2 else None
        change_pct = round((current - prev) / prev * 100, 2) if prev else None
        history = closes[:-1]  # exclude today from reference set

        result = {
            "level":          current,
            "prev_close":     prev,
            "change_pct":     change_pct,
            "week52_high":    round(max(closes), 2),
            "week52_low":     round(min(closes), 2),
            "percentile_52w": _percentile(current, history),
            "interpretation": _interpretation(current),
            "caution_level":  _caution_level(current),
        }
    except Exception as exc:
        return {"error": str(exc)}

    with _LOCK:
        _CACHE[cache_key] = (result, time.monotonic())
    return result
