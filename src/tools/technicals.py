"""
Technical-analysis MCP tools.

OHLCV is pulled through the existing market service (yfinance-backed); the math
lives in src/technical/indicators.py (pure Python). No auth required.
"""

import math
from datetime import date, timedelta
from typing import Optional

from mcp.server.fastmcp import FastMCP

from src.market import get_market
from src.technical import indicators
from src import meta as _meta
from src.market.symbols import normalize_symbol_extended as _norm

def _load_candles(symbol: str, lookback_days: int, interval: str = "1d") -> list[dict]:
    """Return raw OHLCV candle dicts (each with a 'date'), or [] on failure.

    Symbol resolution (index aliases, exchange prefixes) is delegated to the
    market service's canonical resolver — see src/market/symbols.py.
    interval: yfinance interval string — '1d' (daily), '1wk' (weekly), '1mo' (monthly).
    """
    today = date.today()
    start = (today - timedelta(days=lookback_days)).isoformat()
    end = (today + timedelta(days=1)).isoformat()
    try:
        candles = get_market().get_historical(symbol, start, end, interval)
    except Exception:
        return []
    return candles or []


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
    def calculate_rsi(
        symbol: str,
        period: int = 14,
        lookback_days: int = 60,
    ) -> dict:
        """Calculate the Relative Strength Index (RSI) for a symbol.

        RSI > 70 is conventionally overbought; RSI < 30 oversold.
        Data: daily candles via Yahoo Finance. No authentication required.

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', or a raw yfinance ticker.
            period: RSI lookback period (default 14).
            lookback_days: Calendar days of history to fetch (default 60). Note: uses
                a shorter window than analyze_technicals (150 days) for quick checks.
                Use analyze_technicals for strategy-grade values consistent with trade
                setup generation.
        """
        sym, corrected, fmt = _norm(symbol, "calculate_rsi")
        if not symbol.strip():
            return _meta.make_symbol_error(symbol, "calculate_rsi")
        _norm_kw: dict = dict(
            symbol_corrected=corrected,
            symbol_original=symbol if corrected else None,
            symbol_normalized=sym if corrected else None,
            symbol_format_applied=fmt if corrected else None,
        )
        if not _meta.is_market_hours():
            return _meta.make_time_gated_error("calculate_rsi")
        closes, _, _ = _load_closes(sym, lookback_days)
        if not closes:
            data = _err(symbol, "no price data — check the symbol")
            return _meta.wrap(data, _indicator_meta_for(data, symbol, **_norm_kw))
        value = indicators.rsi(closes, period)
        if value is None:
            data = _err(symbol, f"insufficient data for period {period}")
            return _meta.wrap(data, _indicator_meta_for(data, symbol, **_norm_kw))
        if value >= 70:
            signal = "overbought"
        elif value <= 30:
            signal = "oversold"
        else:
            signal = "neutral"
        data = {
            "symbol": symbol.upper(),
            "indicator": "RSI",
            "period": period,
            "value": value,
            "signal": signal,
        }
        return _meta.wrap(data, _indicator_meta_for(data, symbol, **_norm_kw))

    @mcp.tool()
    def calculate_ema(
        symbol: str,
        period: int = 20,
        lookback_days: int = 60,
    ) -> dict:
        """Calculate the Exponential Moving Average (EMA) for a symbol.

        Compares the latest close to the EMA to indicate trend direction.
        Data: daily candles via Yahoo Finance. No authentication required.

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', or a raw yfinance ticker.
            period: EMA period (default 20).
            lookback_days: Calendar days of history to fetch (default 60).
        """
        sym, corrected, fmt = _norm(symbol, "calculate_ema")
        if not symbol.strip():
            return _meta.make_symbol_error(symbol, "calculate_ema")
        _norm_kw: dict = dict(
            symbol_corrected=corrected,
            symbol_original=symbol if corrected else None,
            symbol_normalized=sym if corrected else None,
            symbol_format_applied=fmt if corrected else None,
        )
        if not _meta.is_market_hours():
            return _meta.make_time_gated_error("calculate_ema")
        closes, _, _ = _load_closes(sym, lookback_days)
        if not closes:
            data = _err(symbol, "no price data — check the symbol")
            return _meta.wrap(data, _indicator_meta_for(data, symbol, **_norm_kw))
        value = indicators.ema(closes, period)
        if value is None:
            data = _err(symbol, f"insufficient data for period {period}")
            return _meta.wrap(data, _indicator_meta_for(data, symbol, **_norm_kw))
        last_close = round(closes[-1], 4)
        position = "above" if last_close > value else "below"
        data = {
            "symbol": symbol.upper(),
            "indicator": "EMA",
            "period": period,
            "value": value,
            "last_close": last_close,
            "price_position": position,
        }
        return _meta.wrap(data, _indicator_meta_for(data, symbol, **_norm_kw))

    @mcp.tool()
    def calculate_macd(symbol: str, lookback_days: int = 120) -> dict:
        """Calculate MACD (12/26/9) for a symbol.

        Returns macd line, signal line and histogram. A positive histogram
        (macd above signal) is bullish momentum; negative is bearish.
        Data: daily candles via Yahoo Finance. No authentication required.

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', or a raw yfinance ticker.
            lookback_days: Calendar days of history to fetch (default 120). Note:
                analyze_technicals uses 150 days; values may differ slightly.
        """
        sym, corrected, fmt = _norm(symbol, "calculate_macd")
        if not symbol.strip():
            return _meta.make_symbol_error(symbol, "calculate_macd")
        _norm_kw: dict = dict(
            symbol_corrected=corrected,
            symbol_original=symbol if corrected else None,
            symbol_normalized=sym if corrected else None,
            symbol_format_applied=fmt if corrected else None,
        )
        if not _meta.is_market_hours():
            return _meta.make_time_gated_error("calculate_macd")
        closes, _, _ = _load_closes(sym, lookback_days)
        if not closes:
            data = _err(symbol, "no price data — check the symbol")
            return _meta.wrap(data, _indicator_meta_for(data, symbol, **_norm_kw))
        m = indicators.macd(closes)
        if m["macd"] is None:
            data = _err(symbol, "insufficient data for MACD (need ~35+ candles)")
            return _meta.wrap(data, _indicator_meta_for(data, symbol, **_norm_kw))
        if m["histogram"] is None:
            crossover = "unknown"
        else:
            crossover = "bullish" if m["histogram"] > 0 else "bearish"
        data = {
            "symbol": symbol.upper(),
            "indicator": "MACD",
            "fast": 12, "slow": 26, "signal_period": 9,
            **m,
            "momentum": crossover,
        }
        return _meta.wrap(data, _indicator_meta_for(data, symbol, **_norm_kw))

    @mcp.tool()
    def calculate_adx(
        symbol: str,
        period: int = 14,
        lookback_days: int = 150,
    ) -> dict:
        """Calculate the Average Directional Index (ADX) for a symbol.

        ADX > 25 indicates a trending market; < 20 indicates range/chop.
        +DI above -DI is bullish directional pressure, and vice versa.
        Data: daily candles via Yahoo Finance. No authentication required.

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', or a raw yfinance ticker.
            period: ADX period (default 14).
            lookback_days: Calendar days of history to fetch (default 150).
        """
        sym, corrected, fmt = _norm(symbol, "calculate_adx")
        if not symbol.strip():
            return _meta.make_symbol_error(symbol, "calculate_adx")
        _norm_kw: dict = dict(
            symbol_corrected=corrected,
            symbol_original=symbol if corrected else None,
            symbol_normalized=sym if corrected else None,
            symbol_format_applied=fmt if corrected else None,
        )
        closes, highs, lows = _load_closes(sym, lookback_days)
        if not closes:
            data = _err(symbol, "no price data — check the symbol")
            return _meta.wrap(data, _indicator_meta_for(data, symbol, **_norm_kw))
        a = indicators.adx(highs, lows, closes, period)
        if a["adx"] is None:
            data = _err(symbol, "insufficient data for ADX (need ~2*period candles)")
            return _meta.wrap(data, _indicator_meta_for(data, symbol, **_norm_kw))
        if a["adx"] >= 25:
            strength = "trending"
        elif a["adx"] < 20:
            strength = "ranging"
        else:
            strength = "weak trend"
        data = {
            "symbol": symbol.upper(),
            "indicator": "ADX",
            "period": period,
            **a,
            "trend_strength": strength,
        }
        return _meta.wrap(data, _indicator_meta_for(data, symbol, **_norm_kw))

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
            data = _err(symbol, "no price data — check the symbol")
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

    @mcp.tool()
    def analyze_technicals(symbol: str, lookback_days: int = 150) -> dict:
        """Compute a bundle of technical indicators for a symbol in one call.

        Returns RSI(14), EMA(20), EMA(50), MACD(12/26/9), ADX(14) and ATR(14)
        with each indicator's individual read. Data: daily candles via Yahoo
        Finance. No authentication required.

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', or a raw yfinance ticker.
            lookback_days: Calendar days of history to fetch (default 150).
        """
        sym, corrected, fmt = _norm(symbol, "analyze_technicals")
        if not symbol.strip():
            return _meta.make_symbol_error(symbol, "analyze_technicals")
        _norm_kw: dict = dict(
            symbol_corrected=corrected,
            symbol_original=symbol if corrected else None,
            symbol_normalized=sym if corrected else None,
            symbol_format_applied=fmt if corrected else None,
        )
        if not _meta.is_market_hours():
            return _meta.make_time_gated_error("analyze_technicals")
        closes, highs, lows = _load_closes(sym, lookback_days)
        if not closes:
            data = _err(symbol, "no price data — check the symbol")
            return _meta.wrap(data, _indicator_meta_for(data, symbol, **_norm_kw))

        candles_used = len(closes)
        last_close = round(closes[-1], 4)
        rsi_val = indicators.rsi(closes, 14)
        ema20 = indicators.ema(closes, 20)
        ema50 = indicators.ema(closes, 50)
        macd_val = indicators.macd(closes)
        adx_val = indicators.adx(highs, lows, closes, 14)
        atr_val = indicators.atr(highs, lows, closes, 14)

        _indicator_checks = [
            ("rsi_14", rsi_val),
            ("ema_20", ema20),
            ("ema_50", ema50),
            ("macd",   macd_val.get("macd")),
            ("adx_14", adx_val.get("adx")),
            ("atr_14", atr_val),
        ]
        nan_indicators = [
            name for name, v in _indicator_checks
            if isinstance(v, float) and math.isnan(v)
        ]
        if nan_indicators:
            data = _err(
                symbol,
                f"indicator(s) invalid ({', '.join(nan_indicators)}) — "
                f"possible data gap in price history ({candles_used} candles fetched)",
            )
            return _meta.wrap(data, _indicator_meta_for(data, symbol, **_norm_kw))

        data = {
            "symbol": symbol.upper(),
            "last_close": last_close,
            "candles_used": candles_used,
            "rsi_14": rsi_val,
            "ema_20": ema20,
            "ema_50": ema50,
            "macd": macd_val,
            "adx_14": adx_val,
            "atr_14": atr_val,
        }
        return _meta.wrap(data, _indicator_meta_for(data, symbol, **_norm_kw))
