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

from src.intelligence.events import get_upcoming_events, nearest_high_impact_days
from src.intelligence.vix import get_india_vix

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

# PCR sentiment CODE → risk score. Keyed on the stable code from
# analytics.calculate_pcr (pcr_sentiment_code), NOT the display prose, so
# reworording the interpretation string can never silently change the score.
_PCR_CODE_RISK: dict[str, int] = {
    "BULLISH":          10,   # pcr > 1.3
    "MILDLY_BULLISH":   25,   # pcr > 1.0
    "NEUTRAL_BEARISH":  55,   # pcr > 0.7
    "BEARISH":          85,   # pcr <= 0.7
    "INSUFFICIENT_DATA": 50,
}


_COMPONENT_WEIGHTS = {"vix": 0.35, "event": 0.30, "pcr": 0.20, "regime": 0.15}


def _unpack(component_result: tuple) -> tuple[int, str, bool]:
    """Normalise a component return to (score, desc, ok).

    Components return 3-tuples. Test stubs (and any legacy contributor) may
    return a 2-tuple; those are treated as reliable (ok=True) for compatibility.
    """
    if len(component_result) == 3:
        return component_result
    score, desc = component_result
    return score, desc, True


def _pcr_score(code: str) -> int:
    """Map a stable PCR sentiment code to a risk score; unknown → neutral 50."""
    return _PCR_CODE_RISK.get(code, 50)


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


# Each component returns (score, description, ok). ok=False means the component
# fell back to a neutral default because its data source was unavailable — the
# aggregate score then reports reduced confidence instead of pretending the
# fallback is a real reading.

def _vix_component() -> tuple[int, str, bool]:
    vix = get_india_vix()
    if "error" in vix:
        return 50, f"VIX unavailable ({vix['error']}) — using neutral 50", False
    level = vix["level"]
    caution = vix.get("caution_level", "MODERATE")
    score = _VIX_SCORES.get(caution, 50)
    return score, f"India VIX {level} ({caution}) → {score}", True


def _event_component() -> tuple[int, str, bool]:
    events = get_upcoming_events(days_ahead=7)
    score = _event_score(events)
    days = nearest_high_impact_days(events.get("events", []))
    if days is None:
        desc = "No HIGH-impact events in next 7 days → 0"
    elif days <= 1:
        desc = f"HIGH-impact event tomorrow or today → {score}"
    else:
        desc = f"Next HIGH-impact event in {days} days → {score}"
    return score, desc, True


_BSE_INDICES = {"SENSEX", "BANKEX"}


def _pcr_component(symbol: str) -> tuple[int, str, bool]:
    try:
        from src.options import analytics as oa
        from src.options.bse_service import get_bse_options_service
        from src.options.service import get_options_service
        svc = get_bse_options_service() if symbol.upper() in _BSE_INDICES else get_options_service()
        chain = svc.get_option_chain(symbol)
        if not isinstance(chain, dict):
            return 50, "PCR chain unavailable — using neutral 50", False
        records = chain.get("records", {})
        expiry = (records.get("expiryDates") or [None])[0]
        if expiry is None:
            return 50, "PCR expiry unavailable — using neutral 50", False
        pcr_result = oa.calculate_pcr(chain, expiry)
        code = pcr_result.get("pcr_sentiment_code", "INSUFFICIENT_DATA")
        interp = pcr_result.get("interpretation", "insufficient data")
        score = _pcr_score(code)
        return score, f"PCR: {interp!r} → {score}", True
    except Exception as exc:
        logger.debug("PCR unavailable for risk score (%s): %s", symbol, exc)
        return 50, f"PCR unavailable ({exc}) — using neutral 50", False


def _regime_component(symbol: str) -> tuple[int, str, bool]:
    try:
        from src.analysis.regime import detect_market_regime
        r = detect_market_regime(symbol)
        if "error" in r:
            return 50, "Regime error — using neutral 50", False
        regime = r.get("regime", "NEUTRAL")
        score = _REGIME_SCORES.get(regime, 50)
        return score, f"Regime {regime} → {score}", True
    except Exception as exc:
        logger.debug("Regime unavailable for risk score (%s): %s", symbol, exc)
        return 50, "Regime unavailable — using neutral 50", False


from src.common.scoring import risk_rating as _rating  # single source of truth


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

    vix_s,    vix_desc,    vix_ok    = _unpack(_vix_component())
    event_s,  event_desc,  event_ok  = _unpack(_event_component())
    pcr_s,    pcr_desc,    pcr_ok    = _unpack(_pcr_component(sym))
    regime_s, regime_desc, regime_ok = _unpack(_regime_component(sym))

    score = round(
        vix_s    * 0.35
        + event_s  * 0.30
        + pcr_s    * 0.20
        + regime_s * 0.15
    )
    score = max(0, min(100, score))

    # Confidence = fraction of the weighted model backed by real (non-fallback)
    # data. A score built entirely from neutral fallbacks must not look reliable.
    ok_map = {"vix": vix_ok, "event": event_ok, "pcr": pcr_ok, "regime": regime_ok}
    confidence = round(sum(w for k, w in _COMPONENT_WEIGHTS.items() if ok_map[k]), 2)
    degraded_components = [k for k, ok in ok_map.items() if not ok]
    is_degraded = bool(degraded_components)

    events_result = get_upcoming_events(days_ahead=7)
    events_list = events_result.get("events", [])

    recommendation = _recommendation(score, events_list)
    if is_degraded:
        recommendation += (
            f" NOTE: score is degraded — {', '.join(degraded_components)} data "
            f"unavailable (confidence {confidence:.2f}); treat as indicative only."
        )

    result = {
        "symbol":      sym,
        "score":       score,
        "rating":      _rating(score),
        "confidence":  confidence,
        "is_degraded": is_degraded,
        "degraded_components": degraded_components,
        "factors": [
            f"VIX (35%): {vix_desc}",
            f"Events (30%): {event_desc}",
            f"PCR (20%): {pcr_desc}",
            f"Regime (15%): {regime_desc}",
        ],
        "recommendation": recommendation,
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
