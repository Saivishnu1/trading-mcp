"""
Abstract base class for all broker adapters.
Each broker (Zerodha, INDmoney, etc.) implements this interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from .models import Holding, Position, Fund, Order, Quote


class BrokerAdapter(ABC):
    """Abstract interface every broker adapter must satisfy."""

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """Return the canonical broker identifier (e.g. 'zerodha', 'indmoney')."""
        ...

    @abstractmethod
    async def is_authenticated(self) -> bool:
        """Return True if the broker has a valid session / token."""
        ...

    @abstractmethod
    async def get_profile(self) -> dict:
        """Return authenticated user profile. Return {} on error."""
        ...

    @abstractmethod
    async def get_funds(self) -> list[Fund]:
        """Return available fund balances. Return [] on error."""
        ...

    @abstractmethod
    async def get_holdings(self) -> list[Holding]:
        """Return long-term demat holdings. Return [] on error."""
        ...

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Return open intraday / carry-forward positions. Return [] on error."""
        ...

    @abstractmethod
    async def get_orders(self) -> list[Order]:
        """Return today's orders. Return [] on error."""
        ...

    @abstractmethod
    async def get_quote(self, symbols: list[str]) -> list[Quote]:
        """Return live quotes for the given symbols. Return [] on error."""
        ...

    @abstractmethod
    async def get_historical_data(
        self,
        symbol: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> list[dict]:
        """Return OHLCV candles for the given symbol and date range. Return [] on error."""
        ...
