"""
Pure-Python technical indicator math.

No I/O, no TA-Lib, no numpy required — every function takes plain lists of
floats and returns plain floats/dicts. Wilder's smoothing is used for RSI,
ADX and ATR (matching the convention in most charting platforms); standard
exponential smoothing is used for EMA and MACD.

Each function returns None (or a dict of Nones) when there is not enough data,
so callers can degrade gracefully instead of raising.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

def ema_series(values: list[float], period: int) -> list[float]:
    """Exponential moving average series, seeded with the SMA of the first
    `period` values. Returns a list aligned to `values` from index period-1 on.
    """
    if period <= 0 or len(values) < period:
        return []
    k = 2.0 / (period + 1)
    sma = sum(values[:period]) / period
    out = [sma]
    for v in values[period:]:
        out.append((v - out[-1]) * k + out[-1])
    return out


def _wilder_smooth(values: list[float], period: int) -> list[float]:
    """Wilder's smoothing (a.k.a. RMA), seeded with the simple average of the
    first `period` values. Used for RSI/ADX/ATR.
    """
    if period <= 0 or len(values) < period:
        return []
    first = sum(values[:period]) / period
    out = [first]
    for v in values[period:]:
        out.append((out[-1] * (period - 1) + v) / period)
    return out


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def rsi(closes: list[float], period: int = 14) -> float | None:
    """Relative Strength Index (Wilder). Returns the latest value, 0-100."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for prev, cur in zip(closes, closes[1:]):
        change = cur - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = _wilder_smooth(gains, period)
    avg_loss = _wilder_smooth(losses, period)
    if not avg_gain or not avg_loss:
        return None

    g, l = avg_gain[-1], avg_loss[-1]
    if l == 0:
        return 100.0
    rs = g / l
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------

def ema(values: list[float], period: int = 20) -> float | None:
    """Latest exponential moving average value."""
    series = ema_series(values, period)
    return round(series[-1], 4) if series else None


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------

def macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict:
    """Moving Average Convergence Divergence.

    Returns latest macd line, signal line and histogram.
    """
    none = {"macd": None, "signal": None, "histogram": None}
    if len(closes) < slow + signal:
        return none

    fast_ema = ema_series(closes, fast)
    slow_ema = ema_series(closes, slow)
    if not fast_ema or not slow_ema:
        return none

    # Align the two EMA series (slow starts later) before subtracting.
    offset = len(fast_ema) - len(slow_ema)
    macd_line = [f - s for f, s in zip(fast_ema[offset:], slow_ema)]

    signal_line = ema_series(macd_line, signal)
    if not signal_line:
        return none

    macd_val = macd_line[-1]
    signal_val = signal_line[-1]
    return {
        "macd": round(macd_val, 4),
        "signal": round(signal_val, 4),
        "histogram": round(macd_val - signal_val, 4),
    }


# ---------------------------------------------------------------------------
# True Range helpers (shared by ATR and ADX)
# ---------------------------------------------------------------------------

def _true_ranges(highs, lows, closes) -> list[float]:
    trs = []
    for i in range(1, len(closes)):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return trs


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------

def atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> float | None:
    """Average True Range (Wilder). Returns the latest value."""
    if len(closes) < period + 1:
        return None
    trs = _true_ranges(highs, lows, closes)
    smoothed = _wilder_smooth(trs, period)
    return round(smoothed[-1], 4) if smoothed else None


# ---------------------------------------------------------------------------
# ADX
# ---------------------------------------------------------------------------

def adx(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> dict:
    """Average Directional Index with +DI / -DI (Wilder).

    Returns latest adx, plus_di and minus_di. ADX needs roughly 2*period
    candles to stabilise.
    """
    none = {"adx": None, "plus_di": None, "minus_di": None}
    n = len(closes)
    if n < 2 * period + 1:
        return none

    plus_dm, minus_dm = [], []
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)

    trs = _true_ranges(highs, lows, closes)

    atr_s = _wilder_smooth(trs, period)
    plus_s = _wilder_smooth(plus_dm, period)
    minus_s = _wilder_smooth(minus_dm, period)
    if not atr_s or not plus_s or not minus_s:
        return none

    dx_series = []
    for a, p, m in zip(atr_s, plus_s, minus_s):
        if a == 0:
            continue
        plus_di = 100.0 * p / a
        minus_di = 100.0 * m / a
        denom = plus_di + minus_di
        if denom == 0:
            dx_series.append(0.0)
        else:
            dx_series.append(100.0 * abs(plus_di - minus_di) / denom)

    adx_s = _wilder_smooth(dx_series, period)
    if not adx_s:
        return none

    last_atr = atr_s[-1]
    plus_di = 100.0 * plus_s[-1] / last_atr if last_atr else None
    minus_di = 100.0 * minus_s[-1] / last_atr if last_atr else None
    return {
        "adx": round(adx_s[-1], 2),
        "plus_di": round(plus_di, 2) if plus_di is not None else None,
        "minus_di": round(minus_di, 2) if minus_di is not None else None,
    }
