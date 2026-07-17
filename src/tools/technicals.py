"""
Technical-analysis MCP tools.

OHLCV is pulled through the tiered chart-awareness fetcher (Zerodha, when
authenticated, -> INDmoney -> yfinance) so indicators reflect live broker
candles instead of lagging EOD-adjusted yfinance data (Priority 2,
2026-07-10). The math lives in src/technical/indicators.py (pure Python).
No auth required — Zerodha is simply skipped when not authenticated.
"""

import logging
from datetime import date, timedelta
from typing import Optional

from mcp.server.fastmcp import FastMCP

from src.market import get_market
from src.technical import indicators
from src import meta as _meta
from src.market.symbols import normalize_symbol_extended as _norm

logger = logging.getLogger(__name__)

# Reverse of chart_awareness's yfinance interval map, needed to call the
# tiered (Zerodha -> INDmoney -> Yahoo) fallback fetcher with its own
# canonical interval names when the plain yfinance path returns nothing.
_YF_TO_CANONICAL_INTERVAL = {
    "1m": "1minute", "5m": "5minute", "15m": "15minute",
    "30m": "30minute", "60m": "60minute",
    "1d": "day", "1wk": "week", "1mo": "month",
}


def _run_coro_blocking(coro):
    """Run an async coroutine to completion from synchronous code, safe to
    call whether or not the calling thread already has a running event loop.

    Confirmed bug (2026-07-17): every MCP tool in this module is a plain
    ``def``, not ``async def`` — FastMCP invokes sync tools inline on the
    server's own event loop rather than off-loading them to a worker
    thread, so a bare ``asyncio.run()`` here always raised "asyncio.run()
    cannot be called from a running event loop", silently swallowed by
    _load_candles_tiered's except clause. That meant the entire tiered
    Zerodha -> INDmoney -> Yahoo fetcher had never once actually run since
    it was introduced — every indicator tool and the dashboard's
    technicals section has always silently been yfinance-only. Runs the
    coroutine on a fresh event loop in a dedicated thread instead, which
    works regardless of what the calling thread is doing.
    """
    import asyncio
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _load_candles_tiered(symbol: str, lookback_days: int, interval: str) -> tuple[list[dict], str]:
    """Primary OHLCV fetch via the chart_awareness tiered fetcher
    (Zerodha, when authenticated -> INDmoney -> Yahoo). Returns
    (candles, source) — source is "zerodha"/"indmoney"/"yahoo"/"none".
    Never raises; returns ([], "none") on total failure."""
    from src.chart_awareness.data_fetcher import fetch_candles

    canonical_interval = _YF_TO_CANONICAL_INTERVAL.get(interval, "day")
    today = date.today()
    from_date = (today - timedelta(days=lookback_days)).isoformat()
    to_date = (today + timedelta(days=1)).isoformat()

    try:
        candles, source = _run_coro_blocking(
            fetch_candles(symbol, canonical_interval, from_date, to_date)
        )
    except Exception as exc:
        logger.warning("Tiered candle fetch failed for %s: %s", symbol, exc)
        return [], "none"

    if not candles:
        return [], "none"

    return [
        {
            "date": c["datetime"],
            "open": c["open"],
            "high": c["high"],
            "low": c["low"],
            "close": c["close"],
            "volume": c.get("volume", 0),
        }
        for c in candles
    ], source


def _load_candles_via_yfinance_fallback(symbol: str, lookback_days: int, interval: str) -> list[dict]:
    """Last-resort OHLCV fetch via the plain yfinance-only market service,
    used only when the tiered fetcher (Zerodha/INDmoney/Yahoo) returns
    nothing at all. Returns [] if this also fails; never raises."""
    today = date.today()
    start = (today - timedelta(days=lookback_days)).isoformat()
    end = (today + timedelta(days=1)).isoformat()
    try:
        return get_market().get_historical(symbol, start, end, interval)
    except Exception as exc:
        logger.warning("yfinance fallback get_historical failed for %s: %s", symbol, exc)
        return []


def _load_candles_with_source(symbol: str, lookback_days: int, interval: str = "1d") -> tuple[list[dict], str]:
    """Return (candles, source) — candles are raw OHLCV dicts (each with a
    'date'), source is "zerodha"/"indmoney"/"yahoo"/"none".

    Symbol resolution (index aliases, exchange prefixes) is delegated to the
    market service's canonical resolver — see src/market/symbols.py.
    interval: yfinance interval string — '1d' (daily), '1wk' (weekly), '1mo' (monthly).

    Zerodha-derived candles (when authenticated) are tried first via the
    tiered chart_awareness fetcher; the plain yfinance-only market service
    is only used as a last resort if that tier is fully exhausted
    (Priority 2, 2026-07-10 — previously yfinance ran first unconditionally).
    """
    candles, source = _load_candles_tiered(symbol, lookback_days, interval)
    if candles:
        return candles, source

    candles = _load_candles_via_yfinance_fallback(symbol, lookback_days, interval)
    return candles, ("yahoo" if candles else "none")


