"""
INDmoney broker adapter — uses the INDstocks REST API (api.indstocks.com).

Auth: INDSTOCKS_TOKEN env var → Authorization header (no "Bearer" prefix).
Rate limits: Data APIs 5/sec, 100k/day; Non-trading 15/sec.
"""
from __future__ import annotations

import asyncio
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

    async def get_funds(self, segment: str | None = None) -> list[Fund]:
        """Confirmed under-reporting bug (2026-07-13): this account's real
        F&O buying power (15,000+, confirmed by a successful ~12,941 options
        buy in the INDmoney app) came back as 6852.35 here — `available` was
        reading only the equity/cash balance. `option_buy` was picked as
        "the broadest" segment limit by assumption, never independently
        confirmed against a real response (same class of guess that broke
        `segment`/lot size earlier) — if that key doesn't actually exist in
        INDstocks' real payload, this silently fell through to `eq_cnc`
        (equity only), which matches the observed under-report exactly.

        Not fixed blind: `segment_breakdown` now carries detailed_avl_balance
        verbatim so a caller can see every real key instead of trusting one
        guess, and the raw response is logged once so the correct key name
        can be confirmed from production rather than guessed again.

        Args:
            segment: optional key to read directly out of detailed_avl_balance
                instead of the default option_buy/eq_cnc/sod_balance chain
                (e.g. pass whatever key segment_breakdown reveals is actually
                the F&O limit once confirmed).
        """
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
                logger.info("INDmoneyBroker.get_funds raw data: %s", data)
                # detailed_avl_balance is a dict of segment-wise limits; use option_buy as the broadest
                avl = data.get("detailed_avl_balance") or {}
                if segment and isinstance(avl, dict) and segment in avl:
                    available = float(avl.get(segment) or 0)
                elif isinstance(avl, dict):
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
                    segment_breakdown=avl if isinstance(avl, dict) else None,
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
                    trading_symbol = h.get("trading_symbol")
                    sec_id = h.get("security_id")
                    if not trading_symbol and sec_id:
                        trading_symbol = await self.resolve_security_name(str(sec_id), source="equity")
                    result.append(Holding(
                        symbol=trading_symbol or (str(sec_id) if sec_id else ""),
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
                    trading_symbol = p.get("trading_symbol")
                    sec_id = p.get("security_id")
                    if not trading_symbol and sec_id:
                        trading_symbol = await self.resolve_security_name(str(sec_id), source="fno")
                    result.append(Position(
                        symbol=trading_symbol or (str(sec_id) if sec_id else ""),
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
        """Place an order via INDstocks.

        Plain orders go to ``POST /order`` (api-docs.indstocks.com/normal_orders/).
        Orders carrying an SL and/or target leg (``req.is_smart_order``) go to
        ``POST /smart/order`` (api-docs.indstocks.com/smart_orders/) instead — a
        GTT-style order whose SL/target legs are sibling fields on one request,
        not separate OCO orders. Auth is the same ``Authorization`` header as
        every read call. INDstocks has no pure MARKET order (it converts
        MARKET → LIMIT at the live price server-side). Returns a uniform dict;
        never raises.
        """
        if not self._token:
            return {"status": "error", "message": "not_configured"}
        if req.is_smart_order:
            return await self._place_smart_order(req)
        payload = req.to_indstocks_payload()
        # Logged unconditionally (not just on error) — a 512/InternalServerException
        # from INDstocks (2026-07-12) gave no way to tell after the fact whether
        # is_amo/validity actually reached them as intended vs. our own logic
        # never setting it. No secrets in this payload (auth is header-only).
        logger.info("INDmoneyBroker.place_order payload: %s", payload)
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
                if not ok:
                    # A 4xx/5xx status alone doesn't say which INDstocks
                    # validation failed (e.g. "LimitPriceMustBeAboveZero") —
                    # only the response body does, and the outgoing-payload
                    # log line added 2026-07-12 doesn't capture it. Logged at
                    # warning since this is the caller's signal something
                    # rejected, not a bug in this broker adapter.
                    logger.warning(
                        "INDmoneyBroker.place_order rejected (status=%s): %s",
                        r.status_code, body,
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

    async def _place_smart_order(self, req: OrderRequest) -> dict:
        """POST /smart/order — SL/target-leg (GTT-style) order placement.

        Response shape differs from the plain /order endpoint:
        ``data.order_data`` is a list of order dicts, each optionally carrying
        a ``child_order_details`` sub-order (the GTT leg). We surface the
        parent order_id/order_status plus the child (SL/target) leg's id.
        """
        payload = req.to_indstocks_smart_order_payload()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{INDSTOCKS_BASE}/smart/order",
                    headers=self._headers(),
                    json=payload,
                )
                try:
                    body = r.json()
                except Exception:
                    body = r.text
                ok = (
                    200 <= r.status_code < 300
                    and isinstance(body, dict)
                    and body.get("status") == "success"
                )
                order_data = []
                if isinstance(body, dict):
                    data = body.get("data", {})
                    if isinstance(data, dict):
                        order_data = data.get("order_data") or []
                first = order_data[0] if order_data and isinstance(order_data[0], dict) else {}
                child = first.get("child_order_details") if isinstance(first, dict) else None
                return {
                    "status": "ok" if ok else "error",
                    "status_code": r.status_code,
                    "order_id": first.get("order_id"),
                    "order_status": first.get("order_status"),
                    "child_order_id": child.get("order_id") if isinstance(child, dict) else None,
                    "child_order_status": child.get("order_status") if isinstance(child, dict) else None,
                    "body": body,
                }
        except Exception as exc:
            logger.error("INDmoneyBroker._place_smart_order failed: %s", exc)
            return {"status": "error", "message": str(exc)}

    async def modify_smart_order(self, order_id: str, **fields) -> dict:
        """POST /smart/order/modify — adjust an existing smart order's SL/target
        legs (e.g. ratcheting a trailing SL's sl_trigger_price/sl_limit_price
        as price moves favorably). ``fields`` are passed through verbatim
        (order_id plus whichever of sl_trigger_price/sl_limit_price/
        tgt_trigger_price/tgt_limit_price are being changed)."""
        if not self._token:
            return {"status": "error", "message": "not_configured"}
        payload = {"order_id": order_id, **fields}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{INDSTOCKS_BASE}/smart/order/modify",
                    headers=self._headers(),
                    json=payload,
                )
                try:
                    body = r.json()
                except Exception:
                    body = r.text
                ok = (
                    200 <= r.status_code < 300
                    and isinstance(body, dict)
                    and body.get("status") == "success"
                )
                return {"status": "ok" if ok else "error", "status_code": r.status_code, "body": body}
        except Exception as exc:
            logger.error("INDmoneyBroker.modify_smart_order failed: %s", exc)
            return {"status": "error", "message": str(exc)}

    async def cancel_smart_order(self, order_id: str) -> dict:
        """POST /smart/order/cancel — cancel a pending smart (GTT-style) order."""
        if not self._token:
            return {"status": "error", "message": "not_configured"}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{INDSTOCKS_BASE}/smart/order/cancel",
                    headers=self._headers(),
                    json={"order_id": order_id},
                )
                try:
                    body = r.json()
                except Exception:
                    body = r.text
                ok = (
                    200 <= r.status_code < 300
                    and isinstance(body, dict)
                    and body.get("status") == "success"
                )
                return {"status": "ok" if ok else "error", "status_code": r.status_code, "body": body}
        except Exception as exc:
            logger.error("INDmoneyBroker.cancel_smart_order failed: %s", exc)
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

    async def warm_instrument_cache(self, sources: tuple[str, ...] = ("equity", "fno")) -> None:
        """Pre-fetch instrument masters for the given sources, in parallel.

        Call once at process startup (web server / Telegram bot) so the
        first live /search or /buy doesn't pay the full CSV download —
        previously the dominant cost behind a "slow" first search of the day.
        """
        await asyncio.gather(*(self._cached_instruments(s) for s in sources))

    async def resolve_security_id(
        self, symbol: str, source: str = "equity", exchange: str | None = None,
    ) -> str | None:
        """Resolve a trading symbol to its INDstocks ``security_id``.

        Uses the instrument-master CSV (``GET /market/instruments`` via
        ``get_instruments``). Per the documented schema the CSV headers are
        UPPER_SNAKE_CASE — ``SECURITY_ID`` and ``TRADING_SYMBOL`` (with
        ``SYMBOL_NAME``/``CUSTOM_SYMBOL`` as secondary matches). Returns None
        if the symbol is not found.

        CAUTION for options: for indices with a weekly series (NIFTY, SENSEX)
        multiple weekly contracts in the same month can share an identical
        ``TRADING_SYMBOL`` (INDstocks renders that column month-granular, e.g.
        "NIFTY-JUL2026-27500-PE", for every Thursday in July) and differ only
        by ``EXPIRY_DATE``/``SECURITY_ID``. Matching on symbol text alone is
        therefore AMBIGUOUS for those — prefer resolving directly by
        security_id (returned by search_instruments) whenever the caller
        already has a specific contract selected — this symbol-text path
        exists for the Telegram /buy /sell flow where the user can only type
        a symbol string.

        exchange (2026-07-15): the "equity" instrument master carries BOTH
        NSE and BSE rows for any dual-listed stock, distinguished only by the
        ``EXCH`` column — matching on symbol text alone with no exchange
        filter silently returns whichever row the CSV lists first (in
        practice usually the NSE row), a likely root cause of BSE
        holdings/positions on the /positions page resolving the wrong
        security_id and then never receiving a live-price tick (stuck/zero
        LTP) — not yet confirmed against a real BSE position's raw EXCH
        value, hence the one-time discovery log below. When given, rows are
        filtered to an exact ``EXCH`` match first; only if no
        exchange-matching row exists does this fall back to the first
        symbol-text match (preserves prior behavior for callers that don't
        pass an exchange, e.g. the Telegram /buy flow).
        """
        if not symbol:
            return None
        target = symbol.strip().upper()
        want_exchange = exchange.strip().upper() if exchange else None
        rows = await self._cached_instruments(source)
        fallback_sec_id: str | None = None
        fallback_row: dict | None = None
        exact_match_row: dict | None = None
        for row_up in rows:
            sym = str(
                row_up.get("TRADING_SYMBOL")
                or row_up.get("SYMBOL_NAME")
                or row_up.get("CUSTOM_SYMBOL")
                or ""
            ).strip().upper()
            if sym != target:
                continue
            sec_id = row_up.get("SECURITY_ID")
            sec_id = str(sec_id) if sec_id else None
            if fallback_sec_id is None:
                fallback_sec_id = sec_id
                fallback_row = row_up
            if want_exchange is None:
                return sec_id
            row_exch = str(row_up.get("EXCH") or "").strip().upper()
            if row_exch == want_exchange:
                exact_match_row = row_up
                return sec_id
        if want_exchange is not None and exact_match_row is None and fallback_row is not None:
            # No row's EXCH matched the requested exchange — either this
            # symbol genuinely isn't listed there, or EXCH uses a different
            # string than "NSE"/"BSE" than assumed. Logged once per call
            # (not per row) so a real BSE position's actual EXCH value can be
            # confirmed from live logs before assuming this fallback path is
            # ever actually hit for a real dual-listed stock.
            logger.info(
                "INDmoneyBroker.resolve_security_id: no EXCH=%s row for symbol=%s (source=%s); "
                "falling back to first match with EXCH=%r",
                want_exchange, target, source, fallback_row.get("EXCH"),
            )
        return fallback_sec_id

    async def resolve_security_name(self, security_id: str, source: str = "equity") -> str | None:
        """Reverse of resolve_security_id — look up the instrument master's
        display name for a bare ``security_id``.

        get_positions()/get_holdings() (2026-07-15) fall back to this when
        INDstocks' position/holding row omits ``trading_symbol`` (confirmed
        on a same-day position that had already netted to zero — INDstocks
        blanks the whole descriptive payload once a position is flat, not
        just the quantity), so the /positions page shows a real name (e.g.
        "SENSEX 16 JUL 77800 CE") instead of the raw numeric id. Tries both
        the "fno" and "equity" instrument masters if the given source has no
        match, since a holding/position's `source` guess (equity vs fno) can
        be wrong for the same reason trading_symbol was missing. Returns
        None if not found in either.
        """
        if not security_id:
            return None
        target = str(security_id).strip()
        for src in (source, "fno" if source != "fno" else "equity"):
            rows = await self._cached_instruments(src)
            for row_up in rows:
                sec_id = str(row_up.get("SECURITY_ID") or "").strip()
                if sec_id != target:
                    continue
                name = (
                    row_up.get("TRADING_SYMBOL")
                    or row_up.get("SYMBOL_NAME")
                    or row_up.get("CUSTOM_SYMBOL")
                )
                if name:
                    return str(name)
        return None

    async def search_instruments(self, query: str, source: str = "equity", limit: int = 15) -> list[dict]:
        """Search the instrument master for symbols matching ``query`` — powers
        the /trade page's autocomplete and the Telegram /search command.

        Match order: symbols starting with the query rank before symbols that
        merely contain it, so typing "REL" surfaces RELIANCE before a ticker
        that happens to contain "REL" mid-string.

        Distinct contracts are deduped by ``security_id``, NOT by the display
        symbol string — INDstocks' TRADING_SYMBOL for index options is
        month-granular (e.g. "NIFTY-JUL2026-27500-PE" for every weekly
        contract that month on NIFTY/SENSEX, which still run a weekly series
        post the Nov-2024 SEBI rationalization — see src/market/calendar.py's
        _MONTHLY_ONLY_INDICES). Deduping on the symbol string alone silently
        collapsed every weekly expiry down to one row. ``expiry`` is exposed
        (from EXPIRY_DATE) so the caller/UI can show which specific date each
        result is, and ``security_id`` is returned so the caller can act on
        the EXACT contract the user picked rather than re-resolving by
        (ambiguous) symbol text later.
        """
        target = query.strip().upper()
        if not target:
            return []
        rows = await self._cached_instruments(source)

        starts, contains = [], []
        seen = set()
        logged_raw_row = False
        for row in rows:
            sym = str(row.get("TRADING_SYMBOL") or row.get("SYMBOL_NAME") or "").strip().upper()
            if not sym:
                continue
            if target not in sym:
                continue
            sec_id = str(row.get("SECURITY_ID") or "").strip()
            dedup_key = sec_id or sym  # fall back to symbol text if no id (shouldn't happen)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            if not logged_raw_row:
                # One-time discovery log (2026-07-12) — need the real column
                # name INDstocks uses for lot size (for per-contract "lots"
                # UI support) before wiring anything up; guessing a field
                # name here would repeat the exact mistake the segment bug
                # already cost us. Logged once per search call, not per row.
                logger.info("INDmoneyBroker.search_instruments raw row sample (%s): %s", source, row)
                logged_raw_row = True
            name = str(row.get("INSTRUMENT_NAME") or row.get("SYMBOL_NAME") or sym).strip()
            exch = str(row.get("EXCH") or "NSE").strip().upper()
            expiry = str(row.get("EXPIRY_DATE") or "").strip()
            # LOT_UNITS confirmed 2026-07-12 from a real instrument-master row
            # (SENSEX PE: 'LOT_UNITS': '20', matching the exchange-published
            # lot size exactly) — the exchange-mandated multiple an order's
            # qty must be a whole multiple of. Absent/unparseable for equity
            # rows (no lot concept there), which is the correct signal for
            # the UI to fall back to raw share quantity.
            lot_raw = row.get("LOT_UNITS")
            try:
                lot_size = int(float(lot_raw)) if lot_raw not in (None, "") else None
            except (TypeError, ValueError):
                lot_size = None
            entry = {
                "symbol": sym, "name": name, "exchange": exch,
                "segment": row.get("SEGMENT", ""), "expiry": expiry,
                "security_id": sec_id or None,
                "lot_size": lot_size,
            }
            (starts if sym.startswith(target) else contains).append(entry)

        # Sort by (symbol length, expiry date) so same-named weekly contracts
        # come back in chronological order instead of arbitrary CSV order.
        starts.sort(key=lambda e: (len(e["symbol"]), e["expiry"]))
        contains.sort(key=lambda e: (len(e["symbol"]), e["expiry"]))
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
