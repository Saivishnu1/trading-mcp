"""
Tiered OHLCV data fetcher for the chart awareness engine.

Source hierarchy per symbol type:
  BSE indices (SENSEX/BANKEX/BSE500/…):
    1. INDmoney with BSE scrip code
    2. Yahoo Finance using BSE Yahoo ticker

  NSE indices (NIFTY/BANKNIFTY/…) and NSE stocks:
    1. Zerodha historical API (authenticated)
    2. INDmoney with NSE scrip code (authenticated, chunked for >365-day ranges)
    3. Yahoo Finance (always available)

Returns a list of normalized candle dicts:
  {"datetime": str, "open": float, "high": float,
   "low": float, "close": float, "volume": int}
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Symbol sets
# ---------------------------------------------------------------------------

_BSE_SYMBOLS = {
    "SENSEX", "BANKEX", "BSE500", "BSEMIDCAP", "BSESMALLCAP",
    "BSE:SENSEX", "BSE:BANKEX", "BSE:BSE500", "BSE:BSEMIDCAP", "BSE:BSESMALLCAP",
}

# ---------------------------------------------------------------------------
# Interval maps: canonical → each source's format
# ---------------------------------------------------------------------------

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

# Max date range INDmoney allows per interval (in days)
_INDMONEY_MAX_DAYS: dict[str, int] = {
    "1minute":  7,
    "3minute":  7,
    "5minute":  7,
    "10minute": 7,
    "15minute": 7,
    "30minute": 14,
    "60minute": 14,
    "day":      365,
    "week":     365,
    "month":    365,
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

# ---------------------------------------------------------------------------
# Symbol converters
# ---------------------------------------------------------------------------

# Yahoo Finance ticker map for BSE + NSE indices
_YF_MAP = {
    "NIFTY":       "^NSEI",
    "NIFTY50":     "^NSEI",
    "NIFTY 50":    "^NSEI",
    "BANKNIFTY":   "^NSEBANK",
    "NIFTY BANK":  "^NSEBANK",
    "SENSEX":      "^BSESN",
    "BSE:SENSEX":  "^BSESN",
    "BANKEX":      "BSE-BANK.BO",
    "BSE:BANKEX":  "BSE-BANK.BO",
    "BSE500":      "BSE-500.BO",
    "BSE:BSE500":  "BSE-500.BO",
    "BSEMIDCAP":   "BSE-MIDCAP.BO",
    "BSE:BSEMIDCAP": "BSE-MIDCAP.BO",
    "BSESMALLCAP": "BSE-SMLCAP.BO",
    "BSE:BSESMALLCAP": "BSE-SMLCAP.BO",
}

# Alternative tickers to try when the primary fails — ordered by likelihood
_YF_FALLBACKS: dict[str, list[str]] = {
    "BANKEX":      ["^SPBSEBKEX", "BANKEX.BO"],
    "BSE:BANKEX":  ["^SPBSEBKEX", "BANKEX.BO"],
    "BSE500":      ["^BSE500", "BSE500.BO"],
    "BSE:BSE500":  ["^BSE500", "BSE500.BO"],
    "BSEMIDCAP":   ["^BSEMD", "^BSEMIDCAP"],
    "BSE:BSEMIDCAP": ["^BSEMD", "^BSEMIDCAP"],
    "BSESMALLCAP": ["^BSESML", "^BSESMALLCAP"],
    "BSE:BSESMALLCAP": ["^BSESML", "^BSESMALLCAP"],
}


def _to_yf_symbol(symbol: str) -> str:
    """Convert canonical symbol to yfinance ticker."""
    s = symbol.upper().strip()
    if s in _YF_MAP:
        return _YF_MAP[s]
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
        "NIFTY":       "NSE:NIFTY 50",
        "NIFTY50":     "NSE:NIFTY 50",
        "NIFTY 50":    "NSE:NIFTY 50",
        "BANKNIFTY":   "NSE:NIFTY BANK",
        "NIFTY BANK":  "NSE:NIFTY BANK",
        "SENSEX":      "BSE:SENSEX",
        "BANKEX":      "BSE:BANKEX",
        "BSE500":      "BSE:BSE500",
        "BSEMIDCAP":   "BSE:BSE MIDCAP",
        "BSESMALLCAP": "BSE:BSE SMALLCAP",
    }
    if s in aliases:
        return aliases[s]
    if ":" in s:
        return s
    return f"NSE:{s}"


def _is_bse_symbol(symbol: str) -> bool:
    return symbol.upper().strip() in _BSE_SYMBOLS


# ---------------------------------------------------------------------------
# Individual source fetchers
# ---------------------------------------------------------------------------

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
        return [
            {
                "datetime": str(c.get("date", "")),
                "open": float(c.get("open", 0) or 0),
                "high": float(c.get("high", 0) or 0),
                "low": float(c.get("low", 0) or 0),
                "close": float(c.get("close", 0) or 0),
                "volume": int(c.get("volume", 0) or 0),
            }
            for c in candles
        ]
    except Exception as exc:
        logger.debug("Zerodha historical fetch failed for %s: %s", symbol, exc)
        return []


async def _fetch_indmoney_single_chunk(
    scrip_code: str,
    ind_interval: str,
    start_ms: int,
    end_ms: int,
) -> list[dict]:
    """Single bounded INDmoney historical request (no chunking)."""
    try:
        from src.brokers.indmoney import INDmoneyBroker
        broker = INDmoneyBroker()
        if not broker._token:
            return []
        async with __import__("httpx").AsyncClient(timeout=15) as client:
            r = await client.get(
                f"https://api.indstocks.com/market/historical/{ind_interval}",
                headers={"Authorization": broker._token, "Content-Type": "application/json"},
                params={
                    "scrip-codes": scrip_code,
                    "start_time": start_ms,
                    "end_time": end_ms,
                },
            )
        if r.status_code != 200:
            return []
        raw = r.json()
        if not raw:
            return []
        candles = raw if isinstance(raw, list) else raw.get("data", [])
        result = []
        for c in candles:
            if isinstance(c, list) and len(c) >= 6:
                ts_ms = c[0]
                dt_str = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                result.append({
                    "datetime": dt_str,
                    "open": float(c[1] or 0),
                    "high": float(c[2] or 0),
                    "low": float(c[3] or 0),
                    "close": float(c[4] or 0),
                    "volume": int(c[5] or 0),
                })
        return result
    except Exception as exc:
        logger.debug("INDmoney chunk fetch failed for %s: %s", scrip_code, exc)
        return []


async def _fetch_indmoney(symbol: str, interval: str, from_date: str, to_date: str) -> list[dict]:
    """Fetch via INDstocks, auto-resolving scrip code and chunking for long ranges."""
    try:
        from src.brokers.indmoney import INDmoneyBroker
        broker = INDmoneyBroker()
        if not broker._token:
            return []

        from .instrument_resolver import get_resolver
        resolver = get_resolver()
        s = symbol.upper().strip().replace("NSE:", "").replace("BSE:", "")
        exch = "BSE" if _is_bse_symbol(symbol) else "NSE"
        scrip_code = await resolver.resolve(s, exch)
        if not scrip_code:
            return []

        ind_interval = _INDMONEY_INTERVAL.get(interval, "1day")
        max_days = _INDMONEY_MAX_DAYS.get(interval, 365)

        def _to_ms(d: date) -> int:
            return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)

        start_date = datetime.strptime(from_date, "%Y-%m-%d").date()
        end_date = datetime.strptime(to_date, "%Y-%m-%d").date()

        total_days = (end_date - start_date).days
        all_candles: list[dict] = []

        if total_days <= max_days:
            # Single request
            all_candles = await _fetch_indmoney_single_chunk(
                scrip_code, ind_interval,
                _to_ms(start_date), _to_ms(end_date),
            )
        else:
            # Chunk into max_days windows
            chunk_start = start_date
            seen_datetimes: set[str] = set()
            while chunk_start < end_date:
                chunk_end = min(chunk_start + timedelta(days=max_days), end_date)
                chunk = await _fetch_indmoney_single_chunk(
                    scrip_code, ind_interval,
                    _to_ms(chunk_start), _to_ms(chunk_end),
                )
                for c in chunk:
                    dt = c["datetime"]
                    if dt not in seen_datetimes:
                        seen_datetimes.add(dt)
                        all_candles.append(c)
                chunk_start = chunk_end

            all_candles.sort(key=lambda c: c["datetime"])

        return all_candles

    except Exception as exc:
        logger.debug("INDmoney historical fetch failed for %s: %s", symbol, exc)
        return []


def _yf_download_single(yf_sym: str, yf_interval: str, from_date: str, to_date: str) -> list[dict]:
    """Download one ticker from yfinance and return normalized candles. Empty list on failure."""
    import math
    import yfinance as yf  # type: ignore[import]
    try:
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
            if any(math.isnan(x) for x in [o, h, lo, c]):
                continue
            if c <= 0:
                continue
            result.append({
                "datetime": str(ts),
                "open": o, "high": h, "low": lo, "close": c, "volume": v,
            })
        return result
    except Exception:
        return []


def _fetch_yahoo(symbol: str, interval: str, from_date: str, to_date: str) -> list[dict]:
    """Fetch via yfinance. Tries fallback tickers for BSE indices with unreliable Yahoo coverage."""
    try:
        s_upper = symbol.upper().strip()
        yf_interval = _YFINANCE_INTERVAL.get(interval, "1d")

        # Build ticker list: primary first, then fallbacks
        tickers: list[str] = []
        primary = _to_yf_symbol(symbol)
        tickers.append(primary)
        for extra in _YF_FALLBACKS.get(s_upper, []):
            if extra not in tickers:
                tickers.append(extra)

        for ticker in tickers:
            result = _yf_download_single(ticker, yf_interval, from_date, to_date)
            if result:
                if ticker != primary:
                    logger.debug("Yahoo fallback ticker %s succeeded for %s", ticker, symbol)
                return result

        return []
    except Exception as exc:
        logger.debug("Yahoo Finance fetch failed for %s: %s", symbol, exc)
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def fetch_candles(
    symbol: str,
    interval: str,
    from_date: str,
    to_date: str,
) -> tuple[list[dict], str]:
    """Fetch OHLCV candles using tiered sources. Returns (candles, source_name)."""
    is_bse = _is_bse_symbol(symbol)

    if is_bse:
        # BSE-first: INDmoney → Yahoo
        candles = await _fetch_indmoney(symbol, interval, from_date, to_date)
        if candles:
            return candles, "indmoney"

        candles = _fetch_yahoo(symbol, interval, from_date, to_date)
        if candles:
            return candles, "yahoo"
    else:
        # NSE/equity: Zerodha → INDmoney → Yahoo
        candles = await _fetch_zerodha(symbol, interval, from_date, to_date)
        if candles:
            return candles, "zerodha"

        candles = await _fetch_indmoney(symbol, interval, from_date, to_date)
        if candles:
            return candles, "indmoney"

        candles = _fetch_yahoo(symbol, interval, from_date, to_date)
        if candles:
            return candles, "yahoo"

    return [], "none"
