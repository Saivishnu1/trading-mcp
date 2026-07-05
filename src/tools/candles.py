"""
Phase 4 — Candlestick Pattern Awareness MCP tool.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from mcp.server.fastmcp import FastMCP

from src import meta as _meta
from src.chart_awareness.data_fetcher import fetch_candles
from src.chart_awareness.levels import detect_levels
from src.chart_awareness import indicators as _ind
from src.candle_awareness.patterns import PatternDetector
from src.candle_awareness.classifier import classify_strength, build_context

_STRENGTH_RANK = {"weak": 0, "moderate": 1, "strong": 2}


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def detect_candlestick_patterns(
        symbol: str,
        interval: str = "day",
        days: int = 30,
        min_strength: str = "weak",
    ) -> dict:
        """Detect candlestick patterns for a symbol over a lookback window.

        Returns single, two-candle, and three-candle patterns with volume
        context and proximity to support/resistance levels.

        Factual observations only — no buy/sell signals, no targets.

        Args:
            symbol:       "NIFTY", "BANKNIFTY", "SENSEX", "ICICIBANK", "NSE:INFY"
            interval:     1minute|5minute|15minute|30minute|60minute|day|week (default day)
            days:         Lookback in calendar days (default 30)
            min_strength: "weak"|"moderate"|"strong" — filter minimum strength (default weak)
        """
        today = date.today()
        # Fetch extra bars for volume average (20-bar) and indicator context
        fetch_days = max(days + 30, 60)
        from_date = (today - timedelta(days=fetch_days)).isoformat()
        to_date = (today + timedelta(days=1)).isoformat()

        candles, data_source = await fetch_candles(symbol, interval, from_date, to_date)

        if not candles:
            result = {
                "symbol": symbol.upper(),
                "interval": interval,
                "data_source": "none",
                "candles_analyzed": 0,
                "error": "No data available for this symbol/interval combination",
                "patterns": [],
                "summary": {
                    "total_patterns": 0,
                    "bullish_count": 0,
                    "bearish_count": 0,
                    "neutral_count": 0,
                    "dominant_bias": "neutral",
                },
                "observations": [],
            }
            return _meta.wrap(result, symbol=symbol, source=data_source)

        # Build DataFrame from candles
        df = pd.DataFrame(candles)
        df.columns = [c.lower() for c in df.columns]
        for col in ("open", "high", "low", "close"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0)

        # Trim to requested window for pattern output, keep full for avg vol
        cutoff = (today - timedelta(days=days)).isoformat()
        df_full = df.copy()
        df_window = df[df["datetime"].astype(str) >= cutoff].copy()
        if df_window.empty:
            df_window = df.copy()

        # Compute indicators (ADX, RSI) from full window for context
        indics = _ind.compute(candles)
        adx = indics.get("adx")
        rsi = indics.get("rsi")

        # S/R levels from window
        levels = detect_levels(df_window.to_dict("records"))

        # Detect patterns on window
        detector = PatternDetector()
        # Pass full df for accurate avg volume; window df for pattern detection window
        avg_vol_df = df_full["volume"].replace(0, float("nan")).mean() or 1.0
        patterns_raw = detector.detect_all(df_window.reset_index(drop=True))

        # Classify strength and add context
        min_rank = _STRENGTH_RANK.get(min_strength.lower(), 0)
        patterns_out = []
        for p in patterns_raw:
            # Re-compute volume ratio against full-window avg
            p.volume_ratio = round(p.volume / avg_vol_df, 2) if avg_vol_df > 0 else 0.0
            p.strength = classify_strength(p, adx, rsi, levels)
            p.context = build_context(p, levels)
            if _STRENGTH_RANK.get(p.strength, 0) >= min_rank:
                patterns_out.append(p)

        # Sort: latest bar first, then by strength descending
        patterns_out.sort(key=lambda x: (x.location, -_STRENGTH_RANK.get(x.strength, 0)))

        def _location_label(loc: int) -> str:
            if loc == 0:
                return "latest"
            if loc == 1:
                return "1 bar ago"
            return f"{loc} bars ago"

        serialised = [
            {
                "name": p.name,
                "type": p.pattern_type,
                "strength": p.strength,
                "location": _location_label(p.location),
                "bar_date": p.bar_date,
                "open": round(p.open, 2),
                "high": round(p.high, 2),
                "low": round(p.low, 2),
                "close": round(p.close, 2),
                "volume_ratio": p.volume_ratio,
                "context": p.context,
            }
            for p in patterns_out
        ]

        # Summary
        bullish = sum(1 for p in patterns_out if p.pattern_type == "bullish")
        bearish = sum(1 for p in patterns_out if p.pattern_type == "bearish")
        neutral = sum(1 for p in patterns_out if p.pattern_type == "neutral")
        total = len(patterns_out)

        if total == 0:
            bias = "neutral"
        elif bullish > bearish and bullish > neutral:
            bias = "bullish"
        elif bearish > bullish and bearish > neutral:
            bias = "bearish"
        elif bullish == bearish and bullish > 0:
            bias = "mixed"
        else:
            bias = "neutral"

        # Observations
        observations = _build_observations(symbol, interval, patterns_out, levels, min_strength)

        result = {
            "symbol": symbol.upper(),
            "interval": interval,
            "data_source": data_source,
            "candles_analyzed": len(df_window),
            "patterns": serialised,
            "summary": {
                "total_patterns": total,
                "bullish_count": bullish,
                "bearish_count": bearish,
                "neutral_count": neutral,
                "dominant_bias": bias,
            },
            "observations": observations,
        }
        return _meta.wrap(result, symbol=symbol, source=data_source)


def _build_observations(
    symbol: str,
    interval: str,
    patterns: list,
    levels: dict,
    min_strength: str,
) -> list[str]:
    obs = []

    if not patterns:
        obs.append(f"No {min_strength}-or-stronger patterns detected")
        return obs

    # Group by name for concise summary
    seen: set[str] = set()
    for p in patterns:
        key = f"{p.name}|{p.bar_date}"
        if key in seen:
            continue
        seen.add(key)
        loc = "latest bar" if p.location == 0 else f"{p.location} bar{'s' if p.location > 1 else ''} ago"
        ctx = f" — {p.context}" if p.context else ""
        vol_note = ""
        if p.volume_ratio >= 1.5:
            vol_note = " with high volume"
        elif p.volume_ratio < 0.8:
            vol_note = " on low volume"
        obs.append(f"{p.name} on {loc}{vol_note}{ctx}")

    return obs
