"""
INDmoney broker adapter — uses the INDstocks REST API (api.indstocks.com).

Auth: INDSTOCKS_TOKEN env var → Authorization header (no "Bearer" prefix).
Rate limits: Data APIs 5/sec, 100k/day; Non-trading 15/sec.
"""
from __future__ import annotations

import csv
import io
import logging
import os
from datetime import datetime, timezone

import httpx

from .base import BrokerAdapter
from .models import Holding, Position, Fund, Order, Quote

logger = logging.getLogger(__name__)

INDSTOCKS_BASE = "https://api.indstocks.com"
_TOKEN_ENV = "INDSTOCKS_TOKEN"


class INDmoneyBroker(BrokerAdapter):
    """Broker adapter backed by the INDstocks API."""

    def __init__(self) -> None:
        self._token = os.environ.get(_TOKEN_ENV, "")

    @property
    def broker_name(self) -> str:
        return "indmoney"

    def _headers(self) -> dict:
        return {
            "Authorization": self._token,
            "Content-Type": "application/json",
        }

    async def is_authenticated(self) -> bool:
        if not self._token:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{INDSTOCKS_BASE}/user/profile",
                    headers=self._headers(),
                )
                return r.status_code == 200
        except Exception:
            return False

    async def get_profile(self) -> dict:
        if not self._token:
            return {}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{INDSTOCKS_BASE}/user/profile",
                    headers=self._headers(),
                )
                if r.status_code != 200:
                    return {}
                return r.json() or {}
        except Exception as exc:
            logger.debug("INDmoneyBroker.get_profile error: %s", exc)
            return {}

    async def get_funds(self) -> list[Fund]:
        if not self._token:
            return []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{INDSTOCKS_BASE}/funds",
                    headers=self._headers(),
                )
                if r.status_code != 200:
                    return []
                data = r.json()
                if not data:
                    return []
                # INDstocks funds response fields
                available = float(data.get("detailed_avl_balance", data.get("sod_balance", 0)) or 0)
                used = float(data.get("utilized", data.get("collateral_utilised", 0)) or 0)
                total = available + used
                return [Fund(
                    available=available,
                    used=used,
                    total=total,
                    broker="indmoney",
                )]
        except Exception as exc:
            logger.debug("INDmoneyBroker.get_funds error: %s", exc)
            return []

    async def get_holdings(self) -> list[Holding]:
        if not self._token:
            return []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{INDSTOCKS_BASE}/portfolio/holdings",
                    headers=self._headers(),
                )
                if r.status_code != 200:
                    return []
                raw = r.json()
                if not raw:
                    return []
                # Unwrap if response is wrapped under a key
                items = raw if isinstance(raw, list) else raw.get("data", raw.get("holdings", []))
                result = []
                for h in items:
                    qty = int(h.get("quantity", 0))
                    avg = float(h.get("average_price", 0) or 0)
                    ltp = float(h.get("last_traded_price", 0) or 0)
                    pnl = float(h.get("pnl_absolute", 0) or 0)
                    pnl_pct = float(h.get("pnl_percent", 0) or 0)
                    result.append(Holding(
                        symbol=h.get("trading_symbol", ""),
                        exchange=h.get("exchange_segment", "NSE"),
                        quantity=qty,
                        avg_price=avg,
                        current_price=ltp,
                        pnl=pnl,
                        pnl_percent=pnl_pct,
                        broker="indmoney",
                    ))
                return result
        except Exception as exc:
            logger.debug("INDmoneyBroker.get_holdings error: %s", exc)
            return []

    async def get_positions(self) -> list[Position]:
        if not self._token:
            return []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{INDSTOCKS_BASE}/portfolio/positions",
                    headers=self._headers(),
                )
                if r.status_code != 200:
                    return []
                raw = r.json()
                if not raw:
                    return []
                items = raw if isinstance(raw, list) else raw.get("data", raw.get("positions", []))
                result = []
                for p in items:
                    qty = int(p.get("net_quantity", 0))
                    avg = float(p.get("average_price", 0) or 0)
                    ltp = float(p.get("last_traded_price", 0) or 0)
                    pnl = float(p.get("pnl_absolute", 0) or 0)
                    result.append(Position(
                        symbol=p.get("trading_symbol", ""),
                        exchange=p.get("exchange_segment", "NSE"),
                        product=p.get("position_type", ""),
                        quantity=qty,
                        avg_price=avg,
                        current_price=ltp,
                        pnl=pnl,
                        broker="indmoney",
                    ))
                return result
        except Exception as exc:
            logger.debug("INDmoneyBroker.get_positions error: %s", exc)
            return []

    async def get_raw_order_book(self) -> dict:
        """Return raw /order-book response for field discovery."""
        if not self._token:
            return {"error": "not_configured"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{INDSTOCKS_BASE}/order-book", headers=self._headers())
                return {"status_code": r.status_code, "body": r.json()}
        except Exception as exc:
            return {"error": str(exc)}

    async def get_raw_holdings(self) -> dict:
        """Return raw /portfolio/holdings response for field discovery."""
        if not self._token:
            return {"error": "not_configured"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{INDSTOCKS_BASE}/portfolio/holdings", headers=self._headers())
                return {"status_code": r.status_code, "body": r.json()}
        except Exception as exc:
            return {"error": str(exc)}

    async def get_raw_funds(self) -> dict:
        """Return raw /funds response for field discovery."""
        if not self._token:
            return {"error": "not_configured"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{INDSTOCKS_BASE}/funds", headers=self._headers())
                return {"status_code": r.status_code, "body": r.json()}
        except Exception as exc:
            return {"error": str(exc)}

    async def get_raw_positions(self) -> dict:
        """Return raw /portfolio/positions response for field discovery."""
        if not self._token:
            return {"error": "not_configured"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{INDSTOCKS_BASE}/portfolio/positions", headers=self._headers())
                return {"status_code": r.status_code, "body": r.json()}
        except Exception as exc:
            return {"error": str(exc)}

    async def get_orders(self) -> list[Order]:
        if not self._token:
            return []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{INDSTOCKS_BASE}/order-book",
                    headers=self._headers(),
                )
                if r.status_code != 200:
                    return []
                raw = r.json()
                if not raw:
                    return []
                items = raw if isinstance(raw, list) else raw.get("data", raw.get("orders", []))
                if items and isinstance(items[0], dict):
                    logger.info("INDstocks order-book fields: %s", list(items[0].keys()))
                result = []
                for o in items:
                    if not isinstance(o, dict):
                        continue
                    # _pick returns first non-None, non-empty-string value cast to type
                    def _pick(*keys, cast=str, default=""):
                        for k in keys:
                            v = o.get(k)
                            if v is not None and v != "":
                                try:
                                    return cast(v)
                                except (ValueError, TypeError):
                                    continue
                        return default

                    result.append(Order(
                        order_id=_pick("order_id", "orderId", "id"),
                        symbol=_pick("trading_symbol", "tradingSymbol", "security_id", "symbol", "scrip_code", "ticker"),
                        exchange=_pick("exchange_segment", "exchange", "exch") or "NSE",
                        transaction_type=_pick("transaction_type", "transactionType", "txn_type", "side"),
                        quantity=_pick("quantity", "qty", "order_quantity", cast=int, default=0),
                        price=_pick("price", "limit_price", "avg_price", "trigger_price", cast=float, default=0.0),
                        status=_pick("status", "orderStatus", "order_status"),
                        broker="indmoney",
                    ))
                return result
        except Exception as exc:
            logger.debug("INDmoneyBroker.get_orders error: %s", exc)
            return []

    async def get_quote(self, symbols: list[str]) -> list[Quote]:
        """Fetch full quotes. symbols format: 'SEGMENT_TOKEN' e.g. 'NSE_2885'."""
        if not self._token or not symbols:
            return []
        try:
            scrip_codes = ",".join(symbols)
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{INDSTOCKS_BASE}/market/quotes/full",
                    headers=self._headers(),
                    params={"scrip-codes": scrip_codes},
                )
                if r.status_code != 200:
                    return []
                raw = r.json()
                if not raw:
                    return []
                items = raw if isinstance(raw, list) else raw.get("data", [])
                result = []
                for q in items:
                    result.append(Quote(
                        symbol=q.get("trading_symbol", q.get("scrip_code", "")),
                        ltp=float(q.get("live_price", q.get("ltp", 0)) or 0),
                        open=float(q.get("open", 0) or 0),
                        high=float(q.get("high", 0) or 0),
                        low=float(q.get("low", 0) or 0),
                        close=float(q.get("close", q.get("prev_close", 0)) or 0),
                        volume=int(q.get("volume", 0) or 0),
                        broker="indmoney",
                    ))
                return result
        except Exception as exc:
            logger.debug("INDmoneyBroker.get_quote error: %s", exc)
            return []

    async def get_historical_data(
        self,
        symbol: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> list[dict]:
        """Fetch OHLCV candles from INDstocks historical endpoint.

        Args:
            symbol: instrument token in SEGMENT_TOKEN format e.g. "NSE_2885"
            interval: one of 1minute, 5minute, 15minute, 30minute, 60minute,
                      240minute, 1day, 1week, 1month
            from_date: "YYYY-MM-DD"
            to_date:   "YYYY-MM-DD"

        Returns list of {"timestamp": ..., "open": ..., "high": ..., "low": ...,
                         "close": ..., "volume": ...}
        """
        if not self._token:
            return []
        try:
            # Convert YYYY-MM-DD → Unix milliseconds (start of day UTC)
            def to_ms(date_str: str) -> int:
                dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                return int(dt.timestamp() * 1000)

            start_ms = to_ms(from_date)
            end_ms = to_ms(to_date)

            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"{INDSTOCKS_BASE}/market/historical/{interval}",
                    headers=self._headers(),
                    params={
                        "scrip-codes": symbol,
                        "start_time": start_ms,
                        "end_time": end_ms,
                    },
                )
                if r.status_code != 200:
                    return []
                raw = r.json()
                if not raw:
                    return []
                # Response candles: [timestamp_ms, open, high, low, close, volume]
                candles = raw if isinstance(raw, list) else raw.get("data", [])
                result = []
                for c in candles:
                    if isinstance(c, list) and len(c) >= 6:
                        result.append({
                            "timestamp": c[0],
                            "open": c[1],
                            "high": c[2],
                            "low": c[3],
                            "close": c[4],
                            "volume": c[5],
                        })
                return result
        except Exception as exc:
            logger.debug("INDmoneyBroker.get_historical_data error: %s", exc)
            return []

    async def get_instruments(self, source: str = "equity") -> list[dict]:
        """Fetch instrument master list. source: 'equity' | 'fno' | 'index'.

        Returns parsed CSV rows as list of dicts.
        """
        if not self._token:
            return []
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(
                    f"{INDSTOCKS_BASE}/market/instruments",
                    headers=self._headers(),
                    params={"source": source},
                )
                if r.status_code != 200:
                    return []
                text = r.text
                if not text:
                    return []
                reader = csv.DictReader(io.StringIO(text))
                return list(reader)
        except Exception as exc:
            logger.debug("INDmoneyBroker.get_instruments error: %s", exc)
            return []

    async def get_option_chain(self, symbol: str, expiry: str) -> dict:
        """Option chain — coming soon in INDstocks API."""
        return {
            "status": "not_available",
            "message": "Option chain coming soon in INDstocks API",
        }

    async def get_greeks(self, tokens: list[str]) -> dict:
        """Option Greeks — coming soon in INDstocks API."""
        return {
            "status": "not_available",
            "message": "Greeks coming soon in INDstocks API",
        }
