from mcp.server.fastmcp import FastMCP

from src.recommendations.engine import (
    review_open_trades as _review_open_trades,
)


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def review_open_trades() -> dict:
        """Review all currently open journal positions against live market conditions.

        For each open trade (from the journal), fetches live market data and returns:
          action         — HOLD / REDUCE / EXIT (from review_trade)
          thesis_status  — VALID / WEAKENING / INVALIDATED
          current_price  — live price
          current_pnl    — unrealised P&L in absolute terms
          stoploss_breached — true if current price has passed the logged stoploss
          target_reached    — true if current price has reached the logged target

        Summary includes: total_open, hold/reduce/exit counts,
        total_unrealised_pnl, at_risk_count (stoploss breached).

        Does not require an active broker session — uses journal + yfinance.
        """
        return _review_open_trades()
