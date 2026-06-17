from mcp.server.fastmcp import FastMCP

from src.review import reviewer


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def review_trade(
        symbol: str,
        direction: str,
        entry_price: float | None = None,
        holding_days: int | None = None,
    ) -> dict:
        """Evaluate whether an existing trade's original thesis is still valid.

        Answers: should I hold, reduce, or exit? Has the signal or regime changed?
        What conditions would invalidate this trade?

        Does NOT place or modify orders. All output is for review only.

        Args:
            symbol:       'NIFTY', 'BANKNIFTY', 'NSE:INFY', or a raw yfinance ticker.
            direction:    'LONG' or 'SHORT' — the direction of the original trade.
            entry_price:  Optional. Original entry price. Enables current_pnl_percent.
            holding_days: Optional. Number of days the trade has been open (informational).
        """
        return reviewer.review_trade(symbol, direction, entry_price, holding_days)
