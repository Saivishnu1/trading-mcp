"""Priority 5 — Decision Trace.

No analog exists elsewhere in this codebase (confirmed by the Priority 0
survey): every existing recommendation-shaped output is a terminal dict
with prose lists, not a replayable, purpose-built audit record. This module
does not gather any new data — everything a Decision Trace needs was
already produced by Priorities 1-4 (Timeframe Engine, per-indicator
metadata, freshness gating, Evidence Engine) sitting inside
generate_trade_setup_tf's own output. This is a pure reformatting layer:
it takes that output and restructures it into one coherent record designed
to answer "why did this setup say what it said, and what was left out" at
a glance, rather than requiring a reader to reconstruct that by cross-
referencing five separate fields.

Deliberately NOT wired into generate_trade_setup (the daily-only, unchanged
function) — consistent with every prior priority in this phase, this stays
scoped to the new Timeframe Engine path.
"""
from __future__ import annotations


def build_decision_trace(setup: dict) -> dict:
    """Build the Decision Trace for one generate_trade_setup_tf() result.

    `setup` must be a result that did NOT itself contain an "error" key —
    callers should build a trace only for a setup that actually produced a
    recommendation. Tracing an error result is meaningless (there is no
    recommendation to audit) and is the caller's responsibility to skip.

    Fields (per the phase brief): trade_type, recommendation, confidence,
    indicators_used, indicators_rejected, timeframes, data_timestamps,
    evidence, counter_evidence, assumptions, data_quality.
    """
    indicator_metadata = setup.get("indicator_metadata", [])

    indicators_used = [
        {"indicator": m["indicator"], "value": m["value"], "timeframe": m["timeframe"], "freshness": m["freshness"]}
        for m in indicator_metadata
        if m.get("value") is not None
    ]
    indicators_rejected = [
        {"indicator": m["indicator"], "reason": "value unavailable (None) for this candle/timeframe"}
        for m in indicator_metadata
        if m.get("value") is None
    ]

    timeframes = {
        "execution": setup.get("interval"),
        "execution_role": setup.get("role"),
        "context_intervals": sorted({m["timeframe"] for m in indicator_metadata if m.get("timeframe")}),
    }

    data_timestamps = {
        "candle_timestamp": setup.get("data_basis", {}).get("last_candle_datetime")
                              or setup.get("data_basis", {}).get("last_candle_date"),
        "staleness_days": setup.get("data_basis", {}).get("staleness_days"),
    }

    # Assumptions: things this trace's own construction had to take for
    # granted rather than verify — explicit per the phase's "expose every
    # hidden assumption" goal. Kept short and mechanical: what's true about
    # HOW this setup was produced, not a restatement of the evidence itself.
    assumptions: list[str] = [
        f"Regime classification computed from the same {setup.get('interval')} "
        "timeframe's technicals as the setup itself (not a different, "
        "possibly-daily default).",
    ]
    if not setup.get("context"):
        assumptions.append(
            "No usable CONTEXT-role read was available — this setup's "
            "confidence reflects EXECUTION-timeframe evidence only, with no "
            "higher-timeframe confirmation or contradiction factored in."
        )
    if setup.get("rejected"):
        assumptions.append(
            f"{len(setup['rejected'])} context/data source(s) were rejected "
            "(see rejected) — the setup proceeded without them rather than "
            "blocking on their absence, since they are CONTEXT-role, not "
            "EXECUTION-role, inputs."
        )

    stale_count = sum(1 for m in indicator_metadata if m.get("freshness") == "STALE")
    unknown_count = sum(1 for m in indicator_metadata if m.get("freshness") == "UNKNOWN")
    if stale_count or unknown_count:
        data_quality = "DEGRADED"
    elif indicators_rejected:
        data_quality = "PARTIAL"
    else:
        data_quality = "VALID"

    return {
        "trade_type": setup.get("horizon"),
        "recommendation": setup.get("signal"),
        "confidence": setup.get("confidence"),
        "indicators_used": indicators_used,
        "indicators_rejected": indicators_rejected,
        "timeframes": timeframes,
        "data_timestamps": data_timestamps,
        "evidence": setup.get("evidence_for", []),
        "counter_evidence": setup.get("evidence_against", []),
        "assumptions": assumptions,
        "data_quality": data_quality,
    }
