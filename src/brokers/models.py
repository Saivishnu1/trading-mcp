"""
Shared dataclass models for the multi-broker abstraction layer.
All broker adapters return instances of these classes.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class Holding:
    symbol: str
    exchange: str
    quantity: int
    avg_price: float
    current_price: float
    pnl: float
    pnl_percent: float
    broker: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Position:
    symbol: str
    exchange: str
    product: str
    quantity: int
    avg_price: float
    current_price: float
    pnl: float
    broker: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Fund:
    available: float
    used: float
    total: float
    broker: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Order:
    order_id: str
    symbol: str
    exchange: str
    transaction_type: str
    quantity: int
    price: float
    status: str
    broker: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Quote:
    symbol: str
    ltp: float
    open: float
    high: float
    low: float
    close: float
    volume: int
    broker: str

    def to_dict(self) -> dict:
        return asdict(self)
