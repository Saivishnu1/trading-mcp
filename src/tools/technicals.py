"""
Technical-analysis MCP tools.

OHLCV is pulled through the existing market service (yfinance-backed); the math
lives in src/technical/indicators.py (pure Python). No auth required.
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


def _load_candles_via_indmoney_fallback(symbol: str, lookback_days: int, interval: str) -> list[dict]:
    """Fallback OHLCV fetch when the primary yfinance path returns no data.

    Reuses the chart_awareness tiered fetcher (Zerodha -> INDmoney -> Yahoo),
    which resolves INDmoney scrip codes properly — unlike the plain yfinance
    path in src/market/service.py that has no fallback of its own.
    Returns [] if this also fails; never raises.
    """
    import asyncio
    from src.chart_awareness.data_fetcher import fetch_candles

    canonical_interval = _YF_TO_CANONICAL_INTERVAL.get(interval, "day")
    today = date.today()
    from_date = (today - timedelta(days=lookback_days)).isoformat()
    to_date = (today + timedelta(days=1)).isoformat()

    try:
        candles, source = asyncio.run(fetch_candles(symbol, canonical_interval, from_date, to_date))
    except Exception as exc:
        logger.warning("INDmoney fallback fetch failed for %s: %s", symbol, exc)
        return []

    if not candles:
        return []

    logger.info("Used %s fallback for %s after yfinance returned no data", source, symbol)
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
    ]


def _load_candles(symbol: str, lookback_days: int, interval: str = "1d") -> list[dict]:
    """Return raw OHLCV candle dicts (each with a 'date'), or [] on failure.

    Symbol resolution (index aliases, exchange prefixes) is delegated to the
    market service's canonical resolver — see src/market/symbols.py.
    interval: yfinance interval string — '1d' (daily), '1wk' (weekly), '1mo' (monthly).

    Falls back to the INDmoney-backed tiered fetcher when the primary
    yfinance-only path returns no data (e.g. rate-limited or transient outage).
    """
    today = date.today()
    start = (today - timedelta(days=lookback_days)).isoformat()
    end = (today + timedelta(days=1)).isoformat()
    try:
        candles = get_market().get_historical(symbol, start, end, interval)
    except Exception as exc:
        logger.warning("get_historical failed for %s: %s", symbol, exc)
        candles = []

    if candles:
        return candles

    return _load_candles_via_indmoney_fallback(symbol, lookback_days, interval)


def _load_closes(symbol: str, lookback_days: int):
    """Return (closes, highs, lows) lists, or (None, None, None) on failure."""
    candles = _load_candles(symbol, lookback_days)
    if not candles:
        return None, None, None
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    return closes, highs, lows


def _err(symbol: str, msg: str) -> dict:
    return {"symbol": symbol.upper(), "error": msg}


def _indicator_meta_for(
    data: dict,
    symbol: str,
    *,
    symbol_corrected: bool = False,
    symbol_original: str | None = None,
    symbol_normalized: str | None = None,
    symbol_format_applied: str | None = None,
) -> dict:
    dq = _meta.DQ_INVALID if "error" in data else _meta.detect_data_quality(data, symbol=symbol)
    warning = None
    if not _meta.is_market_hours():
        warning = "Outside NSE session. Indicator computed from last available EOD candle."
    if dq == _meta.DQ_NAN:
        warning = (warning or "") + " NaN detected — check symbol or data gap."
    return _meta.build_meta(
        type_=_meta.TYPE_INDICATOR,
        validation_status=_meta.VALIDATION_COMPUTED,
        data_quality=dq,
        source="yfinance",
        account_type="MARKET_DATA_ONLY",
        limitations=["Derived from EOD-adjusted yfinance candles, not tick data."],
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
        closes, highs, lows = _load_closes(sym, lookback_days)
        if not closes:
            data = _err(
                symbol,
                "no price data available — the data source may be temporarily "
                "unavailable or rate-limited; retry shortly, or verify the symbol "
                "if this persists",
            )
            return _meta.wrap(data, _indicator_meta_for(data, symbol, **_norm_kw))
        value = indicators.atr(highs, lows, closes, period)
        if value is None:
            data = _err(symbol, f"insufficient data for period {period}")
            return _meta.wrap(data, _indicator_meta_for(data, symbol, **_norm_kw))
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
        return _meta.wrap(data, _indicator_meta_for(data, symbol, **_norm_kw))
