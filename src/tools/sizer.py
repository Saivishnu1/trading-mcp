from mcp.server.fastmcp import FastMCP

from src.sizer.engine import (
    size_equity_trade as _size_equity_trade,
    size_options_trade as _size_options_trade,
    size_from_recommendation as _size_from_recommendation,
)


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def size_equity_trade(
        symbol: str,
        direction: str,
        entry: float,
        stoploss: float,
        capital: float = 100_000,
        risk_percent: float = 1.0,
        target: float = None,
    ) -> dict:
        """Calculate position size for an equity trade using fixed-risk sizing.

        Computes quantity, capital_required, and max_loss from your stoploss
        distance and risk budget. Adjusts size downward when portfolio heat is
        ELEVATED (≥7%) or CRITICAL (≥9%), and when the broker portfolio risk
        score is HIGH or EXTREME.

        Returns log_trade_params ready to pass directly to log_trade().

        direction: LONG or SHORT
        risk_percent: percentage of capital to risk (default 1.0 = 1%)
        target: optional — included in log_trade_params and used to compute risk_reward
        """
        return _size_equity_trade(
            symbol=symbol,
            direction=direction,
            entry=entry,
            stoploss=stoploss,
            capital=capital,
            risk_percent=risk_percent,
            target=target,
        )

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

    @mcp.tool()
    def size_from_recommendation(
        symbol: str,
        capital: float = 100_000,
        risk_percent: float = 1.0,
    ) -> dict:
        """Get a fully sized trade package from a portfolio-aware recommendation.

        Calls recommend_trade() to obtain signal, entry, stoploss, target, and
        position_size (already adjusted for event risk and duplicate exposure),
        then computes absolute sizing: quantity, capital_required, risk_amount,
        capital_at_risk_pct, max_loss, and portfolio heat context.

        When recommendation is AVOID, all sizing fields are null and
        log_trade_params is null — preventing accidental trade logging.

        Returns log_trade_params with risk_amount, capital_at_risk, and
        portfolio_heat_at_entry populated for direct use with log_trade().
        """
        return _size_from_recommendation(
            symbol=symbol,
            capital=capital,
            risk_percent=risk_percent,
        )
