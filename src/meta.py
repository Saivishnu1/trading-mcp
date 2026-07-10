"""
Phase 22 — Trust metadata layer.
Phase 23 — Freshness fields, symbol normalization meta, loud error contracts.

Every MCP tool response is wrapped:
  { "data": <existing output>, "meta": <trust context> }

build_meta()           — assemble the meta dict for a tool call
wrap()                 — wrap data + meta into the canonical response envelope
is_market_hours()      — True during NSE session (09:15–15:30 IST)
detect_data_quality()  — inspect a data dict for NaN / USD ticker / staleness
make_symbol_error()    — structured SYMBOL_ERROR response (not a wrapped response)
make_deprecated_error() — structured TOOL_DEPRECATED response
make_time_gated_error() — structured TOOL_TIME_GATED response
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
# Internally inconsistent but not obviously wrong — e.g. spot price falls
# outside the same response's own day_high/day_low range. Surfaced instead
# of VALID so a caller doesn't act on it (e.g. pick an option strike) without
# a second look, but distinct from INVALID since the data isn't necessarily
# unusable.
DQ_SUSPECT = "SUSPECT"

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


def spot_outside_range(spot: float | None, day_high: float | None, day_low: float | None) -> bool:
    """True if spot is a real number that falls outside [day_low, day_high].

    Returns False (not suspect) whenever any input is missing — this is a
    sanity check on internally-inconsistent data, not a substitute for the
    normal "data unavailable" handling.
    """
    if spot is None or day_high is None or day_low is None:
        return False
    if not all(isinstance(v, (int, float)) for v in (spot, day_high, day_low)):
        return False
    return spot > day_high or spot < day_low


# ---------------------------------------------------------------------------
# Meta builder
# ---------------------------------------------------------------------------

def _freshness_label(age_seconds: int, threshold_seconds: int, from_cache: bool) -> str:
    if from_cache:
        return "CACHED"
    if age_seconds < 60:
        return "LIVE"
    if age_seconds <= threshold_seconds:
        return "RECENT"
    return "STALE"


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
    symbol_normalized: str | None = None,
    symbol_format_applied: str | None = None,
    bootstrap_period: bool = True,
    warning: str | None = None,
    data_age_seconds: int = 0,
    stale_threshold_seconds: int = 300,
    from_cache: bool = False,
) -> dict:
    """Build the meta dict that accompanies every tool response."""
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    freshness = _freshness_label(data_age_seconds, stale_threshold_seconds, from_cache)
    is_stale = data_age_seconds > stale_threshold_seconds

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
        "freshness": {
            "label": freshness,
            "data_age_seconds": data_age_seconds,
            "stale_threshold_seconds": stale_threshold_seconds,
            "is_stale": is_stale,
        },
        "limitations": limitations or [],
        "deprecated_fields_present": deprecated_fields_present or [],
        "deprecation_note": deprecation_note,
        "symbol_corrected": symbol_corrected,
        "symbol_original": symbol_original,
        "symbol_normalized": symbol_normalized,
        "symbol_format_applied": symbol_format_applied,
        "bootstrap_period": bootstrap_period,
        "warning": warning,
        "schema_version": 5,
    }
    return meta


# ---------------------------------------------------------------------------
# Wrapper
# ---------------------------------------------------------------------------

def wrap(data: Any, meta: dict, warnings: list[str] | None = None) -> dict:
    """Return { 'data': data, 'meta': meta } with optional warnings array.

    Stale data warnings are appended automatically when meta['freshness']['is_stale'] is True.
    """
    result: dict = {"data": data, "meta": meta}
    active_warnings: list[str] = list(warnings or [])
    if meta.get("freshness", {}).get("is_stale"):
        active_warnings.append("STALE_DATA — data is older than threshold")
    if active_warnings:
        result["warnings"] = active_warnings
    return result


# ---------------------------------------------------------------------------
# Phase 23 — Loud error contracts
# ---------------------------------------------------------------------------

def make_symbol_error(
    received: str,
    tool: str,
    suggestions: list[str] | None = None,
    alternative: str | None = None,
) -> dict:
    """Return a SYMBOL_ERROR structured response (not a wrap envelope)."""
    return {
        "status": "SYMBOL_ERROR",
        "tool": tool,
        "reason": "Could not resolve symbol format",
        "received": received,
        "suggestions": suggestions or ["Use bare symbol: 'INFY', 'NIFTY', or 'NSE:INFY'"],
        "alternative": alternative,
    }


def make_deprecated_error(
    tool: str,
    reason: str,
    alternative: str | None = None,
    suggestions: list[str] | None = None,
) -> dict:
    """Return a TOOL_DEPRECATED structured response."""
    return {
        "status": "TOOL_DEPRECATED",
        "tool": tool,
        "reason": reason,
        "alternative": alternative,
        "suggestions": suggestions or [],
    }


def make_time_gated_error(
    tool: str,
    available_from: str = "09:15 IST",
    available_until: str = "15:30 IST",
    suggestions: list[str] | None = None,
    alternative: str | None = None,
) -> dict:
    """Return a TOOL_TIME_GATED structured response."""
    return {
        "status": "TOOL_TIME_GATED",
        "tool": tool,
        "reason": "Tool unavailable outside allowed market hours",
        "available_from": available_from,
        "available_until": available_until,
        "suggestions": suggestions or ["Use get_historical_data for offline analysis"],
        "alternative": alternative,
    }


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


_INDICATOR_SOURCE_LIMITATIONS = {
    "zerodha": ["Derived from live/intraday Zerodha broker candles."],
    "indmoney": ["Derived from live/intraday INDmoney broker candles."],
    "yahoo": ["Derived from EOD-adjusted yfinance candles, not tick data."],
    "yfinance": ["Derived from EOD-adjusted yfinance candles, not tick data."],
}


def indicator_meta(data: dict, *, symbol: str = "", source: str = "yfinance") -> dict:
    dq = detect_data_quality(data, symbol=symbol)
    warning = None
    if source in ("yahoo", "yfinance") and not is_market_hours():
        warning = "Outside NSE session. Use get_historical_data for end-of-day accuracy."
    if dq == DQ_NAN:
        warning = (warning or "") + " NaN values detected — insufficient data or bad ticker."
    return build_meta(
        type_=TYPE_INDICATOR,
        validation_status=VALIDATION_COMPUTED,
        data_quality=dq,
        source=source,
        account_type="MARKET_DATA_ONLY",
        warning=warning if warning else None,
        limitations=_INDICATOR_SOURCE_LIMITATIONS.get(source, _INDICATOR_SOURCE_LIMITATIONS["yfinance"]),
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
