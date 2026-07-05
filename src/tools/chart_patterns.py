"""
Phase 5 — Chart Pattern Awareness MCP tool.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from mcp.server.fastmcp import FastMCP

from src import meta as _meta
from src.chart_awareness.data_fetcher import fetch_candles
from src.pattern_awareness.detector import ChartPatternDetector

_BIAS_RANK = {"bullish": 1, "bearish": -1, "neutral": 0}


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def detect_chart_patterns(
        symbol: str,
        interval: str = "day",
        days: int = 180,
        min_bars: int = 20,
    ) -> dict:
        """Detect chart patterns for a symbol over a lookback window.

        Returns reversal, continuation, and breakout patterns with key levels
        and pattern status.

        Factual observations only — no buy/sell signals, no targets.

        Args:
            symbol:   "NIFTY", "BANKNIFTY", "SENSEX", "ICICIBANK", "NSE:INFY"
            interval: 1minute|5minute|15minute|30minute|60minute|day|week (default day)
            days:     Lookback in calendar days (default 180)
            min_bars: Minimum bars required to attempt detection (default 20)
        """
        today = date.today()
        from_date = (today - timedelta(days=days)).isoformat()
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
                "observations": ["No data available — cannot detect patterns"],
            }
            m = _meta.build_meta(
                type_=_meta.TYPE_INDICATOR,
                validation_status=_meta.VALIDATION_COMPUTED,
                data_quality=_meta.DQ_INVALID,
                source="none",
                account_type="MARKET_DATA_ONLY",
            )
            return _meta.wrap(result, m)

        df = pd.DataFrame(candles)
        df.columns = [c.lower() for c in df.columns]
        for col in ("open", "high", "low", "close"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0)

        detector = ChartPatternDetector()
        patterns = detector.detect_all(df, min_bars=min_bars)

        bullish = sum(1 for p in patterns if p["direction"] == "bullish")
        bearish = sum(1 for p in patterns if p["direction"] == "bearish")
        neutral = sum(1 for p in patterns if p["direction"] == "neutral")
        total = len(patterns)

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

        observations = _build_observations(symbol, patterns, min_bars)

        result = {
            "symbol": symbol.upper(),
            "interval": interval,
            "data_source": data_source,
            "candles_analyzed": len(df),
            "patterns": patterns,
            "summary": {
                "total_patterns": total,
                "bullish_count": bullish,
                "bearish_count": bearish,
                "neutral_count": neutral,
                "dominant_bias": bias,
            },
            "observations": observations,
        }
        m = _meta.build_meta(
            type_=_meta.TYPE_INDICATOR,
            validation_status=_meta.VALIDATION_COMPUTED,
            data_quality=_meta.DQ_VALID,
            source=data_source,
            account_type="MARKET_DATA_ONLY",
            warning=(
                None if _meta.is_market_hours()
                else "Outside NSE session. Patterns reflect last available candle."
            ),
        )
        return _meta.wrap(result, m)


def _build_observations(symbol: str, patterns: list[dict], min_bars: int) -> list[str]:
    if not patterns:
        return [f"No chart patterns detected in the lookback window"]

    obs = []
    for p in patterns:
        name = p["pattern"]
        status = p["status"]
        neckline = p.get("neckline")
        support = p.get("support")
        resistance = p.get("resistance")
        end_date = p.get("end_date", "")

        parts = [f"{name} ({status})"]
        if neckline and neckline > 0:
            parts.append(f"neckline at {neckline:,.2f}")
        if support and support > 0 and support != neckline:
            parts.append(f"support at {support:,.2f}")
        if resistance and resistance > 0 and resistance != neckline:
            parts.append(f"resistance at {resistance:,.2f}")
        if end_date:
            parts.append(f"as of {end_date}")
        obs.append(" — ".join(parts))

    return obs
