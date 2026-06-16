from typing import Optional
from mcp.server.fastmcp import FastMCP
from src.market import get_market

_SUPPORTED_EXCHANGES = {"NSE", "BSE"}


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_instruments(exchange: str = "NSE") -> list[dict]:
        """Return all equity instruments for an exchange.

        Source: NSE's public EQUITY_L.csv (for NSE). Each record includes
        tradingsymbol, name, exchange, series, isin, and instrument_type.

        Warning: returns thousands of rows. Use search_instruments() for lookups.

        Args:
            exchange: 'NSE' (default). 'BSE' is not yet available via free CSV.
        """
        exchange = exchange.upper()
        if exchange not in _SUPPORTED_EXCHANGES:
            raise ValueError(
                f"exchange must be one of: {', '.join(sorted(_SUPPORTED_EXCHANGES))}"
            )
        return get_market().equity_list(exchange)

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

    @mcp.tool()
    def invalidate_instruments_cache() -> str:
        """Clear the in-memory NSE instruments cache.

        The cache is repopulated from NSE's public CSV on the next call to
        search_instruments() or get_instruments(). Useful if new listings appear.
        """
        get_market().invalidate_instruments_cache()
        return "Instruments cache cleared. Will reload on next search."
