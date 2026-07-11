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


# algo_id is a required INDstocks field that differs by exchange (per the
# order-placement contract at api-docs.indstocks.com/normal_orders/).
_INDSTOCKS_ALGO_ID = {"NSE": "99999", "BSE": "9999999999999999"}


@dataclass
class OrderRequest:
    """Write-model for placing an order (the read-only ``Order`` above lacks these fields).

    Field values use the INDstocks native vocabulary:
      - transaction_type: "BUY" | "SELL"
      - exchange:         "NSE" | "BSE"
      - segment:          "EQUITY" | "DERIVATIVE"
      - order_type:       "MARKET" | "LIMIT"   (INDstocks auto-converts MARKET → LIMIT@live)
      - product:          "CNC" | "INTRADAY" | "MARGIN"
      - validity:         "DAY" | "IOC"

    ``symbol`` is display-only (shown in confirm summaries); the API keys on ``security_id``.
    """

    security_id: str
    exchange: str
    segment: str
    transaction_type: str
    quantity: int
    order_type: str = "MARKET"
    product: str = "INTRADAY"
    limit_price: float = 0.0
    validity: str = "DAY"
    is_amo: bool = False
    symbol: str = ""  # display only, not sent to the API

    def to_dict(self) -> dict:
        return asdict(self)

    def to_indstocks_payload(self) -> dict:
        """Map to the exact INDstocks ``POST /order`` request body.

        Omits ``limit_price`` for MARKET orders (the broker fills at live price).
        """
        payload: dict = {
            "txn_type": self.transaction_type.upper(),
            "exchange": self.exchange.upper(),
            "segment": self.segment.upper(),
            "product": self.product.upper(),
            "order_type": self.order_type.upper(),
            "validity": self.validity.upper(),
            "security_id": str(self.security_id),
            "qty": int(self.quantity),
            "is_amo": bool(self.is_amo),
            "algo_id": _INDSTOCKS_ALGO_ID.get(self.exchange.upper(), "99999"),
        }
        if self.order_type.upper() == "LIMIT":
            payload["limit_price"] = float(self.limit_price)
        return payload


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
