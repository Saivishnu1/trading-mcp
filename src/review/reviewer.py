"""
Trade Review Engine — Phase 7.

Evaluates whether an existing trade's original thesis remains valid
given current market conditions. Does NOT place or modify orders.

Reuses:
  detect_market_regime()   → price, rsi, ema20, ema50, adx
  generate_trade_setup()   → current signal, confidence
  recommend_strategy()     → current strategy, regime
  create_trade_plan()      → trade_quality
"""

from __future__ import annotations

from src.analysis.regime import (
    detect_market_regime,
    generate_trade_setup,
    recommend_strategy,
)
from src.planner.trade_plan import create_trade_plan

# ---------------------------------------------------------------------------
# Thesis evaluation
# ---------------------------------------------------------------------------

_LONG_MAP: dict[str, tuple[str, str]] = {
    "BUY":              ("VALID",       "HOLD"),
    "NEUTRAL_BULLISH":  ("WEAKENING",   "HOLD"),
    "NEUTRAL":          ("WEAKENING",   "REDUCE"),
    "NEUTRAL_BEARISH":  ("INVALIDATED", "EXIT"),
    "SELL":             ("INVALIDATED", "EXIT"),
}

_SHORT_MAP: dict[str, tuple[str, str]] = {
    "SELL":             ("VALID",       "HOLD"),
    "NEUTRAL_BEARISH":  ("WEAKENING",   "HOLD"),
    "NEUTRAL":          ("WEAKENING",   "REDUCE"),
    "NEUTRAL_BULLISH":  ("INVALIDATED", "EXIT"),
    "BUY":              ("INVALIDATED", "EXIT"),
}


def _evaluate(direction: str, signal: str) -> tuple[str, str]:
    lookup = _LONG_MAP if direction == "LONG" else _SHORT_MAP
    return lookup.get(signal, ("WEAKENING", "REDUCE"))


# ---------------------------------------------------------------------------
# Invalidation conditions
# ---------------------------------------------------------------------------

def _invalidation_conditions(direction: str, ema20: float, ema50: float, rsi: float) -> list[str]:
    if direction == "LONG":
        return [
            f"Price closes below EMA20 ({ema20:.2f})",
            f"Price closes below EMA50 ({ema50:.2f})",
            "RSI drops below 45",
            "Signal changes to SELL or NEUTRAL_BEARISH",
        ]
    else:  # SHORT
        return [
            f"Price closes above EMA20 ({ema20:.2f})",
            f"Price closes above EMA50 ({ema50:.2f})",
            "RSI rises above 55",
            "Signal changes to BUY or NEUTRAL_BULLISH",
        ]


# ---------------------------------------------------------------------------
# Reasoning
# ---------------------------------------------------------------------------

