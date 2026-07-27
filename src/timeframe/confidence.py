"""Priority 7 — Recommendation Confidence rework.

_score_setup's raw confidence (src/analysis/regime.py) is a hand-weighted
point sum with no backtested basis — the same kind of score Phase 20A/21
found lacked demonstrated directional edge for other indicators in this
codebase, and the same category Phase 22F deleted outright at one tool
boundary (detect_market_regime). This module does not re-legitimize that
score by dressing it up; it does the one thing the brief actually asks for
that's honest to do here: REDUCE confidence when real, already-computed
evidence-quality problems exist, and say so explicitly. It never increases
confidence — same asymmetry decision as Priority 4's calibration fix
(Phase 1's H5): shrinking on a real problem is a legitimate safeguard,
inventing a boost is not.

What this can and cannot check, honestly:
  - CAN check (computed earlier in this same pipeline): mixed-timeframe
    conflict (context contradicts the execution signal's direction),
    missing/rejected indicator data, internal indicator disagreement
    (non-trivial evidence_against next to evidence_for), and the Decision
    Trace's own data_quality verdict.
  - CANNOT check here: liquidity, bid-ask spread, IV, near-expiry
    uncertainty — those are options-chain properties, and this function
    operates on pure technicals with no options chain in scope at all. The
    brief lists these as confidence-reducing factors; this module does NOT
    fabricate a check for data it never receives. src/strategy/builder.py's
    liquidity_warning (Audit-H4, Phase 1) is the actual place that data
    exists and is checked — a genuinely different code path, not merged
    into this one to avoid faking a signal this function doesn't have.
"""
from __future__ import annotations

# Points subtracted from the raw 0-85 confidence for each real, checkable
# problem. Additive across multiple simultaneous problems; floored at 0
# (never negative) by the caller.
_MIXED_TIMEFRAME_PENALTY = 15
_MISSING_DATA_PENALTY = 10
_INTERNAL_CONFLICT_PENALTY = 10
_DEGRADED_DATA_QUALITY_PENALTY = 15


def _context_conflicts_with_signal(context_lines: list[str], signal: str) -> bool:
    """True if any context line's directional word contradicts signal's
    direction. Deliberately simple/conservative — only flags an EXPLICIT
    'above'/'below' EMA20 contradiction in the context summary text (see
    src.timeframe.evidence.build_context_summary's own wording), not an
    inferred contradiction from anything subtler."""
    bullish_signal = signal in {"BUY", "NEUTRAL_BULLISH"}
    bearish_signal = signal in {"SELL", "NEUTRAL_BEARISH"}
    if not (bullish_signal or bearish_signal):
        return False
    for line in context_lines:
        lower = line.lower()
        if "below ema20" in lower and bullish_signal:
            return True
        if "above ema20" in lower and bearish_signal:
            return True
    return False


def adjust_confidence(setup: dict, decision_trace: dict) -> dict:
    """Return {adjusted_confidence, raw_confidence, penalties: [{reason, points}]}.

    `setup` must already have signal/confidence/evidence_for/evidence_against/
    context (Priority 4's fields). `decision_trace` is Priority 5's trace for
    the same setup — reused for its data_quality verdict and
    indicators_rejected count rather than recomputing them.
    """
    raw = setup.get("confidence", 0)
    penalties: list[dict] = []

    if _context_conflicts_with_signal(setup.get("context", []), setup.get("signal", "")):
        penalties.append({
            "reason": "Higher-timeframe context contradicts this setup's signal direction",
            "points": _MIXED_TIMEFRAME_PENALTY,
        })

    if decision_trace.get("indicators_rejected"):
        penalties.append({
            "reason": (
                f"{len(decision_trace['indicators_rejected'])} indicator(s) had no "
                "usable value for this candle"
            ),
            "points": _MISSING_DATA_PENALTY,
        })

    evidence_for = setup.get("evidence_for", [])
    evidence_against = setup.get("evidence_against", [])
    if evidence_for and evidence_against and len(evidence_against) >= len(evidence_for):
        penalties.append({
            "reason": (
                f"{len(evidence_against)} indicator(s) contradict the signal versus "
                f"{len(evidence_for)} supporting it — internally conflicted"
            ),
            "points": _INTERNAL_CONFLICT_PENALTY,
        })

    if decision_trace.get("data_quality") == "DEGRADED":
        penalties.append({
            "reason": "Decision trace data_quality is DEGRADED (stale or unknown-freshness indicator present)",
            "points": _DEGRADED_DATA_QUALITY_PENALTY,
        })

    total_penalty = sum(p["points"] for p in penalties)
    adjusted = max(0, raw - total_penalty)

    return {
        "raw_confidence": raw,
        "adjusted_confidence": adjusted,
        "penalties": penalties,
        "not_checked": [
            "options liquidity/spread (no options chain data in scope for this setup)",
            "implied volatility / near-expiry uncertainty (same reason)",
        ],
    }
