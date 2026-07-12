"""Candlestick chart data service (2026-07-12) — additive only, powers the
new GET /trade/candles route.

Reuses INDmoneyBroker.get_historical_data() (the same existing INDstocks
integration already used in production by src/chart_awareness/
data_fetcher.py's Phase 3 analyze_chart engine) with the EXACT security_id
already picked on the trade page — never re-resolving by symbol text, which
is ambiguous for weekly index options (multiple contracts can share one
TRADING_SYMBOL string; only security_id is unique per contract).

Error granularity is bounded by what get_historical_data() itself can tell
a caller: it collapses "no token", "expired/rejected token", "unresolvable
security_id", and "genuinely no data in range" all down to an empty list
on any failure (see its own implementation). This module distinguishes
what it can cheaply and honestly check before/around that call (missing
params, unsupported interval, no token configured) and reports everything
else that still comes back empty as a single "no_data" outcome, rather
than fabricate a false distinction the underlying method can't support.
"""
from __future__ import annotations

import time
from datetime import date, timedelta

from src.brokers.factory import get_broker_adapter
from src.chart_awareness.data_fetcher import _INDMONEY_INTERVAL, _INDMONEY_MAX_DAYS

# UI interval -> canonical key already used by _INDMONEY_INTERVAL/
# _INDMONEY_MAX_DAYS (chart_awareness/data_fetcher.py) — reused directly
# rather than re-deriving INDstocks' interval strings or day-range limits.
UI_INTERVALS: dict[str, str] = {
    "1m": "1minute",
    "5m": "5minute",
    "15m": "15minute",
    "30m": "30minute",
    "1h": "60minute",
    "1D": "day",
}

_CACHE_TTL_SECONDS = 60
_cache: dict[tuple[str, str, str], tuple[float, list[dict]]] = {}


def _to_lightweight_candles(raw: list[dict]) -> list[dict]:
    """INDmoneyBroker.get_historical_data()'s {"timestamp" (ms), "open",
    "high", "low", "close", "volume"} -> TradingView Lightweight Charts'
    {"time" (unix seconds), "open", "high", "low", "close", "volume"}."""
    candles = []
    for c in raw:
        ts = c.get("timestamp")
        if ts is None:
            continue
        candles.append({
            "time": int(ts // 1000),
            "open": c.get("open"), "high": c.get("high"),
            "low": c.get("low"), "close": c.get("close"),
            "volume": c.get("volume", 0),
        })
    return candles


def clear_cache() -> None:
    """Test/debug helper — the module-level cache otherwise lives for the
    process lifetime."""
    _cache.clear()


async def get_candles(exchange: str, security_id: str, ui_interval: str) -> dict:
    """Returns one of:
      {"status": "ok", "candles": [...], "cached": bool}
      {"status": "error", "error": "<code>", "message": "<user-facing text>"}

    error codes: invalid_security_id, unsupported_interval, not_authenticated, no_data
    """
    exchange = (exchange or "").strip().upper()
    security_id = (security_id or "").strip()
    if not exchange or not security_id:
        return {
            "status": "error", "error": "invalid_security_id",
            "message": "No contract selected — pick a symbol from the dropdown first.",
        }

    canonical = UI_INTERVALS.get(ui_interval)
    if canonical is None:
        return {
            "status": "error", "error": "unsupported_interval",
            "message": f"Unsupported interval '{ui_interval}'.",
        }

    cache_key = (exchange, security_id, ui_interval)
    now = time.time()
    cached = _cache.get(cache_key)
    if cached is not None and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return {"status": "ok", "candles": cached[1], "cached": True}

    broker = get_broker_adapter("indmoney")
    if not getattr(broker, "_token", None):
        return {
            "status": "error", "error": "not_authenticated",
            "message": "INDstocks isn't configured on the server right now.",
        }

    ind_interval = _INDMONEY_INTERVAL[canonical]
    max_days = _INDMONEY_MAX_DAYS[canonical]
    to_date = date.today()
    from_date = to_date - timedelta(days=max_days)
    scrip_code = f"{exchange}_{security_id}"

    raw = await broker.get_historical_data(
        scrip_code, ind_interval, from_date.isoformat(), to_date.isoformat(),
    )
    if not raw:
        return {
            "status": "error", "error": "no_data",
            "message": "No historical data available for this contract right now.",
        }

    candles = _to_lightweight_candles(raw)
    _cache[cache_key] = (now, candles)
    return {"status": "ok", "candles": candles, "cached": False}
