from mcp.server.fastmcp import FastMCP

from src.strategy import builder


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def build_option_strategy(
        symbol: str = "NIFTY",
        expiry: str | None = None,
    ) -> dict:
        """Build a concrete options strategy with specific strikes, expiry, and payoff.

        Converts the trade plan signal and strategy recommendation into an
        executable structure — legs, premiums, max loss, max profit, and breakeven.

        Premium data and payoff calculations use live NSE option chain prices when
        available (NIFTY and BANKNIFTY). For other symbols or when the chain is
        unavailable, the structure is returned with is_estimate=True and null payoffs.

        This tool does NOT place orders or call the Zerodha order API.
        All output is for planning and review only.

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', or a raw yfinance ticker.
            expiry: Option expiry date string e.g. '23-Jun-2026'. Defaults to nearest expiry.
        """
        return builder.build_option_strategy(symbol, expiry)
