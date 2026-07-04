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
                body = r.json()
                if not body:
                    return []
                data = body.get("data", body)
                # detailed_avl_balance is a dict of segment-wise limits; use option_buy as the broadest
                avl = data.get("detailed_avl_balance") or {}
                if isinstance(avl, dict):
                    available = float(avl.get("option_buy") or avl.get("eq_cnc") or data.get("sod_balance") or 0)
                else:
                    available = float(avl or data.get("sod_balance") or 0)
                sod = float(data.get("sod_balance") or 0)
                realized = float(data.get("realized_pnl") or 0)
                used = max(0.0, sod - available + realized)
                total = sod
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
                    qty = int(h.get("quantity") or 0)
                    avg = float(h.get("average_price") or 0)
                    ltp = float(h.get("last_traded_price") or 0)
                    pnl = float(h.get("pnl_absolute") or 0)
                    pnl_pct = float(h.get("pnl_percent") or 0)
                    # exchange_segment is "NSE_EQ" — strip the suffix for display
                    exch = (h.get("exchange_segment") or "NSE").split("_")[0]
                    result.append(Holding(
                        symbol=h.get("trading_symbol") or h.get("security_id") or "",
                        exchange=exch,
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
                # positions response: data.net_positions + data.day_positions
                data = raw if isinstance(raw, list) else raw.get("data", raw)
                if isinstance(data, dict):
                    items = data.get("net_positions", []) + data.get("day_positions", [])
                else:
                    items = data
                result = []
                for p in items:
                    qty = int(p.get("net_quantity") or 0)
                    avg = float(p.get("average_price") or 0)
                    ltp = float(p.get("last_traded_price") or 0)
                    pnl = float(p.get("pnl_absolute") or 0)
                    exch = (p.get("exchange_segment") or "NSE").split("_")[0]
                    result.append(Position(
                        symbol=p.get("trading_symbol") or p.get("security_id") or "",
                        exchange=exch,
                        product=p.get("position_type") or "",
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

    async def get_raw_trade_book(self) -> dict:
        """Return raw /trade-book response for field discovery."""
        if not self._token:
            return {"error": "not_configured"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{INDSTOCKS_BASE}/trade-book", headers=self._headers())
                return {"status_code": r.status_code, "body": r.json()}
        except Exception as exc:
            return {"error": str(exc)}

    async def get_trades(self, order_id: str | None = None) -> list[dict]:
        """Return executed trades from /trade-book or /trades/{order_id}."""
        if not self._token:
            return []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                if order_id:
                    r = await client.get(
                        f"{INDSTOCKS_BASE}/trades/{order_id}",
                        headers=self._headers(),
                    )
                else:
                    r = await client.get(
                        f"{INDSTOCKS_BASE}/trade-book",
                        headers=self._headers(),
                    )
                if r.status_code != 200:
                    return []
                body = r.json()
                if not body:
                    return []
                data = body if isinstance(body, list) else body.get("data", [])
                if isinstance(data, list):
                    return data
                return [data] if data else []
        except Exception as exc:
            logger.debug("INDmoneyBroker.get_trades error: %s", exc)
            return []

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
                result = []
                for o in items:
                    if not isinstance(o, dict):
                        continue
                    # traded_price when filled, else requested_price for limit orders
                    price_str = o.get("traded_price") or o.get("requested_price") or o.get("sl_trigger_price") or ""
                    try:
                        price = float(price_str) if price_str else 0.0
                    except (ValueError, TypeError):
                        price = 0.0
                    # traded_qty when filled, else requested_qty
                    qty_raw = o.get("traded_qty") if o.get("traded_qty") else o.get("requested_qty")
                    try:
                        qty = int(qty_raw or 0)
                    except (ValueError, TypeError):
                        qty = 0
                    exch = (o.get("exchange") or "NSE")
                    result.append(Order(
                        order_id=str(o.get("id") or ""),
                        symbol=o.get("name") or o.get("trading_symbol") or o.get("security_id") or "",
                        exchange=exch,
                        transaction_type=o.get("txn_type") or "",
                        quantity=qty,
                        price=price,
                        status=o.get("status") or "",
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
