"""Priority 4 — Recommendation Evidence Engine.

Turns _score_setup's internal tagged evidence (indicator, polarity, points,
text — see src.analysis.regime._score_setup's `_log` helper) plus a CONTEXT-
role read into the brief's evidence/context/ignored/rejected structure:

  BUY CE, Confidence 74%
  Evidence: above VWAP, EMA20 support, bullish BOS, ADX(15m)=29
  Context: Daily trend bullish, Weekly neutral
  Ignored: Daily ADX, Yesterday's candle
  Rejected: Missing options chain, Stale IV

"Ignored" here means: the indicator was fetched and evaluated, but
contributed zero points either way (polarity == "neutral" in the tagged
evidence) — it did not silently vanish, it was explicitly weighed and found
non-contributory. "Rejected" means a CONTEXT fetch was attempted and failed
outright (Priority 3's staleness refusal, or a plain fetch error) — the
caller can see WHAT was rejected and WHY, not just that the setup is missing
context.

Consumed only by generate_trade_setup_tf — generate_trade_setup (daily-only,
unchanged) does not use this; its `reasoning` list[str] output is untouched.
"""
from __future__ import annotations


def build_evidence(evidence: list[dict], signal: str) -> dict:
    """Split _score_setup's tagged evidence into evidence_for/evidence_against/
    ignored, relative to `signal`'s direction.

    A bullish-polarity line is "for" when signal is BUY/NEUTRAL_BULLISH and
    "against" when signal is SELL/NEUTRAL_BEARISH (and vice versa for
    bearish-polarity lines) — evidence is evaluated against the DIRECTION
    the setup actually settled on, not just re-sorted by its own polarity in
    isolation, so a caller sees exactly what supported vs. undercut the
    specific call that was made.
    """
    bullish_signal = signal in {"BUY", "NEUTRAL_BULLISH"}
    bearish_signal = signal in {"SELL", "NEUTRAL_BEARISH"}

    evidence_for: list[dict] = []
    evidence_against: list[dict] = []
    ignored: list[dict] = []

    for item in evidence:
        polarity = item.get("polarity")
        entry = {"indicator": item.get("indicator"), "text": item.get("text"), "points": item.get("points")}
        if polarity == "neutral":
            ignored.append(entry)
        elif polarity == "bullish":
            (evidence_for if bullish_signal else evidence_against if bearish_signal else ignored).append(entry)
        elif polarity == "bearish":
            (evidence_for if bearish_signal else evidence_against if bullish_signal else ignored).append(entry)
        else:
            ignored.append(entry)

    return {
        "evidence_for": evidence_for,
        "evidence_against": evidence_against,
        "ignored": ignored,
    }


def build_context_summary(context_technicals: dict | None, context_error: str | None) -> dict:
    """Build the `context`/`rejected` portion from an attempted CONTEXT-role
    fetch. context_technicals is get_technicals()'s result when it
    succeeded (possibly with a staleness_caution); context_error is set
    instead when the fetch itself failed or was refused."""
    if context_error is not None:
        return {"context": [], "rejected": [context_error]}

    if context_technicals is None:
        return {"context": [], "rejected": []}

    interval = context_technicals.get("interval", "context")
    rsi = context_technicals.get("rsi_14")
    ema20 = context_technicals.get("ema_20")
    price = context_technicals.get("last_close")

    lines: list[str] = []
    if price is not None and ema20 is not None:
        lines.append(f"{interval}: price is {'above' if price > ema20 else 'below'} EMA20")
    if rsi is not None:
        lines.append(f"{interval}: RSI {rsi:.0f}")

    caution = context_technicals.get("staleness_caution")
    rejected = [caution] if caution else []

    return {"context": lines, "rejected": rejected}
