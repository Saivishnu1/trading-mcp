from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from src import meta as _meta
from src.market_awareness.engine import MarketAwarenessEngine


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def get_market_awareness(
        symbol: str = "NIFTY",
        interval: str = "day",
        days: int = 90,
        include_options: bool = True,
        include_global: bool = True,
        include_patterns: bool = True,
    ) -> dict:
        """PRIMARY COMPOSITE TOOL — call this first for any market analysis.
        Combines chart, candle, pattern, option, and global analysis in one call.
        All sub-calls run concurrently. Missing data flagged explicitly.

        symbol:          "NIFTY"|"BANKNIFTY"|"SENSEX"|"BANKEX"|stock
        interval:        1minute|5minute|15minute|30minute|60minute|day|week
        days:            lookback in calendar days (default 90)
        include_options: include option chain analysis (default True)
        include_global:  include global pulse and VIX (default True)
        include_patterns: include chart and candle patterns (default True)

        For top gainers/losers, use Indmoney MCP:get_indian_stocks_movers.

        Returns factual observations only — no buy/sell signals, no price targets.
        """
        engine = MarketAwarenessEngine()
        result = await engine.analyze(
            symbol=symbol,
            interval=interval,
            days=days,
            include_options=include_options,
            include_global=include_global,
            include_patterns=include_patterns,
        )

        has_error = "error" in result
        spot_suspect = _meta.spot_outside_range(
            result.get("spot"), result.get("day_high"), result.get("day_low")
        )
        if has_error:
            data_quality = _meta.DQ_INVALID
        elif spot_suspect:
            data_quality = _meta.DQ_SUSPECT
        else:
            data_quality = _meta.DQ_VALID

        warning = None if _meta.is_market_hours() else "Outside NSE session. Indicators and options reflect last available session."
        if spot_suspect:
            suspect_note = (
                f"spot ({result.get('spot')}) falls outside this response's own "
                f"day_high/day_low range ({result.get('day_low')}-{result.get('day_high')}) "
                "— sources may be out of sync; verify before acting on this price."
            )
            warning = suspect_note if warning is None else f"{warning} {suspect_note}"

        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_COMPUTED,
            data_quality=data_quality,
            source="composite",
            account_type="MARKET_DATA_ONLY",
            limitations=[
                "Aggregate view combining yfinance, NSELive/BSE option chains, and local calendars.",
                "Market indicators are EOD-adjusted when sourced from Yahoo Finance.",
            ],
            warning=warning,
        )
        return _meta.wrap(result, m)
