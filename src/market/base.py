from typing import Protocol, runtime_checkable


@runtime_checkable
class MarketClient(Protocol):
    """Interface every market-data backend must satisfy."""

    def get_quote(self, symbol: str) -> dict:
        """Return full quote dict for one symbol (EXCHANGE:SYMBOL format)."""
        ...

    def get_ohlc(self, symbol: str) -> dict:
        """Return OHLC dict for one symbol."""
        ...

    def get_ltp(self, symbol: str) -> float:
        """Return last traded price for one symbol."""
        ...

    def get_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        interval: str,
    ) -> list[dict]:
        """Return list of OHLCV candle dicts."""
        ...

    def search(self, query: str, exchange: str | None) -> list[dict]:
        """Search instruments by name or symbol."""
        ...

    def equity_list(self, exchange: str) -> list[dict]:
        """Return full instrument list for an exchange."""
        ...
