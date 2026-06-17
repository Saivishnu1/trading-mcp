from mcp.server.fastmcp import FastMCP

from src.dashboard.service import build_dashboard


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_nifty_dashboard() -> dict:
        """Full NIFTY 50 market dashboard in a single call.

        Aggregates option chain analytics (PCR, max pain, support/resistance),
        technical indicators (RSI, EMA, MACD, ADX, ATR), market regime detection,
        trade setup (entry, stoploss, target + zone fields), and an options strategy
        recommendation into one structured response with a human-readable summary.

        No authentication required. Uses the nearest weekly expiry for options.
        """
        return build_dashboard("NIFTY")

    @mcp.tool()
    def get_banknifty_dashboard() -> dict:
        """Full BANK NIFTY market dashboard in a single call.

        Aggregates option chain analytics (PCR, max pain, support/resistance),
        technical indicators (RSI, EMA, MACD, ADX, ATR), market regime detection,
        trade setup (entry, stoploss, target + zone fields), and an options strategy
        recommendation into one structured response with a human-readable summary.

        No authentication required. Uses the nearest weekly expiry for options.
        """
        return build_dashboard("BANKNIFTY")
