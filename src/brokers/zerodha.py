"""
Zerodha broker adapter — delegates to the existing src/broker/ layer.

This adapter wraps the existing ZerodhaWebClient (src/broker/zerodha_web.py)
via the get_broker() factory. It does NOT re-implement Zerodha auth.
"""
from __future__ import annotations

import logging

from .base import BrokerAdapter
from .models import Fund, Holding, Order, OrderRequest, Position, Quote

logger = logging.getLogger(__name__)


class ZerodhaBroker(BrokerAdapter):
    """Adapter that delegates to the existing src/broker/ layer."""

    @property
    def broker_name(self) -> str:
        return "zerodha"

    def _get_broker(self):
        """Lazy import to avoid circular imports and allow patching in tests."""
        from src.broker import get_broker
        return get_broker()

    async def is_authenticated(self) -> bool:
        try:
            return self._get_broker().is_authenticated()
        except Exception:
            return False

    async def get_profile(self) -> dict:
        try:
            return self._get_broker().profile() or {}
        except Exception as exc:
            logger.debug("ZerodhaBroker.get_profile error: %s", exc)
            return {}

    async def get_funds(self, segment: str | None = None) -> list[Fund]:
        try:
            data = self._get_broker().margins(segment=segment or "equity")
            if not data:
                return []
            # margins() returns a dict with keys like: net, available, utilised, etc.
            available = float(data.get("available", {}).get("live_balance", 0) or 0)
            used = float(data.get("utilised", {}).get("debits", 0) or 0)
            total = available + used
            return [Fund(
                available=available,
                used=used,
                total=total,
                broker="zerodha",
            )]
        except Exception as exc:
            logger.debug("ZerodhaBroker.get_funds error: %s", exc)
            return []

    async def get_holdings(self) -> list[Holding]:
        try:
            raw = self._get_broker().holdings()
            if not raw:
                return []
            result = []
            for h in raw:
                qty = int(h.get("quantity", 0))
                avg = float(h.get("average_price", 0) or 0)
                ltp = float(h.get("last_price", 0) or 0)
                pnl = float(h.get("pnl", 0) or 0)
                pnl_pct = ((ltp - avg) / avg * 100) if avg else 0.0
                result.append(Holding(
                    symbol=h.get("tradingsymbol", ""),
                    exchange=h.get("exchange", "NSE"),
                    quantity=qty,
                    avg_price=avg,
                    current_price=ltp,
                    pnl=pnl,
                    pnl_percent=round(pnl_pct, 2),
                    broker="zerodha",
                ))
            return result
        except Exception as exc:
            logger.debug("ZerodhaBroker.get_holdings error: %s", exc)
            return []

    async def get_positions(self) -> list[Position]:
        try:
            raw = self._get_broker().positions()
            if not raw:
                return []
            # positions() returns {"net": [...], "day": [...]}
            items = raw.get("net", []) if isinstance(raw, dict) else []
            result = []
            for p in items:
                qty = int(p.get("quantity", 0))
                avg = float(p.get("average_price", 0) or 0)
                ltp = float(p.get("last_price", 0) or 0)
                pnl = float(p.get("pnl", 0) or 0)
                result.append(Position(
                    symbol=p.get("tradingsymbol", ""),
                    exchange=p.get("exchange", "NSE"),
                    product=p.get("product", ""),
                    quantity=qty,
                    avg_price=avg,
                    current_price=ltp,
                    pnl=pnl,
                    broker="zerodha",
                ))
            return result
        except Exception as exc:
            logger.debug("ZerodhaBroker.get_positions error: %s", exc)
            return []

    async def get_raw_positions(self) -> dict:
        """Return the unmodified Zerodha positions() response — used by the
        Phase 9A monitor to resolve tradingsymbol/instrument_token for options,
        which the normalized Position dataclass does not carry."""
        try:
            raw = self._get_broker().positions()
            return raw if isinstance(raw, dict) else {"net": [], "day": []}
        except Exception as exc:
            logger.debug("ZerodhaBroker.get_raw_positions error: %s", exc)
            return {"net": [], "day": []}

    async def get_orders(self) -> list[Order]:
        try:
            raw = self._get_broker().orders()
            if not raw:
                return []
            result = []
            for o in raw:
                result.append(Order(
                    order_id=str(o.get("order_id", "")),
                    symbol=o.get("tradingsymbol", ""),
                    exchange=o.get("exchange", "NSE"),
                    transaction_type=o.get("transaction_type", ""),
                    quantity=int(o.get("quantity", 0)),
                    price=float(o.get("price", 0) or 0),
                    status=o.get("status", ""),
                    broker="zerodha",
                ))
            return result
        except Exception as exc:
            logger.debug("ZerodhaBroker.get_orders error: %s", exc)
            return []

    async def get_quote(self, symbols: list[str]) -> list[Quote]:
        # Zerodha quotes require live session and Kite Connect access;
        # the existing market tools (NSELive / yfinance) handle quoting.
        # Return empty for now — use get_quote / get_ltp MCP tools directly.
        try:
            if not await self.is_authenticated():
                return []
            # The existing ZerodhaWebClient does not expose a quote endpoint
            # (it relies on NSELive). Delegate to empty list.
            return []
        except Exception:
            return []

    async def get_historical_data(
        self,
        symbol: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> list[dict]:
        # Delegate to the existing yfinance-backed market service for now.
        try:
            from src.market.service import MarketService
            svc = MarketService()
            return svc.get_historical(symbol, from_date, to_date, interval) or []
        except Exception as exc:
            logger.debug("ZerodhaBroker.get_historical_data error: %s", exc)
            return []

    async def place_order(self, req: OrderRequest) -> dict:
        # Order placement in this stack is routed through INDmoney (no Kite
        # Connect subscription on this account). Kept concrete so the class
        # satisfies BrokerAdapter; never places a real Zerodha order.
        return {
            "status": "error",
            "message": "order placement via INDmoney only; Zerodha execution not available",
        }
