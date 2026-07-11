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
import time
from datetime import datetime, timezone

import httpx

from .base import BrokerAdapter
from .models import Holding, Position, Fund, Order, OrderRequest, Quote

logger = logging.getLogger(__name__)

INDSTOCKS_BASE = "https://api.indstocks.com"
_TOKEN_ENV = "INDSTOCKS_TOKEN"

# Module-level (process-wide) instrument cache, keyed by source. A fresh
# INDmoneyBroker() is constructed per request (see get_broker_adapter), so an
# instance-level cache would re-download the ~MB-sized instrument CSV on every
# keystroke of a symbol search. This is shared across all instances/requests
# and refreshed once per _INSTRUMENT_CACHE_TTL_SECONDS.
_INSTRUMENT_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours — instrument masters rarely change intraday
_instrument_cache: dict[str, tuple[float, list[dict]]] = {}


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

    async def _raw_get(self, path: str) -> dict:
        """GET path and return {status_code, body} — body is JSON or raw text on parse failure."""
        if not self._token:
            return {"error": "not_configured"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{INDSTOCKS_BASE}{path}", headers=self._headers())
                try:
                    body = r.json()
                except Exception:
                    body = r.text
                return {"status_code": r.status_code, "body": body}
        except Exception as exc:
            return {"error": str(exc)}

    async def get_raw_order_book(self) -> dict:
        return await self._raw_get("/order-book")

    async def get_raw_holdings(self) -> dict:
        return await self._raw_get("/portfolio/holdings")

    async def get_raw_funds(self) -> dict:
        return await self._raw_get("/funds")

    async def get_raw_positions(self) -> dict:
        return await self._raw_get("/portfolio/positions")

    async def get_raw_trade_book(self, segment: str = "DERIVATIVE") -> dict:
        """/trade-book requires segment=EQUITY or segment=DERIVATIVE."""
        if not self._token:
            return {"error": "not_configured"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{INDSTOCKS_BASE}/trade-book",
                    headers=self._headers(),
                    params={"segment": segment},
                )
                try:
                    body = r.json()
                except Exception:
                    body = r.text
                return {"status_code": r.status_code, "segment": segment, "body": body}
        except Exception as exc:
            return {"error": str(exc)}

    async def get_trades(self, order_id: str | None = None, segment: str | None = None) -> list[dict]:
        """Return executed trades.

        - order_id set: GET /trades/{order_id}
        - segment set: GET /trade-book?segment=<segment>
        - neither: fetch both EQUITY and DERIVATIVE and merge
        """
        if not self._token:
            return []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                if order_id:
                    r = await client.get(
                        f"{INDSTOCKS_BASE}/trades/{order_id}",
                        headers=self._headers(),
                    )
                    if r.status_code != 200:
                        return []
                    body = r.json()
                    data = body if isinstance(body, list) else body.get("data", [])
                    return data if isinstance(data, list) else ([data] if data else [])

                segments = [segment] if segment else ["EQUITY", "DERIVATIVE"]
                combined: list[dict] = []
                for seg in segments:
                    r = await client.get(
                        f"{INDSTOCKS_BASE}/trade-book",
                        headers=self._headers(),
                        params={"segment": seg},
                    )
                    if r.status_code != 200:
                        continue
                    body = r.json()
                    if not body:
                        continue
                    raw_items = body if isinstance(body, list) else body.get("data", [])
                    if not isinstance(raw_items, list):
                        continue
                    for t in raw_items:
                        if not isinstance(t, dict):
                            continue
                        combined.append({
                            "order_id": str(t.get("fill_id") or t.get("id") or ""),
                            "symbol": t.get("scrip_code") or t.get("trading_symbol") or t.get("name") or "",
                            "quantity": t.get("quantity") or 0,
                            "price": t.get("price") or 0,
                            "created_at": t.get("trade_date") or t.get("created_at") or "",
                            "segment": seg,
                            "_raw": t,
                        })
                return combined
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
                    price_str = o.get("traded_price") or o.get("requested_price") or o.get("sl_trigger_price") or ""
                    try:
                        price = float(price_str) if price_str else 0.0
                    except (ValueError, TypeError):
                        price = 0.0
                    try:
                        qty = int(o.get("requested_qty") or 0)
                    except (ValueError, TypeError):
                        qty = 0
                    exch = o.get("exchange") or "NSE"
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

    async def place_order(self, req: OrderRequest) -> dict:
        """Place an order via INDstocks ``POST /order``.

        Contract: api-docs.indstocks.com/normal_orders/ — auth is the same
        ``Authorization`` header as every read call. INDstocks has no pure MARKET
        order (it converts MARKET → LIMIT at the live price server-side).
        Returns a uniform dict; never raises.
        """
        if not self._token:
            return {"status": "error", "message": "not_configured"}
        payload = req.to_indstocks_payload()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{INDSTOCKS_BASE}/order",
                    headers=self._headers(),
                    json=payload,
                )
                try:
                    body = r.json()
                except Exception:
                    body = r.text
                data = body.get("data", {}) if isinstance(body, dict) else {}
                ok = (
                    200 <= r.status_code < 300
                    and isinstance(body, dict)
                    and body.get("status") == "success"
                )
                return {
                    "status": "ok" if ok else "error",
                    "status_code": r.status_code,
                    "order_id": data.get("order_id") if isinstance(data, dict) else None,
                    "order_status": data.get("order_status") if isinstance(data, dict) else None,
                    "body": body,
                }
        except Exception as exc:
            logger.error("INDmoneyBroker.place_order failed: %s", exc)
            return {"status": "error", "message": str(exc)}

    async def _cached_instruments(self, source: str) -> list[dict]:
        """Return the instrument-master rows for ``source``, normalized to
        UPPER_SNAKE_CASE keys (matching the documented CSV schema), from the
        process-wide TTL cache — refetching only when stale or missing."""
        now = time.time()
        cached = _instrument_cache.get(source)
        if cached is not None and (now - cached[0]) < _INSTRUMENT_CACHE_TTL_SECONDS:
            return cached[1]
        rows = await self.get_instruments(source)
        normalized = [{str(k).strip().upper(): v for k, v in row.items()} for row in rows]
        _instrument_cache[source] = (now, normalized)
        return normalized

    async def resolve_security_id(self, symbol: str, source: str = "equity") -> str | None:
        """Resolve a trading symbol to its INDstocks ``security_id``.

        Uses the instrument-master CSV (``GET /market/instruments`` via
        ``get_instruments``). Per the documented schema the CSV headers are
        UPPER_SNAKE_CASE — ``SECURITY_ID`` and ``TRADING_SYMBOL`` (with
        ``SYMBOL_NAME``/``CUSTOM_SYMBOL`` as secondary matches). Returns None
        if the symbol is not found.
        """
        if not symbol:
            return None
        target = symbol.strip().upper()
        rows = await self._cached_instruments(source)
        for row_up in rows:
            sym = str(
                row_up.get("TRADING_SYMBOL")
                or row_up.get("SYMBOL_NAME")
                or row_up.get("CUSTOM_SYMBOL")
                or ""
            ).strip().upper()
            if sym == target:
                sec_id = row_up.get("SECURITY_ID")
                return str(sec_id) if sec_id else None
        return None

    async def search_instruments(self, query: str, source: str = "equity", limit: int = 15) -> list[dict]:
        """Search the instrument master for symbols matching ``query`` — powers
        the /trade page's autocomplete and the Telegram /search command.

        Match order: symbols starting with the query rank before symbols that
        merely contain it, so typing "REL" surfaces RELIANCE before a ticker
        that happens to contain "REL" mid-string. security_id is intentionally
        NOT included — callers only need it to render a picker; the id is
        re-resolved server-side at order time via resolve_security_id.
        """
        target = query.strip().upper()
        if not target:
            return []
        rows = await self._cached_instruments(source)

        starts, contains = [], []
        seen = set()
        for row in rows:
            sym = str(row.get("TRADING_SYMBOL") or row.get("SYMBOL_NAME") or "").strip().upper()
            if not sym or sym in seen:
                continue
            if target not in sym:
                continue
            seen.add(sym)
            name = str(row.get("INSTRUMENT_NAME") or row.get("SYMBOL_NAME") or sym).strip()
            exch = str(row.get("EXCH") or "NSE").strip().upper()
            entry = {"symbol": sym, "name": name, "exchange": exch, "segment": row.get("SEGMENT", "")}
            (starts if sym.startswith(target) else contains).append(entry)

        starts.sort(key=lambda e: len(e["symbol"]))
        contains.sort(key=lambda e: len(e["symbol"]))
        return (starts + contains)[:limit]

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
