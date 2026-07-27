"""Priority 8 — Mixed Timeframe Detection.

Priority 7's confidence adjuster already checks ONE binary case (does the
horizon's single CONTEXT-role fetch contradict the EXECUTION signal) as
part of computing a confidence penalty — useful, but not what this
priority actually asks for. The brief's example is a genuine N-timeframe
disagreement (daily bullish / 15m bearish / 5m bullish) with an explicit
instruction: "instead of averaging, return Mixed timeframe conflict,
confidence reduced, explain why." That needs comparing every one of a
horizon's policy-defined timeframes against each other, not a single
execution-vs-context binary check.

INTRADAY_OPTIONS is the only horizon in src.timeframe.policy with enough
distinct intervals (15minute EXECUTION, 5minute EXECUTION, 1minute
FINE_ENTRY, day CONTEXT) to build this for real — SWING/POSITIONAL only
have one EXECUTION and one/two CONTEXT interval(s), so for those this
degrades to the same binary check Priority 7 already does, just reported
through this module's shape instead.

Deliberately NOT fetched by default — this requires fetching every
policy-defined interval for the horizon (up to 4x the network/compute cost
of the single-EXECUTION-plus-one-CONTEXT fetch generate_trade_setup_tf
normally does), so it's opt-in via check_mixed_timeframes=True.
"""
from __future__ import annotations


def _direction_from_technicals(technicals: dict) -> str:
    """Bullish/bearish/neutral from price vs EMA20 — the same conservative,
    single-fact signal src.timeframe.confidence's context-conflict check
    already uses, reused here rather than inventing a second directional
    rule that could disagree with the first."""
    price = technicals.get("last_close")
    ema20 = technicals.get("ema_20")
    if price is None or ema20 is None:
        return "unknown"
    if price > ema20:
        return "bullish"
    if price < ema20:
        return "bearish"
    return "neutral"


def build_mixed_timeframe_report(technicals_by_interval: dict[str, dict]) -> dict:
    """Compare every fetched interval's direction and report agreement or
    conflict — never averages disagreeing timeframes into one number.

    technicals_by_interval: {interval: technicals_dict_or_error_dict} for
    every interval actually fetched (caller decides which/how many —
    typically all of a horizon's policy-defined intervals via
    src.timeframe.policy.POLICY).

    Returns {alignment, directions, conflict_detail}:
      alignment  — "ALIGNED" (all known directions agree, ignoring
                   "unknown"/fetch-failed entries), "CONFLICT" (at least
                   two known directions disagree), or "INSUFFICIENT_DATA"
                   (fewer than two intervals produced a known direction).
      directions — {interval: direction} for every interval that WAS
                   fetched, including "unknown"/"error" entries, so a
                   caller can see exactly what was checked and what
                   couldn't be.
      conflict_detail — human-readable explanation naming which intervals
                   disagreed, empty when ALIGNED or INSUFFICIENT_DATA.
    """
    directions: dict[str, str] = {}
    for interval, technicals in technicals_by_interval.items():
        if not isinstance(technicals, dict) or "error" in technicals:
            directions[interval] = "error"
        else:
            directions[interval] = _direction_from_technicals(technicals)

    known = {i: d for i, d in directions.items() if d in ("bullish", "bearish")}
    if len(known) < 2:
        return {"alignment": "INSUFFICIENT_DATA", "directions": directions, "conflict_detail": ""}

    unique_directions = set(known.values())
    if len(unique_directions) == 1:
        return {"alignment": "ALIGNED", "directions": directions, "conflict_detail": ""}

    bullish_intervals = sorted(i for i, d in known.items() if d == "bullish")
    bearish_intervals = sorted(i for i, d in known.items() if d == "bearish")
    detail = (
        f"{', '.join(bullish_intervals)} bullish vs {', '.join(bearish_intervals)} bearish — "
        "timeframes disagree; not averaged into a single reading."
    )
    return {"alignment": "CONFLICT", "directions": directions, "conflict_detail": detail}
