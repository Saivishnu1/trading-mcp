"""
Trade Planner — Phase 5.

Converts market analysis into an executable trade plan.
Read-only: generates plans and sizing only. Does NOT place orders
or call any Zerodha order API.

Reuses existing module functions — no indicators are recalculated here:
  generate_trade_setup()    → signal, entry, stoploss, target
  recommend_strategy()      → strategy, regime, secondary
  calculate_risk_reward()   → risk, reward, rr
  calculate_position_size() → quantity from capital + risk %
  options service           → pcr, max_pain (index symbols only)
"""

from __future__ import annotations

import logging

from src.analysis.regime import (
    calculate_position_size,
    calculate_risk_reward,
    generate_trade_setup,
    recommend_strategy,
)
from src.options import analytics
from src.options.service import get_options_service

def _risk_score_context(symbol: str) -> dict | None:
    """Fetch market risk score for visibility only. Never affects trade logic."""
    try:
        from src.intelligence.risk import get_market_risk_score
        rs = get_market_risk_score(symbol)
        if "error" not in rs:
            return {"score": rs.get("score"), "rating": rs.get("rating")}
    except Exception:
        pass
    return None

from src.common.signals import NEUTRAL_SIGNALS as _NEUTRAL_SIGNALS

logger = logging.getLogger(__name__)


def _options_context(symbol: str) -> dict:
    """PCR and max pain — index options only; silently empty for equities."""
    try:
        svc = get_options_service()
        chain = svc.get_option_chain(symbol)
        records = chain.get("records", {})
        expiry = (records.get("expiryDates") or [None])[0]
        if expiry is None:
            return {}
        pcr = analytics.calculate_pcr(chain, expiry)
        mp = analytics.calculate_max_pain(chain, expiry)
        return {
            "pcr": pcr.get("pcr_oi"),
            "pcr_interpretation": pcr.get("interpretation"),
            "max_pain": mp.get("max_pain"),
        }
    except Exception as exc:
        logger.debug("options context unavailable for %s: %s", symbol, exc)
        return {}


def _trade_quality(rr: float | None) -> str:
    if rr is None or rr < 1.0:
        return "LOW_QUALITY"
    if rr < 1.5:
        return "MODERATE"
    if rr < 2.0:
        return "GOOD"
    return "HIGH_QUALITY"


def _quality_clause(quality: str, rr: float | None) -> str:
    rr_str = f"{rr:.2f}" if rr is not None else "N/A"
    if quality == "LOW_QUALITY":
        return (
            f"current risk/reward is only {rr_str}. "
            "Consider waiting for a better entry or using an options spread structure."
        )
    if quality == "MODERATE":
        return f"risk/reward is {rr_str}. Trade is acceptable but risk/reward remains average."
    if quality == "GOOD":
        return f"risk/reward is {rr_str}. Trade offers favorable risk/reward and aligns with the current market bias."
    return f"risk/reward is {rr_str}. High-conviction setup with strong risk/reward characteristics."


def _build_summary(
    signal: str,
    entry: float,
    stoploss: float,
    target: float,
    rr: float | None,
    strategy: str,
    quality: str,
) -> str:
    rr_str = f"{rr:.1f}" if rr is not None else "N/A"
    q_clause = _quality_clause(quality, rr)

    if signal == "BUY":
        if quality == "LOW_QUALITY":
            return f"Bullish setup detected, but {q_clause}"
        return (
            f"Enter above {entry} with stoploss at {stoploss}. "
            f"Target {target}. {q_clause} "
            f"{strategy} is the preferred strategy."
        )
    if signal == "SELL":
        if quality == "LOW_QUALITY":
            return f"Bearish setup detected, but {q_clause}"
        return (
            f"Enter below {entry} with stoploss at {stoploss}. "
            f"Target {target}. {q_clause} "
            f"{strategy} is the preferred strategy."
        )
    if signal == "NEUTRAL_BULLISH":
        if quality == "LOW_QUALITY":
            return f"Cautious bullish bias, but {q_clause}"
        return (
            f"Cautious bullish plan. Enter above {entry} with stoploss at {stoploss}. "
            f"Target {target}. {q_clause} "
            f"Reduce position size — conviction is moderate. {strategy} preferred."
        )
    if signal == "NEUTRAL_BEARISH":
        if quality == "LOW_QUALITY":
            return f"Cautious bearish bias, but {q_clause}"
        return (
            f"Cautious bearish plan. Enter below {entry} with stoploss at {stoploss}. "
            f"Target {target}. {q_clause} "
            f"Reduce position size — conviction is moderate. {strategy} preferred."
        )
    return "No trade recommended. Market lacks sufficient directional conviction."


