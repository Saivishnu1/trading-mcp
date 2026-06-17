"""
Market Risk Score — Phase 10.

Composite 0-100 score derived from:
  VIX caution level      35%
  Event proximity        30%
  PCR interpretation     20%  (uses the full interpretation string from calculate_pcr)
  Market regime          15%

Higher score = more risk. Not a trading signal — a context modifier.

Cache TTL: 60 s (1 min).
"""
from __future__ import annotations

import logging
import threading
import time

from src.intelligence.vix import get_india_vix
from src.intelligence.events import get_upcoming_events, nearest_high_impact_days

logger = logging.getLogger(__name__)

_TTL = 60
_CACHE: dict[str, tuple[dict, float]] = {}
_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Component scorers (each returns 0-100)
# ---------------------------------------------------------------------------

_VIX_SCORES = {
    "LOW":      15,
    "MODERATE": 45,
    "HIGH":     75,
    "EXTREME":  100,
}

_REGIME_SCORES = {
    "BULL_TREND":         5,
    "NEUTRAL_BULLISH":    25,
    "BREAKOUT_POTENTIAL": 40,
    "RANGE_BOUND":        50,
    "NEUTRAL":            55,
    "NEUTRAL_BEARISH":    70,
    "BEAR_TREND":         90,
}

# PCR interpretation → risk score (keyed by substring match)
# Matches the exact strings returned by analytics._pcr_sentiment()
_PCR_RISK: list[tuple[str, int]] = [
    ("bullish — elevated put writing", 10),   # pcr > 1.3
    ("mildly bullish",                 25),   # pcr > 1.0
    ("neutral to mildly bearish",      55),   # pcr > 0.7
    ("bearish — elevated call writing", 85),  # pcr <= 0.7
    ("insufficient data",              50),
]


def _pcr_score(interpretation: str) -> int:
    interp = (interpretation or "").lower()
    for fragment, score in _PCR_RISK:
        if fragment in interp:
            return score
    return 50  # unknown → neutral


def _event_score(events_result: dict) -> int:
    days = nearest_high_impact_days(events_result.get("events", []))
    if days is None:
        return 0
    if days <= 1:
        return 100
    if days <= 2:
        return 80
    if days <= 5:
        return 50
    return 20


def _vix_component() -> tuple[int, str]:
    vix = get_india_vix()
    if "error" in vix:
        return 50, f"VIX unavailable ({vix['error']}) — using neutral 50"
    level = vix["level"]
    caution = vix.get("caution_level", "MODERATE")
    score = _VIX_SCORES.get(caution, 50)
    return score, f"India VIX {level} ({caution}) → {score}"


def _event_component() -> tuple[int, str]:
    events = get_upcoming_events(days_ahead=7)
    score = _event_score(events)
    days = nearest_high_impact_days(events.get("events", []))
    if days is None:
        desc = "No HIGH-impact events in next 7 days → 0"
    elif days <= 1:
        desc = f"HIGH-impact event tomorrow or today → {score}"
    else:
        desc = f"Next HIGH-impact event in {days} days → {score}"
    return score, desc


def _pcr_component(symbol: str) -> tuple[int, str]:
    try:
        from src.options.service import get_options_service
        from src.options import analytics as oa
        svc = get_options_service()
        chain = svc.get_option_chain(symbol)
        records = chain.get("records", {})
        expiry = (records.get("expiryDates") or [None])[0]
        if expiry is None:
            return 50, "PCR expiry unavailable — using neutral 50"
        pcr_result = oa.calculate_pcr(chain, expiry)
        interp = pcr_result.get("interpretation", "insufficient data")
        score = _pcr_score(interp)
        return score, f"PCR: {interp!r} → {score}"
    except Exception as exc:
        logger.debug("PCR unavailable for risk score (%s): %s", symbol, exc)
        return 50, f"PCR unavailable ({exc}) — using neutral 50"


def _regime_component(symbol: str) -> tuple[int, str]:
    try:
        from src.analysis.regime import detect_market_regime
        r = detect_market_regime(symbol)
        if "error" in r:
            return 50, f"Regime error — using neutral 50"
        regime = r.get("regime", "NEUTRAL")
        score = _REGIME_SCORES.get(regime, 50)
        return score, f"Regime {regime} → {score}"
    except Exception as exc:
        logger.debug("Regime unavailable for risk score (%s): %s", symbol, exc)
        return 50, f"Regime unavailable — using neutral 50"


def _rating(score: int) -> str:
    if score < 30:
        return "LOW"
    if score < 60:
        return "MODERATE"
    if score < 80:
        return "HIGH"
    return "EXTREME"


def _recommendation(score: int, events: list[dict]) -> str:
    days = nearest_high_impact_days(events)
    event_warning = ""
    if days is not None and days <= 3:
        first_high = next(
            (e for e in events if e.get("impact") == "HIGH"), None
        )
        if first_high:
            event_warning = (
                f" {first_high['description']} in {days} day(s) —"
                " consider defined-risk structures."
            )
    if score < 30:
        return "Conditions are calm. Normal position sizing is appropriate." + event_warning
    if score < 60:
        return "Moderate risk environment. Standard risk management applies." + event_warning
    if score < 80:
        return (
            "Elevated risk. Reduce position size or use defined-risk spreads."
            + event_warning
        )
    return (
        "Extreme risk environment. Avoid new trades or use minimal size."
        + event_warning
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_market_risk_score(symbol: str = "NIFTY") -> dict:
    """
    Composite market risk score for *symbol* (0 = no risk, 100 = extreme risk).

    Weights: VIX 35% + upcoming events 30% + PCR 20% + regime 15%.
    """
    sym = symbol.upper()
    cache_key = f"risk_{sym}"
    with _LOCK:
        if cache_key in _CACHE:
            result, ts = _CACHE[cache_key]
            if time.monotonic() - ts < _TTL:
                return result

    vix_s,    vix_desc    = _vix_component()
    event_s,  event_desc  = _event_component()
    pcr_s,    pcr_desc    = _pcr_component(sym)
    regime_s, regime_desc = _regime_component(sym)

    score = round(
        vix_s    * 0.35
        + event_s  * 0.30
        + pcr_s    * 0.20
        + regime_s * 0.15
    )
    score = max(0, min(100, score))

    events_result = get_upcoming_events(days_ahead=7)
    events_list = events_result.get("events", [])

    result = {
        "symbol":      sym,
        "score":       score,
        "rating":      _rating(score),
        "factors": [
            f"VIX (35%): {vix_desc}",
            f"Events (30%): {event_desc}",
            f"PCR (20%): {pcr_desc}",
            f"Regime (15%): {regime_desc}",
        ],
        "recommendation": _recommendation(score, events_list),
        "inputs": {
            "vix_score":    vix_s,
            "event_score":  event_s,
            "pcr_score":    pcr_s,
            "regime_score": regime_s,
        },
    }

    with _LOCK:
        _CACHE[cache_key] = (result, time.monotonic())
    return result
