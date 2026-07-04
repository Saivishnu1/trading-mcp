"""
Tiered OHLCV data fetcher for the chart awareness engine.

Fetch order:
  1. Zerodha historical API (authenticated, best quality)
  2. INDmoney /market/historical (authenticated)
  3. Yahoo Finance via yfinance (guest, always available)

Returns a list of normalized candle dicts:
  {"datetime": str, "open": float, "high": float,
   "low": float, "close": float, "volume": int}
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Interval mapping: canonical → each source's format
_ZERODHA_INTERVAL = {
    "1minute": "minute",
    "3minute": "3minute",
    "5minute": "5minute",
    "10minute": "10minute",
    "15minute": "15minute",
    "30minute": "30minute",
    "60minute": "60minute",
    "day": "day",
    "week": "week",
    "month": "month",
}

_INDMONEY_INTERVAL = {
    "1minute": "1minute",
    "3minute": "3minute",
    "5minute": "5minute",
    "10minute": "10minute",
    "15minute": "15minute",
    "30minute": "30minute",
    "60minute": "60minute",
    "day": "1day",
    "week": "1week",
    "month": "1month",
}

_YFINANCE_INTERVAL = {
    "1minute": "1m",
    "3minute": "3m",
    "5minute": "5m",
    "10minute": "5m",   # yfinance has no 10m; use 5m as closest
    "15minute": "15m",
    "30minute": "30m",
    "60minute": "60m",
    "day": "1d",
    "week": "1wk",
    "month": "1mo",
}


def _to_yf_symbol(symbol: str) -> str:
    """Convert canonical symbol to yfinance ticker."""
    s = symbol.upper().strip()
    mapping = {
        "NIFTY": "^NSEI",
        "NIFTY50": "^NSEI",
        "NIFTY 50": "^NSEI",
        "BANKNIFTY": "^NSEBANK",
        "NIFTY BANK": "^NSEBANK",
        "SENSEX": "^BSESN",
        "BSE:SENSEX": "^BSESN",
    }
    if s in mapping:
        return mapping[s]
    if s.startswith("NSE:"):
        return s[4:] + ".NS"
    if s.startswith("BSE:"):
        return s[4:] + ".BO"
    if not s.endswith(".NS") and not s.endswith(".BO") and not s.startswith("^"):
        return s + ".NS"
    return s


def _to_zerodha_symbol(symbol: str) -> str:
    """Convert canonical symbol to Zerodha NSE:SYMBOL format."""
    s = symbol.upper().strip()
    aliases = {
        "NIFTY": "NSE:NIFTY 50",
        "NIFTY50": "NSE:NIFTY 50",
        "NIFTY 50": "NSE:NIFTY 50",
        "BANKNIFTY": "NSE:NIFTY BANK",
        "NIFTY BANK": "NSE:NIFTY BANK",
        "SENSEX": "BSE:SENSEX",
    }
    if s in aliases:
        return aliases[s]
    if ":" in s:
        return s
    return f"NSE:{s}"


async def _fetch_zerodha(symbol: str, interval: str, from_date: str, to_date: str) -> list[dict]:
    """Fetch via Zerodha JugaadClient historical API."""
    try:
        from src.broker import get_broker
        broker = get_broker()
        if not broker:
            return []
        zd_sym = _to_zerodha_symbol(symbol)
        zd_interval = _ZERODHA_INTERVAL.get(interval, "day")
        candles = broker.historical_data(zd_sym, from_date, to_date, zd_interval)
        if not candles:
            return []
        result = []
        for c in candles:
            result.append({
                "datetime": str(c.get("date", "")),
                "open": float(c.get("open", 0) or 0),
                "high": float(c.get("high", 0) or 0),
                "low": float(c.get("low", 0) or 0),
                "close": float(c.get("close", 0) or 0),
                "volume": int(c.get("volume", 0) or 0),
            })
        return result
    except Exception as exc:
        logger.debug("Zerodha historical fetch failed for %s: %s", symbol, exc)
        return []


async def _fetch_indmoney(symbol: str, interval: str, from_date: str, to_date: str) -> list[dict]:
    """Fetch via INDstocks /market/historical API."""
    try:
        from src.brokers.indmoney import INDmoneyBroker
        broker = INDmoneyBroker()
        if not broker._token:
            return []
        ind_interval = _INDMONEY_INTERVAL.get(interval, "1day")
        candles = await broker.get_historical_data(symbol, ind_interval, from_date, to_date)
        if not candles:
            return []
        result = []
        for c in candles:
            result.append({
                "datetime": str(c.get("timestamp", "")),
                "open": float(c.get("open", 0) or 0),
                "high": float(c.get("high", 0) or 0),
                "low": float(c.get("low", 0) or 0),
                "close": float(c.get("close", 0) or 0),
                "volume": int(c.get("volume", 0) or 0),
            })
        return result
    except Exception as exc:
        logger.debug("INDmoney historical fetch failed for %s: %s", symbol, exc)
        return []


def _fetch_yahoo(symbol: str, interval: str, from_date: str, to_date: str) -> list[dict]:
    """Fetch via yfinance (synchronous)."""
    try:
        import yfinance as yf  # type: ignore[import]
        yf_sym = _to_yf_symbol(symbol)
        yf_interval = _YFINANCE_INTERVAL.get(interval, "1d")
        df = yf.download(
            yf_sym,
            start=from_date,
            end=to_date,
            interval=yf_interval,
            progress=False,
            auto_adjust=True,
        )
        if df is None or df.empty:
            return []
        # Flatten MultiIndex columns if present
        if hasattr(df.columns, "levels"):
            df.columns = [col[0].lower() if isinstance(col, tuple) else col.lower()
                          for col in df.columns]
        else:
            df.columns = [c.lower() for c in df.columns]
        result = []
        for ts, row in df.iterrows():
            o = float(row.get("open", 0) or 0)
            h = float(row.get("high", 0) or 0)
            lo = float(row.get("low", 0) or 0)
            c = float(row.get("close", 0) or 0)
            v = int(row.get("volume", 0) or 0)
            # Skip NaN rows
            import math
            if any(math.isnan(x) for x in [o, h, lo, c]):
                continue
            if c <= 0:
                continue
            result.append({
                "datetime": str(ts),
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "volume": v,
            })
        return result
    except Exception as exc:
        logger.debug("Yahoo Finance fetch failed for %s: %s", symbol, exc)
        return []


async def fetch_candles(
    symbol: str,
    interval: str,
    from_date: str,
    to_date: str,
) -> tuple[list[dict], str]:
    """Fetch OHLCV candles using tiered sources. Returns (candles, source_name)."""
    # Tier 1: Zerodha
    candles = await _fetch_zerodha(symbol, interval, from_date, to_date)
    if candles:
        return candles, "zerodha"

    # Tier 2: INDmoney
    candles = await _fetch_indmoney(symbol, interval, from_date, to_date)
    if candles:
        return candles, "indmoney"

    # Tier 3: Yahoo Finance
    candles = _fetch_yahoo(symbol, interval, from_date, to_date)
    if candles:
        return candles, "yahoo"

    return [], "none"
