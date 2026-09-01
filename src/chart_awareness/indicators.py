"""
Indicator computation for the chart engine.

Delegates to the existing pure-Python src/technical/indicators.py library.
Returns the latest scalar values only — not full series.
"""
from __future__ import annotations

import math

from src.technical import indicators as _ind


def _safe(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    try:
        return round(float(val), 4)
    except (TypeError, ValueError):
        return None


def compute(candles: list[dict]) -> dict:
    """Compute all indicators from a list of OHLCV candle dicts.

    Returns latest values only. None means insufficient data.
    """
    if not candles:
        return _empty()

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c.get("volume", 0) or 0 for c in candles]

    # EMA 20, 50, 200
    ema20 = _safe(_ind.ema(closes, 20))
    ema50 = _safe(_ind.ema(closes, 50))
    ema200 = _safe(_ind.ema(closes, 200))

    # RSI 14
    rsi = _safe(_ind.rsi(closes, 14))

    # MACD (12, 26, 9) — existing lib returns {"macd", "signal", "histogram"}
    macd_raw = _ind.macd(closes)
    macd = _safe(macd_raw.get("macd"))
    macd_signal = _safe(macd_raw.get("signal"))
    macd_histogram = _safe(macd_raw.get("histogram"))

    # ADX 14
    adx_raw = _ind.adx(highs, lows, closes, 14)
    adx = _safe(adx_raw.get("adx"))

    # ATR 14
    atr = _safe(_ind.atr(highs, lows, closes, 14))

    # Bollinger Bands (20, 2) — compute manually using existing ema_series
    bb_upper, bb_lower, bb_mid = _bollinger(closes, 20, 2.0)

    # VWAP — only meaningful intraday; compute if volumes are present
    vwap = _vwap(highs, lows, closes, volumes)

    return {
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
        "rsi": rsi,
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_histogram": macd_histogram,
        "adx": adx,
        "atr": atr,
        "bb_upper": bb_upper,
        "bb_mid": bb_mid,
        "bb_lower": bb_lower,
        "vwap": vwap,
    }


def _empty() -> dict:
    keys = ["ema20", "ema50", "ema200", "rsi", "macd", "macd_signal",
            "macd_histogram", "adx", "atr", "bb_upper", "bb_mid", "bb_lower", "vwap"]
    return dict.fromkeys(keys)


def _bollinger(closes: list[float], period: int = 20, std_mult: float = 2.0):
    """Return (upper, lower, mid) latest Bollinger Band values."""
    if len(closes) < period:
        return None, None, None
    window = closes[-period:]
    mid = sum(window) / period
    variance = sum((x - mid) ** 2 for x in window) / period
    std = variance ** 0.5
    upper = _safe(mid + std_mult * std)
    lower = _safe(mid - std_mult * std)
    return upper, lower, _safe(mid)


def _vwap(highs, lows, closes, volumes) -> float | None:
    """Typical-price VWAP over the entire candle series."""
    if not volumes or sum(volumes) == 0:
        return None
    num = sum((h + l + c) / 3 * v for h, l, c, v in zip(highs, lows, closes, volumes))
    den = sum(volumes)
    if den == 0:
        return None
    return _safe(num / den)
