"""
Canonical symbol resolution — single source of truth (Phase 14.6).

Before this module, three separate `_INDEX_YF` tables (market/service.py,
tools/technicals.py, catalyst/constants.py) disagreed about which index aliases
existed. The result: the same alias resolved to different yfinance tickers — or
broke — depending on the entry point (e.g. get_quote("NIFTY") resolved to a bad
ticker while calculate_rsi("NIFTY") worked). This module unifies the index alias
table so index resolution is identical everywhere.

Two resolution semantics intentionally coexist for *equities*:
  - Market data (to_yf): BSE:RELIANCE → RELIANCE.BO  (quotes must honor BSE)
  - Catalyst (constants._to_yf_ticker): BSE:RELIANCE → RELIANCE.NS
    (news/earnings are per-company, keyed on the NSE listing)
Both now share the INDEX_YF table below; only the equity-suffix rule differs.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Index alias → yfinance ticker (union of all previously-divergent tables)
# ---------------------------------------------------------------------------

INDEX_YF: dict[str, str] = {
    "NIFTY":            "^NSEI",
    "NIFTY50":          "^NSEI",
    "NIFTY 50":         "^NSEI",
    "BANKNIFTY":        "^NSEBANK",
    "NIFTY BANK":       "^NSEBANK",
    "SENSEX":           "^BSESN",
    "FINNIFTY":         "^CNXFIN",
    "MIDCPNIFTY":       "^NSEMDCP50",
    "NIFTY IT":         "^CNXIT",
    "NIFTY MIDCAP 100": "^CNXMIDCAP",
    "NIFTY MIDCAP":     "^CNXMIDCAP",
}

INDEX_TICKERS: frozenset[str] = frozenset(INDEX_YF.values())

# Characters that mark a string as an already-resolved raw yfinance ticker
# (e.g. ^NSEI, CL=F, INFY.NS, DX-Y.NYB). Bare alphanumeric symbols lack these.
_RAW_TICKER_MARKERS = (".", "^", "=")


def parse(instrument: str) -> tuple[str | None, str]:
    """Return (exchange, symbol). exchange is None for raw yfinance tickers.

    The bare (no-colon) form is returned with original case preserved so raw
    tickers like 'DX-Y.NYB' pass through untouched.
    """
    if ":" in instrument:
        exchange, sym = instrument.split(":", 1)
        return exchange.upper(), sym.upper()
    return None, instrument


def to_yf(instrument: str) -> str:
    """Resolve any accepted symbol form to a yfinance ticker (market-data semantics).

    Handles: index aliases (NIFTY → ^NSEI), exchange-prefixed (NSE:INFY → INFY.NS,
    BSE:RELIANCE → RELIANCE.BO), already-suffixed/raw tickers (INFY.NS, ^NSEI,
    CL=F — passed through), and bare NSE equities (INFY → INFY.NS).
    """
    exchange, sym = parse(instrument)
    key = sym.upper().strip()

    if key in INDEX_YF:
        return INDEX_YF[key]
    if exchange == "NSE":
        return f"{key}.NS"
    if exchange == "BSE":
        return f"{key}.BO"
    if exchange is None:
        # Raw yfinance ticker carries a marker char → pass through unchanged.
        if any(ch in sym for ch in _RAW_TICKER_MARKERS):
            return sym
        # Bare alphanumeric, no exchange → assume NSE equity.
        return f"{key}.NS"
    return instrument


def is_nse_stock(instrument: str) -> bool:
    """True for an explicit NSE-prefixed equity (not an index alias)."""
    exchange, sym = parse(instrument)
    return exchange == "NSE" and sym.upper() not in INDEX_YF


def is_index(yf_ticker: str) -> bool:
    """True if the resolved yfinance ticker represents a known index."""
    return yf_ticker in INDEX_TICKERS


# Per-tool symbol format requirements (Phase 22 — symbol normalizer)
_TOOL_FORMATS: dict[str, str] = {
    "get_quote":             "NSE:{symbol}",
    "get_ohlc":              "NSE:{symbol}",
    "get_ltp":               "NSE:{symbol}",
    "analyze_technicals":    "{symbol}.NS",
    "calculate_rsi":         "{symbol}.NS",
    "calculate_ema":         "{symbol}.NS",
    "calculate_macd":        "{symbol}.NS",
    "calculate_adx":         "{symbol}.NS",
    "calculate_atr":         "{symbol}.NS",
    "get_historical_data":   "{symbol}.NS",
    "detect_market_regime":  "{symbol}",
    "generate_trade_setup":  "{symbol}.NS",
    "recommend_strategy":    "{symbol}",
}


def normalize_symbol(symbol: str, tool: str) -> tuple[str, bool]:
    """Return (normalized_symbol, was_corrected) for the given tool.

    Strips .NS/.BO suffix if present, upper-cases, applies the tool-specific
    format.  Indices (NIFTY, BANKNIFTY, etc.) are passed through via to_yf
    regardless of tool format.  Symbols that resolve to a price < 1 are likely
    USD tickers; callers should set data_quality='INVALID' in that case.

    Returns the original symbol unchanged if the tool is not in the format map.
    """
    raw = symbol.strip()
    _, base = parse(raw)
    base_upper = base.upper().removesuffix(".NS").removesuffix(".BO")

    # Index aliases pass through canonical resolution
    if base_upper in INDEX_YF:
        normalized = INDEX_YF[base_upper]
        return normalized, (normalized != raw)

    fmt = _TOOL_FORMATS.get(tool)
    if fmt is None:
        return raw, False

    normalized = fmt.format(symbol=base_upper)
    return normalized, (normalized != raw)
