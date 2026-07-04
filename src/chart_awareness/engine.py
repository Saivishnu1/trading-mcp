"""
ChartEngine — orchestrates data fetching, trend, structure, levels, and indicators.
"""
from __future__ import annotations

from datetime import date, timedelta

from .data_fetcher import fetch_candles
from .trend import detect_trend
from .structure import detect_structure
from .levels import detect_levels
from . import indicators as _ind


class ChartEngine:

    async def analyze(
        self,
        symbol: str,
        interval: str = "day",
        days: int = 90,
        include_indicators: bool = True,
        include_structure: bool = True,
        include_levels: bool = True,
    ) -> dict:
        today = date.today()
        from_date = (today - timedelta(days=days)).isoformat()
        to_date = (today + timedelta(days=1)).isoformat()

        candles, data_source = await fetch_candles(symbol, interval, from_date, to_date)

        if not candles:
            return {
                "symbol": symbol.upper(),
                "interval": interval,
                "data_source": "none",
                "candles_analyzed": 0,
                "error": "No data available for this symbol/interval combination",
                "trend": {},
                "structure": {},
                "indicators": {},
                "levels": {},
                "observations": [],
            }

        trend = detect_trend(candles)
        structure = detect_structure(candles) if include_structure else {}
        levels = detect_levels(candles) if include_levels else {}
        computed_indicators = _ind.compute(candles) if include_indicators else {}

        observations = _build_observations(candles, trend, computed_indicators, levels)

        return {
            "symbol": symbol.upper(),
            "interval": interval,
            "data_source": data_source,
            "candles_analyzed": len(candles),
            "trend": trend,
            "structure": structure,
            "indicators": computed_indicators,
            "levels": levels,
            "observations": observations,
        }


def _build_observations(
    candles: list[dict],
    trend: dict,
    indics: dict,
    levels: dict,
) -> list[str]:
    obs = []
    last_close = candles[-1]["close"] if candles else None

    # Trend observations
    direction = trend.get("direction")
    strength = trend.get("strength")
    if direction and direction != "sideways":
        obs.append(f"Price is in a {strength} {direction}")
    elif direction == "sideways":
        obs.append("Price is moving sideways with no clear trend")

    pos20 = trend.get("price_vs_ema20")
    pos50 = trend.get("price_vs_ema50")
    if pos20 and pos50:
        obs.append(f"Price is {pos20} EMA20 and {pos50} EMA50")
    elif pos20:
        obs.append(f"Price is {pos20} EMA20")

    # Indicator observations
    rsi = indics.get("rsi")
    if rsi is not None:
        if rsi >= 70:
            obs.append(f"RSI at {rsi:.1f} — overbought territory")
        elif rsi <= 30:
            obs.append(f"RSI at {rsi:.1f} — oversold territory")
        else:
            obs.append(f"RSI at {rsi:.1f}")

    adx = indics.get("adx")
    if adx is not None:
        if adx >= 25:
            obs.append(f"ADX at {adx:.1f} indicates trending market")
        else:
            obs.append(f"ADX at {adx:.1f} indicates ranging/choppy market")

    macd = indics.get("macd")
    macd_signal = indics.get("macd_signal")
    if macd is not None and macd_signal is not None:
        if macd > macd_signal:
            obs.append(f"MACD ({macd:.2f}) above signal ({macd_signal:.2f}) — bullish momentum")
        else:
            obs.append(f"MACD ({macd:.2f}) below signal ({macd_signal:.2f}) — bearish momentum")

    # Level observations
    if last_close is not None:
        supports = levels.get("supports", [])
        resistances = levels.get("resistances", [])
        if supports:
            nearest_sup = min(supports, key=lambda x: abs(x["level"] - last_close))
            if nearest_sup["level"] < last_close:
                obs.append(
                    f"Nearest support at {nearest_sup['level']:,.2f} "
                    f"({nearest_sup['strength']}, {nearest_sup['touches']} touches)"
                )
        if resistances:
            nearest_res = min(resistances, key=lambda x: abs(x["level"] - last_close))
            if nearest_res["level"] > last_close:
                obs.append(
                    f"Nearest resistance at {nearest_res['level']:,.2f} "
                    f"({nearest_res['strength']}, {nearest_res['touches']} touches)"
                )

    return obs