def _load_candles(symbol: str, lookback_days: int, interval: str = "1d") -> list[dict]:
    """Return raw OHLCV candle dicts (each with a 'date'), or [] on failure.
    See _load_candles_with_source for the source-aware variant."""
    candles, _source = _load_candles_with_source(symbol, lookback_days, interval)
    return candles


def _load_closes(symbol: str, lookback_days: int):
    """Return (closes, highs, lows) lists, or (None, None, None) on failure."""
    candles = _load_candles(symbol, lookback_days)
    if not candles:
        return None, None, None
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    return closes, highs, lows


def _load_closes_with_source(symbol: str, lookback_days: int):
    """Return (closes, highs, lows, source), or (None, None, None, "none")
    on failure. `source` is "zerodha"/"indmoney"/"yahoo"/"none" — used by
    dashboard/service.py to label which candle source fed the indicators."""
    candles, source = _load_candles_with_source(symbol, lookback_days)
    if not candles:
        return None, None, None, "none"
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    return closes, highs, lows, source


def _err(symbol: str, msg: str) -> dict:
    return {"symbol": symbol.upper(), "error": msg}


_SOURCE_LIMITATIONS = {
    "zerodha": ["Derived from live/intraday Zerodha broker candles."],
    "indmoney": ["Derived from live/intraday INDmoney broker candles."],
    "yahoo": ["Derived from EOD-adjusted yfinance candles, not tick data."],
    "yfinance": ["Derived from EOD-adjusted yfinance candles, not tick data."],
}


def _indicator_meta_for(
    data: dict,
    symbol: str,
    *,
    source: str = "yfinance",
    symbol_corrected: bool = False,
    symbol_original: str | None = None,
    symbol_normalized: str | None = None,
    symbol_format_applied: str | None = None,
) -> dict:
    dq = _meta.DQ_INVALID if "error" in data else _meta.detect_data_quality(data, symbol=symbol)
    warning = None
    if source in ("yahoo", "yfinance") and not _meta.is_market_hours():
        warning = "Outside NSE session. Indicator computed from last available EOD candle."
    if dq == _meta.DQ_NAN:
        warning = (warning or "") + " NaN detected — check symbol or data gap."
    return _meta.build_meta(
        type_=_meta.TYPE_INDICATOR,
        validation_status=_meta.VALIDATION_COMPUTED,
        data_quality=dq,
        source=source,
        account_type="MARKET_DATA_ONLY",
        limitations=_SOURCE_LIMITATIONS.get(source, _SOURCE_LIMITATIONS["yfinance"]),
        warning=warning,
        symbol_corrected=symbol_corrected,
        symbol_original=symbol_original,
        symbol_normalized=symbol_normalized,
        symbol_format_applied=symbol_format_applied,
    )


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def calculate_atr(
        symbol: str,
        period: int = 14,
        lookback_days: int = 60,
    ) -> dict:
        """Calculate the Average True Range (ATR) for a symbol.

        ATR measures volatility in absolute price terms. Also returned as a
        percentage of the last close for cross-symbol comparison.
        Data: daily candles via Yahoo Finance. No authentication required.

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', or a raw yfinance ticker.
            period: ATR period (default 14).
            lookback_days: Calendar days of history to fetch (default 60). Note: uses
                a shorter window than analyze_technicals (150 days) for quick checks.
                Use analyze_technicals for strategy-grade values consistent with trade
                setup generation.
        """
        sym, corrected, fmt = _norm(symbol, "calculate_atr")
        if not symbol.strip():
            return _meta.make_symbol_error(symbol, "calculate_atr")
        _norm_kw: dict = dict(
            symbol_corrected=corrected,
            symbol_original=symbol if corrected else None,
            symbol_normalized=sym if corrected else None,
            symbol_format_applied=fmt if corrected else None,
        )
        closes, highs, lows, source = _load_closes_with_source(sym, lookback_days)
        if not closes:
            data = _err(
                symbol,
                "no price data available — the data source may be temporarily "
                "unavailable or rate-limited; retry shortly, or verify the symbol "
                "if this persists",
            )
            return _meta.wrap(data, _indicator_meta_for(data, symbol, source=source, **_norm_kw))
        value = indicators.atr(highs, lows, closes, period)
        if value is None:
            data = _err(symbol, f"insufficient data for period {period}")
            return _meta.wrap(data, _indicator_meta_for(data, symbol, source=source, **_norm_kw))
        last_close = round(closes[-1], 4)
        atr_pct = round(100.0 * value / last_close, 2) if last_close else None
        data = {
            "symbol": symbol.upper(),
            "indicator": "ATR",
            "period": period,
            "value": value,
            "last_close": last_close,
            "atr_percent": atr_pct,
        }
        return _meta.wrap(data, _indicator_meta_for(data, symbol, source=source, **_norm_kw))
