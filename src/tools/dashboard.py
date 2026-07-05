from mcp.server.fastmcp import FastMCP

from src.dashboard.service import build_dashboard


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_nifty_dashboard() -> dict:
        """Full NIFTY 50 market dashboard in a single call.

        Aggregates option chain analytics (PCR, max pain, support/resistance),
        technical indicators (RSI, EMA, MACD, ADX, ATR), and factual market
        structure (price vs EMA20/EMA50, ADX/RSI thresholds) into one
        structured response with a factual, observation-only summary.

        No signal, confidence, trade setup, or strategy recommendation is
        included — use create_trade_plan / build_option_strategy for those.

        No authentication required. Uses the nearest expiry for options.
        """
        return build_dashboard("NIFTY")

    @mcp.tool()
    def get_banknifty_dashboard() -> dict:
        """Full BANK NIFTY market dashboard in a single call.

        Aggregates option chain analytics (PCR, max pain, support/resistance),
        technical indicators (RSI, EMA, MACD, ADX, ATR), and factual market
        structure (price vs EMA20/EMA50, ADX/RSI thresholds) into one
        structured response with a factual, observation-only summary.

        No signal, confidence, trade setup, or strategy recommendation is
        included — use create_trade_plan / build_option_strategy for those.

        No authentication required. Uses the nearest monthly expiry for options.
        """
        return build_dashboard("BANKNIFTY")

    @mcp.tool()
    def get_sensex_dashboard() -> dict:
        """Full SENSEX market dashboard in a single call.

        Aggregates BSE option chain analytics (PCR, max pain, support/resistance),
        technical indicators (RSI, EMA, MACD, ADX, ATR), and factual market
        structure (price vs EMA20/EMA50, ADX/RSI thresholds) into one
        structured response with a factual, observation-only summary.

        No signal, confidence, trade setup, or strategy recommendation is
        included — use create_trade_plan / build_option_strategy for those.

        No authentication required. Uses the nearest expiry for options.
        """
        return build_dashboard("SENSEX")
