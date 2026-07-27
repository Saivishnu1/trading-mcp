"""Priority 6 — Trade Thesis Engine.

The only existing prior art anywhere in this codebase (per the Priority 0
survey) is src/review/reviewer.py's _invalidation_conditions — a real,
concrete "why the trade fails" list (EMA20/EMA50/RSI thresholds tied to
direction), used only for reviewing an ALREADY-OPEN position, daily-only,
with no "why the trade exists" counterpart anywhere.

This module builds both halves for a NEW setup (generate_trade_setup_tf,
any EXECUTION-role timeframe):
  - the "exists because" half is not re-derived — it's Priority 4's own
    evidence_for, reframed as thesis language, since that's already exactly
    "what supported the direction this setup settled on."
  - the "invalidation" half generalizes reviewer.py's pattern: concrete,
    checkable conditions (price vs EMA20/EMA50, RSI crossing back through
    its own threshold, signal reversal) tied to the setup's OWN timeframe's
    technicals — not hardcoded to daily like reviewer.py's version.

Not wired into review_trade/reviewer.py — that module keeps reviewing
EXISTING positions with its own established logic. This is for a fresh
setup produced via generate_trade_setup_tf, so a caller gets the thesis at
the moment of entry, ready to be re-checked later (e.g. by a future
position-monitoring consumer of this same module, not built here).
"""
from __future__ import annotations


def build_trade_thesis(setup: dict, technicals: dict) -> dict:
    """Build the Trade Thesis for one generate_trade_setup_tf() result.

    `setup` is the already-scored result (has `signal`, `evidence_for`).
    `technicals` is the EXECUTION-role technicals that produced it (has
    ema_20, ema_50, rsi_14) — the same dict generate_trade_setup_tf already
    fetched, passed through so invalidation conditions are computed from
    numbers, not re-derived from prose.
    """
    signal = setup.get("signal", "NEUTRAL")
    ema20 = technicals.get("ema_20")
    ema50 = technicals.get("ema_50")
    rsi = technicals.get("rsi_14")

    bullish = signal in {"BUY", "NEUTRAL_BULLISH"}
    bearish = signal in {"SELL", "NEUTRAL_BEARISH"}

    thesis_because = [e["text"] for e in setup.get("evidence_for", [])]

    invalidation: list[str] = []
    if bullish:
        if ema20 is not None:
            invalidation.append(f"Price closes below EMA20 ({ema20:.2f})")
        if ema50 is not None:
            invalidation.append(f"Price closes below EMA50 ({ema50:.2f})")
        invalidation.append("RSI drops below 45")
        invalidation.append("Signal flips to SELL or NEUTRAL_BEARISH on a later read")
    elif bearish:
        if ema20 is not None:
            invalidation.append(f"Price closes above EMA20 ({ema20:.2f})")
        if ema50 is not None:
            invalidation.append(f"Price closes above EMA50 ({ema50:.2f})")
        invalidation.append("RSI rises above 55")
        invalidation.append("Signal flips to BUY or NEUTRAL_BULLISH on a later read")
    else:
        invalidation.append("No directional thesis to invalidate — signal is NEUTRAL")

    # Universal invalidation triggers the brief calls out that this codebase
    # cannot compute from technicals alone (they belong to the actual order,
    # not the setup) — named explicitly as a gap rather than fabricated.
    invalidation.append(
        "Premium/price stop-loss is hit (set at order placement — this "
        "engine does not track a live position's stop)"
    )
    invalidation.append(
        "Time stop reached (e.g. no follow-through by a defined session/day "
        "count — set by the trader, not computed here)"
    )

    return {
        "direction": "LONG" if bullish else "SHORT" if bearish else "NONE",
        "thesis_because": thesis_because,
        "invalidation_conditions": invalidation,
    }
