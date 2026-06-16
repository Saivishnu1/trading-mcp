from typing import Optional
from mcp.server.fastmcp import FastMCP
from src.market import get_market

# Valid yfinance intervals and a human-readable alias map
_YF_INTERVALS = {
    "1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h",
    "1d", "5d", "1wk", "1mo", "3mo",
}
_INTERVAL_ALIAS: dict[str, str] = {
    # kite-style → yfinance
    "minute": "1m",
    "3minute": "5m",
    "5minute": "5m",
    "10minute": "15m",
    "15minute": "15m",
    "30minute": "30m",
    "60minute": "60m",
    "day": "1d",
}


def _resolve_interval(interval: str) -> str:
    i = interval.lower().strip()
    if i in _YF_INTERVALS:
        return i
    if i in _INTERVAL_ALIAS:
        return _INTERVAL_ALIAS[i]
    raise ValueError(
        f"Unknown interval '{interval}'. Valid values: "
        + ", ".join(sorted(_YF_INTERVALS))
        + ". Kite-style aliases also accepted: "
        + ", ".join(sorted(_INTERVAL_ALIAS))
    )


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_quote(instruments: list[str]) -> dict:
        """Return a full market quote for one or more instruments.

        Data source: NSELive (real-time NSE feed) for NSE stocks;
        Yahoo Finance for BSE stocks and indices.
        No authentication required.

        Args:
            instruments: List of 'EXCHANGE:SYMBOL' strings.
                         Examples: ['NSE:INFY', 'BSE:RELIANCE', 'NSE:NIFTY 50']
                         Raw yfinance tickers ('^NSEI', 'INFY.NS') also accepted.
        """
        market = get_market()
        return {inst: market.get_quote(inst) for inst in instruments}

    @mcp.tool()
    def get_ohlc(instruments: list[str]) -> dict:
        """Return today's OHLC and last traded price for instruments.

        Args:
            instruments: List of 'EXCHANGE:SYMBOL' strings.
                         Example: ['NSE:TCS', 'NSE:WIPRO']
        """
        market = get_market()
        return {inst: market.get_ohlc(inst) for inst in instruments}

    @mcp.tool()
    def get_ltp(instruments: list[str]) -> dict:
        """Return just the last traded price for instruments — fastest quote call.

        Args:
            instruments: List of 'EXCHANGE:SYMBOL' strings.
                         Example: ['NSE:INFY', 'NSE:NIFTY 50']
        """
        market = get_market()
        return {inst: {"last_price": market.get_ltp(inst)} for inst in instruments}

    @mcp.tool()
    def get_historical_data(
        symbol: str,
        from_date: str,
        to_date: str,
        interval: str = "1d",
    ) -> list[dict]:
        """Return historical OHLCV candle data via Yahoo Finance.

        No authentication required. Data goes back years for daily candles;
        intraday data has a rolling 60-day limit from Yahoo Finance.

        Args:
            symbol: 'EXCHANGE:SYMBOL' (e.g. 'NSE:INFY', 'BSE:RELIANCE') or
                    raw yfinance ticker ('INFY.NS', '^NSEI').
            from_date: Start date as 'YYYY-MM-DD'.
            to_date: End date as 'YYYY-MM-DD'.
            interval: Candle size.
                      yfinance native: '1m','2m','5m','15m','30m','60m','90m',
                                       '1h','1d','5d','1wk','1mo','3mo'
                      Kite-style aliases also accepted: 'minute','5minute',
                                       '15minute','30minute','60minute','day'
        """
        yf_interval = _resolve_interval(interval)
        return get_market().get_historical(symbol, from_date, to_date, yf_interval)
