"""
Phase 22 — Trust metadata layer.

Every MCP tool response is wrapped:
  { "data": <existing output>, "meta": <trust context> }

build_meta()           — assemble the meta dict for a tool call
wrap()                 — wrap data + meta into the canonical response envelope
is_market_hours()      — True during NSE session (09:15–15:30 IST)
detect_data_quality()  — inspect a data dict for NaN / USD ticker / staleness
"""
from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Type constants
# ---------------------------------------------------------------------------

# Fundamental observable facts: price, volume, OI, FII/DII flows
TYPE_FACT = "FACT"
# Mathematically derived from facts: RSI, EMA, ADX, MACD, ATR
TYPE_INDICATOR = "INDICATOR"
# Human or model interpretation of indicators: regime label, PCR note
TYPE_INTERPRETATION = "INTERPRETATION"
# Directional forecast with claimed probability — DEPRECATED
TYPE_PREDICTION = "PREDICTION"

# ---------------------------------------------------------------------------
# Validation status constants
# ---------------------------------------------------------------------------

VALIDATION_VERIFIED = "VERIFIED"
VALIDATION_COMPUTED = "MATHEMATICALLY_COMPUTED"
VALIDATION_UNVALIDATED = "UNVALIDATED"
VALIDATION_DEPRECATED = "DEPRECATED"

# ---------------------------------------------------------------------------
# Data quality constants
# ---------------------------------------------------------------------------

DQ_VALID = "VALID"
DQ_NAN = "NaN_DETECTED"
DQ_STALE = "STALE"
DQ_PARTIAL = "PARTIAL"
DQ_INVALID = "INVALID"

# ---------------------------------------------------------------------------
# Research status constants
# ---------------------------------------------------------------------------

RS_EXPERIMENTAL = "EXPERIMENTAL"
RS_INVALIDATED = "INVALIDATED"
RS_NOT_TESTED = "NOT_TESTED"

# ---------------------------------------------------------------------------
# Market hours (IST = UTC+5:30)
# ---------------------------------------------------------------------------

_IST = timezone(timedelta(hours=5, minutes=30))
_MARKET_OPEN_H, _MARKET_OPEN_M = 9, 15
_MARKET_CLOSE_H, _MARKET_CLOSE_M = 15, 30


def is_market_hours() -> bool:
    """True if current IST time is within NSE session (09:15–15:30)."""
    now = datetime.now(_IST)
    open_ = now.replace(hour=_MARKET_OPEN_H, minute=_MARKET_OPEN_M, second=0, microsecond=0)
    close = now.replace(hour=_MARKET_CLOSE_H, minute=_MARKET_CLOSE_M, second=0, microsecond=0)
    return open_ <= now <= close


# ---------------------------------------------------------------------------
# Data quality detection
# ---------------------------------------------------------------------------

def _flatten_values(obj: Any) -> list:
    """Recursively collect all leaf numeric values from nested dicts/lists."""
    out: list = []
    if isinstance(obj, dict):
        for v in obj.values():
            out.extend(_flatten_values(v))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(_flatten_values(item))
    elif isinstance(obj, float):
        out.append(obj)
    return out


def _is_usd_ticker(data: dict) -> bool:
    """Heuristic: if a price-like field is < 1.0, it's probably a USD ticker on NSE data."""
    for key in ("last_price", "ltp", "close", "price"):
        val = data.get(key)
        if isinstance(val, (int, float)) and 0 < val < 1.0:
            return True
    return False


def detect_data_quality(data: dict | list, symbol: str = "", tool: str = "") -> str:
    """Return one of the DQ_* constants based on data inspection."""
    if isinstance(data, dict) and "error" in data:
        return DQ_INVALID

    values = _flatten_values(data)

    # NaN check
    if any(isinstance(v, float) and math.isnan(v) for v in values):
        return DQ_NAN

    # USD ticker check (applies only to market data tools)
    if isinstance(data, dict) and _is_usd_ticker(data):
        return DQ_INVALID

    # Staleness check — data_basis.staleness_days > 5
    if isinstance(data, dict):
        basis = data.get("data_basis", {}) or {}
        staleness = basis.get("staleness_days")
        if isinstance(staleness, int) and staleness > 5:
            return DQ_STALE

    return DQ_VALID


# ---------------------------------------------------------------------------
# Meta builder
# ---------------------------------------------------------------------------

