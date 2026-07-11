from mcp.server.fastmcp import FastMCP

from src import meta as _meta
from src.options.analytics import project_carry_cost as _project_carry_cost
from src.planner import trade_plan as planner


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def create_trade_plan(
        symbol: str = "NIFTY",
        capital: float = 100_000,
        risk_percent: float = 1.0,
    ) -> dict:
        """Generate a complete, read-only trade plan for a symbol.

        Answers: what to trade, where to enter, stoploss, target,
        position size, risk/reward, and which options strategy to use.

        This tool does NOT place orders or call the Zerodha order API.
        All output is for planning and sizing purposes only.

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', or a raw yfinance ticker.
            capital: Total trading capital in INR (default 100000).
            risk_percent: Percent of capital to risk on this trade (default 1.0).
        """
        return planner.create_trade_plan(symbol, capital, risk_percent)

    @mcp.tool()
    def project_carry_cost(premium: float, dte: int, days_held: int) -> dict:
        """Rough time-value cost of holding an option position N more days
        with no price movement (Priority B12, 2026-07-11) — e.g. "holding to
        Monday at current decay rate costs approximately ₹X in time value."

        Use before holding a position overnight/into a weekend, or whenever
        an expiry-adjacent hold decision is being considered.

        No options-pricing (Black-Scholes/Greeks) model exists in this
        platform — this is a simple linear time-decay approximation
        (premium / dte per day), not a precise theta calculation. It
        deliberately errs toward overstating near-term decay, the safer
        direction for a hold-or-close warning.

        Args:
            premium: Current option premium (₹).
            dte: Current days to expiry.
            days_held: How many more calendar days you're considering holding.
        """
        data = _project_carry_cost(premium, dte, days_held)
        m = _meta.build_meta(
            type_=_meta.TYPE_INTERPRETATION,
            validation_status=_meta.VALIDATION_UNVALIDATED,
            data_quality=_meta.DQ_VALID,
            source="internal_approximation",
            account_type="MARKET_DATA_ONLY",
            limitations=[
                "Linear time-decay approximation, not a Black-Scholes/Greeks model.",
                "Assumes no price movement in the underlying.",
            ],
        )
        return _meta.wrap(data, m)
