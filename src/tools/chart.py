"""
Phase 3 — Chart Awareness Engine MCP tool.
"""
from __future__ import annotations

from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from src import meta as _meta
from src.chart_awareness.engine import ChartEngine


def _candle_age_seconds(last_candle_datetime: str | None) -> int | None:
    """Seconds between now (UTC) and the last candle's timestamp. None if the
    timestamp is missing or unparseable — callers must not fabricate a
    freshness label from an unknown age (Audit-M3 follow-up: analyze_chart's
    freshness label previously always defaulted to 0 seconds / "LIVE"
    regardless of true candle age, since nothing populated data_age_seconds)."""
    if not last_candle_datetime:
        return None
    raw = str(last_candle_datetime).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - dt).total_seconds()
            return max(0, int(age))
        except ValueError:
            continue
    return None


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def analyze_chart(
        symbol: str,
        interval: str = "day",
        days: int = 90,
        include_indicators: bool = True,
        include_structure: bool = True,
        include_levels: bool = True,
    ) -> dict:
        """Analyze chart for a symbol — trend, structure, indicators, and key levels.

        Replaces calculate_rsi, calculate_ema, calculate_macd, calculate_adx,
        and analyze_technicals with a single comprehensive call.

        Data source hierarchy:
          1. Zerodha historical API (if authenticated)
          2. INDmoney historical API (if authenticated)
          3. Yahoo Finance (always available, no auth)

        Args:
            symbol:   "NIFTY", "BANKNIFTY", "SENSEX", "ICICIBANK", "NSE:INFY", etc.
            interval: 1minute | 5minute | 15minute | 30minute | 60minute |
                      day | week | month  (default: day)
            days:     Lookback in calendar days (default 90)
            include_indicators: RSI, MACD, EMA 20/50/200, ADX, ATR,
                                 Bollinger Bands, VWAP
            include_structure:  Swing HH/HL/LH/LL, BOS, CHOCH
            include_levels:     Support/resistance clusters, floor trader pivots

        Returns factual chart observations — no buy/sell signals, no targets.
        """
        engine = ChartEngine()
        result = await engine.analyze(
            symbol=symbol,
            interval=interval,
            days=days,
            include_indicators=include_indicators,
            include_structure=include_structure,
            include_levels=include_levels,
        )

        has_error = "error" in result
        age_seconds = _candle_age_seconds(result.get("last_candle_datetime"))
        # Intraday intervals go stale in minutes, not the 5-minute default
        # tuned for EOD/daily data — a 15-minute-old 1minute candle is stale;
        # a 15-minute-old daily candle is normal mid-session.
        stale_threshold = 180 if interval.endswith("minute") else 300
        m = _meta.build_meta(
            type_=_meta.TYPE_INDICATOR,
            validation_status=_meta.VALIDATION_COMPUTED,
            data_quality=_meta.DQ_INVALID if has_error else _meta.DQ_VALID,
            source=result.get("data_source", "unknown"),
            account_type="MARKET_DATA_ONLY",
            limitations=[
                "EOD-adjusted candles when sourced from Yahoo Finance.",
                "Intraday intervals use unadjusted data — VWAP is session VWAP.",
                "Structure and level detection requires sufficient swing points.",
            ],
            warning=(
                None if _meta.is_market_hours()
                else "Outside NSE session. Indicators reflect last available candle."
            ),
            data_age_seconds=age_seconds if age_seconds is not None else 0,
            stale_threshold_seconds=stale_threshold,
        )
        return _meta.wrap(result, m)
