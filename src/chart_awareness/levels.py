"""
Support, resistance, and pivot level detection for the chart engine.

Support/resistance: identified by price clustering at swing highs/lows.
Touch count determines strength: 3+ = strong, 2 = moderate, 1 = weak.

Pivots: classic floor trader pivots from the last completed candle.
"""
from __future__ import annotations

_SWING_LOOKBACK = 3
_CLUSTER_TOLERANCE = 0.005  # 0.5% of price — levels within this band are merged


def detect_levels(candles: list[dict]) -> dict:
    if len(candles) < 10:
        return _empty()

    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]

    swing_h_prices = _swing_highs(highs, _SWING_LOOKBACK)
    swing_l_prices = _swing_lows(lows, _SWING_LOOKBACK)

    resistances = _cluster_levels(swing_h_prices, closes[-1])
    supports = _cluster_levels(swing_l_prices, closes[-1])

    pivot = _floor_pivot(candles[-2]) if len(candles) >= 2 else {}

    return {
        "supports": supports,
        "resistances": resistances,
        "pivot": pivot,
    }


def _swing_highs(highs: list[float], n: int) -> list[float]:
    result = []
    for i in range(n, len(highs) - n):
        window = highs[i - n: i + n + 1]
        if highs[i] == max(window):
            result.append(highs[i])
    return result


def _swing_lows(lows: list[float], n: int) -> list[float]:
    result = []
    for i in range(n, len(lows) - n):
        window = lows[i - n: i + n + 1]
        if lows[i] == min(window):
            result.append(lows[i])
    return result


def _cluster_levels(prices: list[float], current_price: float) -> list[dict]:
    """Merge nearby price levels and count touches to determine strength."""
    if not prices:
        return []

    tol = current_price * _CLUSTER_TOLERANCE
    clusters: list[tuple[float, int]] = []  # (centroid, count)

    for p in sorted(prices):
        merged = False
        for i, (centroid, count) in enumerate(clusters):
            if abs(p - centroid) <= tol:
                # Update centroid to weighted average
                new_centroid = (centroid * count + p) / (count + 1)
                clusters[i] = (new_centroid, count + 1)
                merged = True
                break
        if not merged:
            clusters.append((p, 1))

    result = []
    for centroid, count in sorted(clusters, key=lambda x: x[0]):
        if count >= 3:
            strength = "strong"
        elif count == 2:
            strength = "moderate"
        else:
            strength = "weak"
        result.append({
            "level": round(centroid, 2),
            "strength": strength,
            "touches": count,
        })
    return result


def _floor_pivot(candle: dict) -> dict:
    """Classic floor trader pivot from a single candle (H, L, C)."""
    h = candle.get("high", 0) or 0
    l = candle.get("low", 0) or 0
    c = candle.get("close", 0) or 0
    if not (h and l and c):
        return {}
    pp = (h + l + c) / 3
    r1 = 2 * pp - l
    r2 = pp + (h - l)
    s1 = 2 * pp - h
    s2 = pp - (h - l)
    return {
        "pp": round(pp, 2),
        "r1": round(r1, 2),
        "r2": round(r2, 2),
        "s1": round(s1, 2),
        "s2": round(s2, 2),
    }


def _empty() -> dict:
    return {"supports": [], "resistances": [], "pivot": {}}
