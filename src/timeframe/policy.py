"""Timeframe Engine — Priority 1 policy table.

Encodes, per holding-horizon, which timeframes may drive an ENTRY decision
("execution" role) versus which may only inform/contextualize one ("context"
role) but must never gate or trigger a trade by themselves.

Before this module existed, the one rule of this kind in the codebase (Phase
19: "weekly is context only for recommend_trade") lived as a single inline
`if signal in _LONG_SIGNALS and weekly_regime in (...)` conditional inside
src/recommendations/engine.py — correct for that one function, invisible and
unenforceable everywhere else. This module is the single source of truth so
every consumer (not just recommend_trade) can ask the same question.

Interval strings match src/chart_awareness/data_fetcher.py's supported set
exactly: 1minute, 3minute, 5minute, 10minute, 15minute, 30minute, 60minute,
day, week, month. There is no 4-hour interval anywhere in this codebase's
data fetchers (Zerodha/INDmoney/yfinance) — SWING's "4H execution" from the
original brief is not implementable without a new data source, so SWING's
execution role uses "day" (the finest interval this codebase can actually
fetch reliably at swing-relevant history depth) and this gap is called out
explicitly rather than faked with an interval nothing can serve.
"""
from __future__ import annotations

from enum import Enum


class HoldingHorizon(str, Enum):
    """How long the position is intended to be held. Distinct from
    src.journal.db's `trade_type` column (EQUITY/OPTIONS/FUTURES — an
    instrument class), which this deliberately does not reuse or collide
    with — a horizon and an instrument class are independent axes."""

    INTRADAY_OPTIONS = "INTRADAY_OPTIONS"
    SWING = "SWING"
    POSITIONAL = "POSITIONAL"


class TimeframeRole(str, Enum):
    EXECUTION = "EXECUTION"   # may trigger/gate an entry
    FINE_ENTRY = "FINE_ENTRY"  # optional, finer-grained entry timing within an EXECUTION signal
    CONTEXT = "CONTEXT"       # informs conviction/sizing only — must never gate entry alone
    DISALLOWED = "DISALLOWED"  # not part of this horizon's policy at all


# All interval strings this codebase's data fetchers can actually serve
# (src/chart_awareness/data_fetcher.py's _ZERODHA_INTERVAL /
# _INDMONEY_INTERVAL / _YFINANCE_INTERVAL keys — kept in sync manually since
# duplicating that import here would create a fetcher<->policy coupling in
# the wrong direction; policy should not import from data_fetcher).
KNOWN_INTERVALS = frozenset({
    "1minute", "3minute", "5minute", "10minute", "15minute", "30minute",
    "60minute", "day", "week", "month",
})


# {horizon: {interval: role}}. An interval absent from a horizon's dict is
# DISALLOWED for that horizon — not a silent default, not fetchable at all
# for this kind of decision.
POLICY: dict[HoldingHorizon, dict[str, TimeframeRole]] = {
    HoldingHorizon.INTRADAY_OPTIONS: {
        "15minute": TimeframeRole.EXECUTION,
        "5minute": TimeframeRole.EXECUTION,
        "1minute": TimeframeRole.FINE_ENTRY,
        "day": TimeframeRole.CONTEXT,
    },
    HoldingHorizon.SWING: {
        # No 4-hour interval exists in this codebase's data fetchers (see
        # module docstring) — "day" is the finest interval available for
        # swing execution, not a substitute chosen for convenience.
        "day": TimeframeRole.EXECUTION,
        "week": TimeframeRole.CONTEXT,
    },
    HoldingHorizon.POSITIONAL: {
        "day": TimeframeRole.EXECUTION,
        "week": TimeframeRole.CONTEXT,
        "month": TimeframeRole.CONTEXT,
    },
}


def role_for(horizon: HoldingHorizon, interval: str) -> TimeframeRole:
    """Return the role `interval` plays for `horizon`. DISALLOWED if this
    interval has no defined role under this horizon at all (not merely
    "not preferred" — genuinely outside this horizon's policy)."""
    return POLICY.get(horizon, {}).get(interval, TimeframeRole.DISALLOWED)


def can_gate_entry(horizon: HoldingHorizon, interval: str) -> bool:
    """True only for EXECUTION/FINE_ENTRY — the two roles allowed to trigger
    or block an entry decision. CONTEXT and DISALLOWED must never gate."""
    return role_for(horizon, interval) in (TimeframeRole.EXECUTION, TimeframeRole.FINE_ENTRY)


def execution_intervals(horizon: HoldingHorizon) -> list[str]:
    return [i for i, r in POLICY.get(horizon, {}).items() if r == TimeframeRole.EXECUTION]


def context_intervals(horizon: HoldingHorizon) -> list[str]:
    return [i for i, r in POLICY.get(horizon, {}).items() if r == TimeframeRole.CONTEXT]
