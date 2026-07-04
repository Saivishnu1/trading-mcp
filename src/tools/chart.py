"""
Phase 3 — Chart Awareness Engine MCP tool.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from src import meta as _meta
from src.chart_awareness.engine import ChartEngine


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
        )
        return _meta.wrap(result, m)
