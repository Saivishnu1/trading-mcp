from mcp.server.fastmcp import FastMCP

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