def create_trade_plan(
    symbol: str = "NIFTY",
    capital: float = 100_000,
    risk_percent: float = 1.0,
) -> dict:
    """
    Build a complete, read-only trade plan for *symbol*.

    Does NOT place orders or interact with the Zerodha order API.
    All figures are for planning and sizing purposes only.
    """
    sym = symbol.upper()

    # --- setup (signal, entry, stoploss, target) ---
    setup = generate_trade_setup(symbol)
    if "error" in setup:
        return {"symbol": sym, "error": setup["error"]}

    signal: str = setup["signal"]
    confidence: int = setup["confidence"]
    entry: float = setup["entry"]
    stoploss: float = setup["stoploss"]
    target: float = setup["target"]
    data_basis = setup.get("data_basis")

    # --- risk score (visibility only — never affects trade logic) ---
    try:
        risk_score = _risk_score_context(symbol)
    except Exception:
        risk_score = None

    # --- NEUTRAL: no trade ---
    if signal in _NEUTRAL_SIGNALS:
        opts_ctx = _options_context(symbol)
        return {
            "symbol": sym,
            "signal": signal,
            "trade_allowed": False,
            "reason": "Market lacks sufficient directional conviction. No trade recommended.",
            "market_context": {
                "regime": None,
                **opts_ctx,
            },
            "risk_score": risk_score,
            "data_basis": data_basis,
            "summary": "No trade recommended. Market lacks sufficient directional conviction.",
        }

    # --- strategy (also carries regime via updated recommend_strategy) ---
    strat = recommend_strategy(symbol)
    if "error" in strat:
        return {"symbol": sym, "error": strat["error"]}

    regime: str = strat.get("regime", "")
    recommended_strategy: str = strat.get("recommended", strat.get("strategy", ""))
    secondary_strategy: str | None = strat.get("secondary")
    strategy_reason: str = strat.get("reason", "")

    # --- risk/reward ---
    rr_result = calculate_risk_reward(entry, stoploss, target)
    rr_val: float | None = rr_result.get("rr")

    # --- position sizing ---
    pos_result = calculate_position_size(capital, risk_percent, entry, stoploss)

    # --- options context (pcr, max_pain — index only) ---
    opts_ctx = _options_context(symbol)

    quality = _trade_quality(rr_val)
    trade_allowed = quality != "LOW_QUALITY"
    summary = _build_summary(signal, entry, stoploss, target, rr_val, recommended_strategy, quality)

    return {
        "symbol": sym,
        "trade_allowed": trade_allowed,
        "signal": signal,
        "trade_quality": quality,
        "confidence": confidence,
        "entry": entry,
        "stoploss": stoploss,
        "target": target,
        "risk_reward": {
            "risk": rr_result.get("risk"),
            "reward": rr_result.get("reward"),
            "rr": rr_val,
        },
        "position": {
            "capital": pos_result.get("capital"),
            "risk_percent": pos_result.get("risk_percent"),
            "risk_amount": pos_result.get("risk_amount"),
            "position_size": pos_result.get("position_size"),
        },
        "strategy": {
            "recommended": recommended_strategy,
            "secondary": secondary_strategy,
            "reason": strategy_reason,
        },
        "market_context": {
            "regime": regime,
            **opts_ctx,
        },
        "risk_score": risk_score,
        "data_basis": data_basis,
        "summary": summary,
    }
