"""
Catalyst Intelligence constants — Phase 11B.

Centralises keyword sets, symbol resolution, and catalyst priority weights
so that news.py, earnings.py, and event_risk.py share a single source of truth.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Index alias → yfinance ticker
# ---------------------------------------------------------------------------

# Index alias table is the canonical one in src/market/symbols.py.
# Catalyst keeps its own NSE-centric equity rule (BSE:X → X.NS, since news and
# earnings are per-company and keyed on the NSE listing), but shares the index
# table so index aliases never diverge from the rest of the system.
from src.market.symbols import INDEX_YF as _INDEX_YF, is_index  # noqa: F401


def _to_yf_ticker(symbol: str) -> str:
    """Normalise a symbol to a yfinance-compatible ticker (catalyst semantics).

    Handles: bare NSE symbols (INFY), exchange-prefixed (NSE:INFY, BSE:RELIANCE),
    already-suffixed (INFY.NS), and index aliases (NIFTY → ^NSEI).
    Idempotent: calling twice does not double the .NS suffix.

    Note: unlike market data resolution, a BSE: prefix resolves to .NS here —
    catalyst data (news/earnings) is keyed on the NSE listing of the company.
    """
    s = symbol.upper().strip()
    # Strip exchange prefix
    if ":" in s:
        s = s.split(":", 1)[1]
    # Index alias takes priority
    if s in _INDEX_YF:
        return _INDEX_YF[s]
    # Already a suffixed equity or raw yfinance ticker (^XYZ, CL=F, etc.)
    if s.endswith(".NS") or s.endswith(".BO") or s.startswith("^") or "=" in s:
        return s
    # Default: NSE equity
    return s + ".NS"


# ---------------------------------------------------------------------------
# News sentiment keywords
# ---------------------------------------------------------------------------

_POSITIVE_KEYWORDS: frozenset[str] = frozenset({
    "beat", "beats", "record", "profit", "growth", "upgrade", "upgraded",
    "buyback", "dividend", "win", "wins", "outperform", "strong", "acquisition",
    "expansion", "order", "contract", "approve", "approved", "rally",
    "surge", "raise", "raised", "positive", "upbeat", "gains", "gain",
    "recovery", "turnaround", "momentum", "inflow", "invest",
})

_NEGATIVE_KEYWORDS: frozenset[str] = frozenset({
    "loss", "losses", "miss", "misses", "downgrade", "downgraded", "fraud",
    "resign", "resigns", "declined", "decline", "probe", "penalty", "penalties",
    "investigation", "cut", "cuts", "weak", "underperform", "default",
    "bankruptcy", "recall", "write-off", "writeoff", "outflow", "slump",
    "slumps", "fall", "falls", "crash", "plunge", "plunges", "concern",
    "concerns", "risk", "risks", "lawsuit", "fine", "fined", "delay", "delays",
})

# ---------------------------------------------------------------------------
# Catalyst type priority (for highest_impact_catalyst selection)
# ---------------------------------------------------------------------------

CATALYST_PRIORITY: dict[str, int] = {
    "EARNINGS": 100,
    "SPLIT":     70,
    "DIVIDEND":  40,
}
