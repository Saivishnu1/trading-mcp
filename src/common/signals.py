"""
Signal taxonomy — single source of truth (Phase 14.6).

The set of signal values emitted by generate_trade_setup, and their mapping to
a LONG/SHORT direction, was previously re-encoded independently in
recommendations/engine.py, planner/trade_plan.py and review/reviewer.py. A new
signal value had to be added in every copy or it would silently route wrong.

This module is the canonical consumer-side classification of those strings.
"""
from __future__ import annotations

# Directional signals that imply a long / short bias.
LONG_SIGNALS: frozenset[str] = frozenset({"BUY", "NEUTRAL_BULLISH"})
SHORT_SIGNALS: frozenset[str] = frozenset({"SELL", "NEUTRAL_BEARISH"})

# Signals that produce no trade vs. an actionable directional plan.
NEUTRAL_SIGNALS: frozenset[str] = frozenset({"NEUTRAL"})
DIRECTIONAL_SIGNALS: frozenset[str] = LONG_SIGNALS | SHORT_SIGNALS


def direction_from_signal(signal: str) -> str | None:
    """Return 'LONG', 'SHORT', or None for a setup signal."""
    if signal in LONG_SIGNALS:
        return "LONG"
    if signal in SHORT_SIGNALS:
        return "SHORT"
    return None