def build_meta(
    *,
    type_: str = TYPE_FACT,
    validation_status: str = VALIDATION_VERIFIED,
    backtested: bool = False,
    production_validated: bool = False,
    research_status: str = RS_NOT_TESTED,
    data_quality: str = DQ_VALID,
    source: str = "yfinance",
    account_type: str = "MARKET_DATA_ONLY",
    zerodha_connected: bool = False,
    limitations: list[str] | None = None,
    deprecated_fields_present: list[str] | None = None,
    deprecation_note: str | None = None,
    symbol_corrected: bool = False,
    symbol_original: str | None = None,
    bootstrap_period: bool = True,
    warning: str | None = None,
) -> dict:
    """Build the meta dict that accompanies every tool response."""
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    meta: dict = {
        "type": type_,
        "validation": {
            "status": validation_status,
            "backtested": backtested,
            "production_validated": production_validated,
            "research_status": research_status,
        },
        "data_quality": data_quality,
        "market_hours": is_market_hours(),
        "source": source,
        "account_type": account_type,
        "zerodha_connected": zerodha_connected,
        "as_of": now_utc,
        "limitations": limitations or [],
        "deprecated_fields_present": deprecated_fields_present or [],
        "deprecation_note": deprecation_note,
        "symbol_corrected": symbol_corrected,
        "symbol_original": symbol_original,
        "bootstrap_period": bootstrap_period,
        "warning": warning,
    }
    return meta


# ---------------------------------------------------------------------------
# Wrapper
# ---------------------------------------------------------------------------

def wrap(data: Any, meta: dict) -> dict:
    """Return { 'data': data, 'meta': meta }."""
    return {"data": data, "meta": meta}


# ---------------------------------------------------------------------------
# Convenience builders per tool category
# ---------------------------------------------------------------------------

def market_meta(data: dict, *, symbol: str = "", source: str = "NSELive",
                symbol_corrected: bool = False, symbol_original: str | None = None) -> dict:
    dq = detect_data_quality(data, symbol=symbol, tool="market")
    warning = None
    if not is_market_hours():
        warning = "Outside NSE session. Quote may be last traded price, not live."
    return build_meta(
        type_=TYPE_FACT,
        validation_status=VALIDATION_VERIFIED,
        data_quality=dq,
        source=source,
        account_type="MARKET_DATA_ONLY",
        warning=warning,
        symbol_corrected=symbol_corrected,
        symbol_original=symbol_original,
    )


def indicator_meta(data: dict, *, symbol: str = "") -> dict:
    dq = detect_data_quality(data, symbol=symbol)
    warning = None
    if not is_market_hours():
        warning = "Outside NSE session. Use get_historical_data for end-of-day accuracy."
    if dq == DQ_NAN:
        warning = (warning or "") + " NaN values detected — insufficient data or bad ticker."
    return build_meta(
        type_=TYPE_INDICATOR,
        validation_status=VALIDATION_COMPUTED,
        data_quality=dq,
        source="yfinance",
        account_type="MARKET_DATA_ONLY",
        warning=warning if warning else None,
        limitations=["Derived from EOD-adjusted yfinance candles, not tick data."],
    )


def interpretation_meta(*, deprecated_fields: list[str] | None = None) -> dict:
    dep_note = (
        "Fields marked deprecated have no demonstrated predictive validity. "
        "See Phase 22 deprecation plan."
    ) if deprecated_fields else None
    return build_meta(
        type_=TYPE_INTERPRETATION,
        validation_status=VALIDATION_UNVALIDATED,
        research_status=RS_EXPERIMENTAL,
        data_quality=DQ_VALID,
        source="internal_journal",
        account_type="MARKET_DATA_ONLY",
        limitations=[
            "Regime classification has not been backtested for edge.",
            "Phase 20A: regime-classifier edge not demonstrated.",
        ],
        deprecated_fields_present=deprecated_fields or [],
        deprecation_note=dep_note,
    )


def journal_meta() -> dict:
    return build_meta(
        type_=TYPE_FACT,
        validation_status=VALIDATION_VERIFIED,
        data_quality=DQ_VALID,
        source="internal_journal",
        account_type="PAPER_JOURNAL",
        warning=(
            "Internal paper journal only. "
            "Not connected to real Zerodha account without authenticated login."
        ),
    )
