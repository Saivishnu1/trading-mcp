"""
Shared dataclass models for the multi-broker abstraction layer.
All broker adapters return instances of these classes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


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
    # The broker's own real security_id for this row, when the adapter has
    # one on hand (2026-07-17). Previously always dropped — get_positions_for_web
    # re-resolved it via resolve_symbol()'s ambiguous symbol-text search
    # instead, which is a confirmed-wrong match for any weekly index option
    # sharing a TRADING_SYMBOL string with other expiries in the same month
    # (see resolve_security_id's own docstring) — the live-price WebSocket
    # subscribed to a completely different contract's security_id than the
    # one actually held, so its LTP never matched and stayed at ₹0 forever.
    security_id: str | None = None

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
    # See Holding.security_id's docstring — same bug, same fix.
    security_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Fund:
    available: float
    used: float
    total: float
    broker: str
    # Segment-wise raw balances (2026-07-13) — additive, optional. INDmoney's
    # /funds response nests a detailed_avl_balance dict whose exact key
    # names for F&O vs equity buying power aren't independently confirmed
    # (see INDmoneyBroker.get_funds' docstring — this exists specifically so
    # a caller can see the real breakdown rather than trust a single
    # possibly-wrong guessed field). None for brokers that don't expose this
    # (e.g. Zerodha's margins() shape is flat, not segment-wise).
    segment_breakdown: dict | None = None

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

    SL/target fields route this order through INDstocks' Smart Order (GTT-style)
    endpoint instead of the plain order endpoint — see ``is_smart_order``/
    ``to_indstocks_smart_order_payload``. INDstocks has no native trailing-SL field
    (confirmed absent from api-docs.indstocks.com/smart_orders/); trailing SL is
    synthesized client-side (see src/execution/trailing_sl.py) by repeatedly calling
    ``/smart/order/modify`` as price moves favorably — it is never sent as a single
    order field.
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
    sl_trigger_price: float | None = None
    sl_limit_price: float | None = None
    tgt_trigger_price: float | None = None
    tgt_limit_price: float | None = None
    trailing_sl_points: float | None = None  # client-side only, never sent to INDstocks

    def __post_init__(self) -> None:
        # INDstocks requires DAY validity for AMO orders (confirmed against
        # their docs, 2026-07-12) — normalized here so every caller (web,
        # Telegram, MCP) gets this for free instead of duplicating the rule.
        if self.is_amo:
            self.validity = "DAY"

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_smart_order(self) -> bool:
        """True if any SL/target leg is set, requiring /smart/order instead of /order."""
        return any(
            v is not None
            for v in (self.sl_trigger_price, self.sl_limit_price, self.tgt_trigger_price, self.tgt_limit_price)
        )

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

    def to_indstocks_smart_order_payload(self) -> dict:
        """Map to the exact INDstocks ``POST /smart/order`` request body.

        Per api-docs.indstocks.com/smart_orders/: SL and target are sibling legs
        of one GTT-style order (``sl_trigger_price``/``sl_limit_price``,
        ``tgt_trigger_price``/``tgt_limit_price``), not separate OCO orders.
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
            "algo_id": _INDSTOCKS_ALGO_ID.get(self.exchange.upper(), "99999"),
        }
        if self.order_type.upper() == "LIMIT":
            payload["limit_price"] = float(self.limit_price)
        if self.sl_trigger_price is not None:
            payload["sl_trigger_price"] = float(self.sl_trigger_price)
        if self.sl_limit_price is not None:
            payload["sl_limit_price"] = float(self.sl_limit_price)
        if self.tgt_trigger_price is not None:
            payload["tgt_trigger_price"] = float(self.tgt_trigger_price)
        if self.tgt_limit_price is not None:
            payload["tgt_limit_price"] = float(self.tgt_limit_price)
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
