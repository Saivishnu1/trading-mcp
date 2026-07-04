from mcp.server.fastmcp import FastMCP

from src.sizer.engine import (
    size_options_trade as _size_options_trade,
)


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def size_options_trade(
        symbol: str,
        direction: str,
        premium: float,
        stoploss_premium: float,
        lot_size: int,
        capital: float = 100_000,
        risk_percent: float = 1.0,
    ) -> dict:
        """Calculate lot count for an options trade using fixed-risk sizing.

        Computes lots, quantity (lots × lot_size), capital_required (premium basis),
        and max_loss from the premium distance to the stoploss premium level.
        Warns when capital_at_risk_pct exceeds 5% for a single options position.
        Adjusts lots for portfolio heat and portfolio risk rating.

        Returns log_trade_params with trade_type='OPTIONS' ready for log_trade().

        premium: entry premium per unit
        stoploss_premium: exit premium level (must be below entry premium for LONG)
        lot_size: contract lot size (e.g. 50 for NIFTY)
        """
        return _size_options_trade(
            symbol=symbol,
            direction=direction,
            premium=premium,
            stoploss_premium=stoploss_premium,
            lot_size=lot_size,
            capital=capital,
            risk_percent=risk_percent,
        )

