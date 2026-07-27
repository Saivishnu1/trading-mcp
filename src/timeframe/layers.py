"""Priority 9 — Recommendation Architecture: Options + Risk layers.

The phase brief's requested pipeline is:

    Market Context -> Timeframe Engine -> Data Validation -> Chart Structure
    -> Options Engine -> Risk Engine -> Recommendation Engine

Priorities 1-8 built the Timeframe Engine, Data Validation (freshness
refusal), Chart Structure (technicals/evidence), and Recommendation stages
for real, inside generate_trade_setup_tf's pure-technicals pipeline. Two
stages the brief names were genuinely absent from that pipeline until now:
Options Engine and Risk Engine — generate_trade_setup_tf never touched
options-chain data or the existing composite risk score at all.

This module does not reimplement either — src.options_awareness.engine's
OptionsAwarenessEngine and src.intelligence.risk.get_market_risk_score are
real, working, already-tested engines. This is a thin, best-effort adapter
that calls both and folds their output into generate_trade_setup_tf's
result as two additional, clearly-labeled sections, mirroring Priority 8's
opt-in pattern (check_mixed_timeframes) rather than the brief's literal
"always in the pipeline" diagram — an options-chain fetch has real network
cost and only applies to option-eligible symbols (index/eligible F&O
underlyings), so making it mandatory for every technicals-only setup call
would be wasted cost for the common case.
"""
from __future__ import annotations


def attach_options_layer(symbol: str) -> dict:
    """Best-effort options-chain read for `symbol`. Never raises — a
    non-options-eligible symbol or a chain fetch failure both surface as
    {"available": False, "reason": ...}, not an exception that would take
    down the setup that's asking for this optional layer."""
    try:
        from src.options_awareness.engine import OptionsAwarenessEngine
        result = OptionsAwarenessEngine().analyze(symbol)
    except Exception as exc:
        return {"available": False, "reason": f"options engine raised: {exc}"}

    if result.get("error"):
        return {"available": False, "reason": result["error"]}

    return {
        "available": True,
        "pcr": result.get("pcr"),
        "pcr_interpretation": result.get("pcr_interpretation"),
        "max_pain": result.get("max_pain"),
        "distance_from_max_pain": result.get("distance_from_max_pain"),
        "atm_iv": result.get("iv", {}).get("atm_iv"),
        "iv_skew": result.get("iv", {}).get("iv_skew"),
    }


def attach_risk_layer(symbol: str) -> dict:
    """Best-effort composite risk score for `symbol` via the existing
    src.intelligence.risk engine (VIX 35% + events 30% + PCR 20% + regime
    15%). Never raises — a failure surfaces as {"available": False, ...}."""
    try:
        from src.intelligence.risk import get_market_risk_score
        result = get_market_risk_score(symbol)
    except Exception as exc:
        return {"available": False, "reason": f"risk engine raised: {exc}"}

    if "error" in result:
        return {"available": False, "reason": result["error"]}

    return {
        "available": True,
        "score": result.get("score"),
        "rating": result.get("rating"),
        "recommendation": result.get("recommendation"),
        "is_degraded": result.get("is_degraded"),
        "confidence": result.get("confidence"),
    }
