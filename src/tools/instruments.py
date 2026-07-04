from typing import Optional
from mcp.server.fastmcp import FastMCP
from src.market import get_market


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def search_instruments(
        query: str,
        exchange: Optional[str] = "NSE",
        limit: int = 20,
    ) -> list[dict]:
        """Search instruments by trading symbol or company name.

        Uses a locally-cached NSE equity list (downloaded once on first call)
        for fast substring matching. No auth required.

        Args:
            query: Partial or full name/symbol (e.g. 'INFY', 'Infosys', 'NIFTY').
            exchange: Filter by exchange — 'NSE' or None for all (default 'NSE').
            limit: Max results to return (default 20, max 100).
        """
        limit = min(max(1, limit), 100)
        return get_market().search(query, exchange)[:limit]
