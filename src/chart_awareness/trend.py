"""
Trend detection for the chart engine.

Uses EMA slope and price position to classify trend direction and strength.
No predictions — factual description of price structure only.
"""
from __future__ import annotations

from src.technical.indicators import ema_series


def detect_trend(candles: list[dict]) -> dict:
    """Detect trend from OHLCV candles.

    Returns:
      direction: uptrend | downtrend | sideways
      strength:  strong | moderate | weak
      duration_bars: consecutive bars in current trend direction
      ema20_slope: slope of EMA20 over last 5 bars (price units per bar)
      ema50_slope: slope of EMA50 over last 5 bars
      price_vs_ema20: above | below
      price_vs_ema50: above | below
    """
    if len(candles) < 20:
        return _insufficient()

    closes = [c["close"] for c in candles]
    last_close = closes[-1]

    ema20_s = ema_series(closes, 20)
    ema50_s = ema_series(closes, 50) if len(closes) >= 50 else []

    ema20_now = ema20_s[-1] if ema20_s else None
    ema50_now = ema50_s[-1] if ema50_s else None

    # Slope: change over last 5 bars of the EMA series
    ema20_slope = _slope(ema20_s, 5)
    ema50_slope = _slope(ema50_s, 5)

    price_vs_ema20 = _position(last_close, ema20_now)
    price_vs_ema50 = _position(last_close, ema50_now)

    direction = _direction(ema20_slope, ema50_slope, price_vs_ema20, price_vs_ema50)
    strength = _strength(ema20_slope, ema50_slope, closes)
    duration = _trend_duration(closes, direction)

    return {
        "direction": direction,
        "strength": strength,
        "duration_bars": duration,
        "ema20_slope": round(ema20_slope, 4) if ema20_slope is not None else None,
        "ema50_slope": round(ema50_slope, 4) if ema50_slope is not None else None,
        "price_vs_ema20": price_vs_ema20,
        "price_vs_ema50": price_vs_ema50,
    }


def _slope(series: list[float], lookback: int) -> float | None:
    if len(series) < lookback:
        return None
    window = series[-lookback:]
    return (window[-1] - window[0]) / (lookback - 1)


def _position(price: float, ema: float | None) -> str | None:
    if ema is None:
        return None
    return "above" if price > ema else "below"


def _direction(
    slope20: float | None,
    slope50: float | None,
    pos20: str | None,
    pos50: str | None,
) -> str:
    signals = []
    if slope20 is not None:
        signals.append(1 if slope20 > 0 else -1)
    if slope50 is not None:
        signals.append(1 if slope50 > 0 else -1)
    if pos20 == "above":
        signals.append(1)
    elif pos20 == "below":
        signals.append(-1)
    if pos50 == "above":
        signals.append(1)
    elif pos50 == "below":
        signals.append(-1)

    if not signals:
        return "sideways"
    score = sum(signals) / len(signals)
    if score >= 0.5:
        return "uptrend"
    if score <= -0.5:
        return "downtrend"
    return "sideways"


def _strength(
    slope20: float | None,
    slope50: float | None,
    closes: list[float],
) -> str:
    if not closes:
        return "weak"
    price_scale = closes[-1] if closes[-1] != 0 else 1.0
    # Normalise slope as fraction of price
    s20 = abs(slope20 / price_scale) if slope20 is not None else 0.0
    s50 = abs(slope50 / price_scale) if slope50 is not None else 0.0
    avg = (s20 + s50) / 2 if s50 else s20
    if avg >= 0.005:
        return "strong"
    if avg >= 0.001:
        return "moderate"
    return "weak"


def _trend_duration(closes: list[float], direction: str) -> int:
    if not closes or direction == "sideways":
        return 0
    # Count consecutive bars where close > prev close (uptrend) or < prev (downtrend)
    count = 0
    for i in range(len(closes) - 1, 0, -1):
        if (direction == "uptrend" and closes[i] >= closes[i - 1]) or (direction == "downtrend" and closes[i] <= closes[i - 1]):
            count += 1
        else:
            break
    return count


def _insufficient() -> dict:
    return {
        "direction": "sideways",
        "strength": "weak",
        "duration_bars": 0,
        "ema20_slope": None,
        "ema50_slope": None,
        "price_vs_ema20": None,
        "price_vs_ema50": None,
    }