def _reasoning(
    direction: str,
    signal: str,
    regime: str,
    rsi: float,
    ema20: float,
    ema50: float,
    adx: float,
    price: float,
    thesis_status: str,
) -> list[str]:
    lines: list[str] = []

    # Signal alignment
    if thesis_status == "VALID":
        lines.append(
            f"Current signal is {signal}, which aligns with the {direction} direction."
        )
    elif thesis_status == "WEAKENING":
        lines.append(
            f"Current signal is {signal} — directional conviction has weakened."
        )
    else:
        lines.append(
            f"Current signal is {signal}, which OPPOSES the {direction} direction."
        )

    # Regime
    lines.append(f"Market regime is {regime}.")

    # Price vs EMAs
    if price > ema20 and price > ema50:
        lines.append(
            f"Price ({price:.2f}) is above both EMA20 ({ema20:.2f}) and EMA50 ({ema50:.2f}) — bullish structure."
        )
    elif price < ema20 and price < ema50:
        lines.append(
            f"Price ({price:.2f}) is below both EMA20 ({ema20:.2f}) and EMA50 ({ema50:.2f}) — bearish structure."
        )
    elif price > ema20:
        lines.append(
            f"Price ({price:.2f}) is above EMA20 ({ema20:.2f}) but below EMA50 ({ema50:.2f}) — mixed structure."
        )
    else:
        lines.append(
            f"Price ({price:.2f}) is below EMA20 ({ema20:.2f}) but above EMA50 ({ema50:.2f}) — mixed structure."
        )

    # RSI
    if rsi > 60:
        lines.append(f"RSI at {rsi:.2f} is strong — momentum favors bulls.")
    elif rsi > 55:
        lines.append(f"RSI at {rsi:.2f} is mildly bullish.")
    elif rsi > 45:
        lines.append(f"RSI at {rsi:.2f} is neutral.")
    elif rsi > 40:
        lines.append(f"RSI at {rsi:.2f} is mildly bearish.")
    else:
        lines.append(f"RSI at {rsi:.2f} is weak — momentum favors bears.")

    # ADX
    if adx > 25:
        lines.append(f"ADX at {adx:.2f} confirms trending conditions.")
    elif adx > 20:
        lines.append(f"ADX at {adx:.2f} indicates moderate trend strength.")
    else:
        lines.append(f"ADX at {adx:.2f} indicates low trend strength — range-bound market.")

    return lines


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _summary(direction: str, thesis_status: str, action: str, signal: str) -> str:
    direction_word = "bullish" if direction == "LONG" else "bearish"

    if thesis_status == "VALID":
        return (
            f"Original {direction_word} thesis remains intact. "
            f"Continue holding while signal remains {signal}."
        )
    if thesis_status == "WEAKENING" and action == "HOLD":
        return (
            "Thesis is weakening but direction is preserved. "
            "Consider reducing position size if conditions deteriorate further."
        )
    if thesis_status == "WEAKENING" and action == "REDUCE":
        return (
            "Directional conviction has faded to neutral. "
            "Consider reducing exposure and tightening stops."
        )
    # INVALIDATED
    return (
        f"Trade thesis has been invalidated. "
        f"Current signal ({signal}) opposes the original {direction_word} direction. "
        "Exit the position."
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def review_trade(
    symbol: str,
    direction: str,
    entry_price: float | None = None,
    holding_days: int | None = None,
) -> dict:
    """
    Evaluate whether an existing trade's original thesis is still valid.

    Does NOT place or modify orders.
    All output is for review and decision-support only.
    """
    sym = symbol.upper()
    direction = direction.upper()

    if direction not in ("LONG", "SHORT"):
        return {"symbol": sym, "error": "direction must be LONG or SHORT"}

    # --- Reuse existing analysis modules ---
    regime_result = detect_market_regime(symbol)
    if "error" in regime_result:
        return {"symbol": sym, "error": regime_result["error"]}

    setup = generate_trade_setup(symbol)
    if "error" in setup:
        return {"symbol": sym, "error": setup["error"]}

    strat = recommend_strategy(symbol)
    if "error" in strat:
        return {"symbol": sym, "error": strat["error"]}

    plan = create_trade_plan(symbol)

    # --- Extract values ---
    price: float   = regime_result["price"]
    rsi: float     = regime_result["rsi"]
    ema20: float   = regime_result["ema20"]
    ema50: float   = regime_result["ema50"]
    adx: float     = regime_result["adx"]

    signal: str     = setup["signal"]
    confidence: int = min(100, setup["confidence"])

    current_regime:   str       = strat.get("regime", regime_result.get("regime", ""))
    current_strategy: str       = strat.get("recommended", strat.get("strategy", ""))
    trade_quality:    str | None = plan.get("trade_quality")

    # --- Thesis evaluation ---
    thesis_status, action = _evaluate(direction, signal)

    # --- Build response ---
    result: dict = {
        "symbol":                sym,
        "direction":             direction,
        "current_price":         round(price, 2),
        "current_signal":        signal,
        "current_regime":        current_regime,
        "thesis_status":         thesis_status,
        "confidence":            confidence,
        "action":                action,
        "trade_quality":         trade_quality,
        "current_strategy":      current_strategy,
        "invalidation_conditions": _invalidation_conditions(direction, ema20, ema50, rsi),
        "reasoning":             _reasoning(
                                     direction, signal, current_regime,
                                     rsi, ema20, ema50, adx, price, thesis_status,
                                 ),
        "summary":               _summary(direction, thesis_status, action, signal),
    }

    # Optional: P&L when entry_price is known
    if entry_price is not None:
        ep = float(entry_price)
        if direction == "LONG":
            pnl_pct = ((price - ep) / ep) * 100
        else:
            pnl_pct = ((ep - price) / ep) * 100
        result["entry_price"]        = round(ep, 4)
        result["current_pnl_percent"] = round(pnl_pct, 2)

    if holding_days is not None:
        result["holding_days"] = int(holding_days)

    return result
