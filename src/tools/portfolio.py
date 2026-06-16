from mcp.server.fastmcp import FastMCP
from src.broker import get_broker


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_holdings() -> list[dict]:
        """Return your long-term demat holdings.

        Each entry includes tradingsymbol, exchange, quantity, average_price,
        last_price, pnl, and day_change. Requires an active session
        (call zerodha_login first).
        """
        return get_broker().holdings()

    @mcp.tool()
    def get_positions() -> dict:
        """Return your current intraday and carry-forward positions.

        Returns a dict with 'net' and 'day' keys, each a list of position
        dicts. Requires an active session.
        """
        return get_broker().positions()

    @mcp.tool()
    def get_margins(segment: str = "equity") -> dict:
        """Return available fund margins for a segment.

        Args:
            segment: 'equity' or 'commodity' (default 'equity').

        Requires an active session.
        """
        if segment not in ("equity", "commodity"):
            raise ValueError("segment must be 'equity' or 'commodity'")
        return get_broker().margins(segment=segment)
