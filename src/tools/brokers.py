"""
Phase 1 — Broker Intelligence tools.

MCP tools for unified multi-broker portfolio access:
  get_unified_holdings, get_unified_positions, get_unified_funds,
  get_unified_orders, get_broker_status.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from datetime import time as _time

import pytz
from mcp.server.fastmcp import FastMCP

from src import meta as _meta
from src.brokers.factory import (
    get_broker_status as _get_broker_status,
)
from src.brokers.indmoney import INDmoneyBroker
from src.brokers.zerodha import ZerodhaBroker
from src.monitor.conditions import MarketConditions

_IST = pytz.timezone("Asia/Kolkata")


def _broker_meta(zerodha_connected: bool = False) -> dict:
    return _meta.build_meta(
        type_=_meta.TYPE_FACT,
        validation_status=_meta.VALIDATION_VERIFIED,
        data_quality=_meta.DQ_VALID,
        source="broker_api",
        account_type="LIVE_ACCOUNT",
        zerodha_connected=zerodha_connected,
    )


async def _check_zerodha_connected() -> bool:
    try:
        return await ZerodhaBroker().is_authenticated()
    except Exception:
        return False


async def _fetch_broker_data(adapter, method_name: str, **method_kwargs) -> dict:
    """Call adapter.<method_name>(**method_kwargs) and return a broker result
    envelope. method_kwargs is empty for every existing caller (positions/
    orders/holdings) — get_unified_funds is the only one that passes
    `segment` (2026-07-13), and only both broker adapters' get_funds()
    accept it, so this stays a true no-op for everything else."""
    try:
        method = getattr(adapter, method_name)
        items = await method(**method_kwargs)
        return {
            "data": [i.to_dict() for i in items],
            "status": "ok",
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


async def _unified(method_name: str, broker: str, *, indmoney_kwargs: dict | None = None) -> dict:
    """Core helper for all unified tools.

    indmoney_kwargs (2026-07-13): passed only to the INDmoney adapter call,
    never Zerodha — get_unified_funds' `segment` is INDmoney's
    detailed_avl_balance vocabulary (e.g. "option_buy"), which has no
    equivalent meaning for Zerodha's margins() segment ("equity"/
    "commodity"); passing the same string to both would silently do the
    wrong thing for Zerodha rather than nothing at all."""
    brokers_result: dict = {}
    combined: list = []

    zerodha_connected = False
    if broker in ("zerodha", "all"):
        z = ZerodhaBroker()
        try:
            auth = await z.is_authenticated()
        except Exception:
            auth = False
        zerodha_connected = auth
        if auth:
            brokers_result["zerodha"] = await _fetch_broker_data(z, method_name)
            if brokers_result["zerodha"]["status"] == "ok":
                combined.extend(brokers_result["zerodha"]["data"])
        else:
            brokers_result["zerodha"] = {"status": "unauthenticated"}

    if broker in ("indmoney", "all"):
        ind = INDmoneyBroker()
        try:
            auth = await ind.is_authenticated()
        except Exception:
            auth = False
        if auth:
            brokers_result["indmoney"] = await _fetch_broker_data(ind, method_name, **(indmoney_kwargs or {}))
            if brokers_result["indmoney"]["status"] == "ok":
                combined.extend(brokers_result["indmoney"]["data"])
        else:
            # Distinguish "token not set" from "token set but invalid"
            import os

            from src.brokers.indmoney import _TOKEN_ENV
            if not os.environ.get(_TOKEN_ENV, ""):
                brokers_result["indmoney"] = {"status": "not_configured"}
            else:
                brokers_result["indmoney"] = {"status": "unauthenticated"}

    payload = {
        "brokers": brokers_result,
        "combined": combined,
        "total": len(combined),
    }
    m = _broker_meta(zerodha_connected=zerodha_connected)
    return _meta.wrap(payload, m)


# Priority B6 (2026-07-11) — exchange -> session-close time, for
# get_all_open_positions. NSE/BSE close at 15:30 IST; MCX trades until 23:30
# IST, past when attention typically shifts away (see also Priority B7's
# session-close risk check, src/monitor/conditions.py::check_session_close_risk).
_SESSION_CLOSE_TIMES = {
    "NSE": "15:30",
    "BSE": "15:30",
    "MCX": "23:30",
}


async def _sl_target_status_by_symbol(broker_name: str) -> dict[str, dict]:
    """Best-effort (symbol -> {sl_status, target_status}) lookup from the
    monitor's own tracked positions/peaks — NOT required for every row, and
    never fails the whole tool if the monitor DB is unavailable (e.g. no
    live Postgres connection in this environment). Matches on symbol only
    (MonitorPosition doesn't share a broker-position identity key with the
    Position dataclass) — a best-effort join, not exact reconciliation."""
    try:
        from src.monitor.repository import MonitorRepository
        repo = MonitorRepository()
        users = await repo.get_active_users()
        if not users:
            return {}
        user_id = users[0]["id"]
        positions = await repo.get_active_positions(user_id)

        status: dict[str, dict] = {}
        for pos in positions:
            if pos.get("broker") != broker_name:
                continue
            peak = await repo.get_peak(pos["id"])
            trailing_sl = peak.get("trailing_sl") if peak else None
            status[pos["symbol"]] = {
                "sl_status": f"trailing_sl={trailing_sl}" if trailing_sl is not None else "not_set",
                "target_status": "monitor_tracked",
            }
        return status
    except Exception:
        # Monitor DB unavailable — degrade gracefully, never fail the tool.
        return {}


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def get_unified_holdings(broker: str = "all") -> dict:
        """Returns combined F&O and equity holdings from Zerodha + INDmoney.

        Args:
            broker: "zerodha" | "indmoney" | "all" (default "all")

        For full networth including MF, US stocks, and liabilities,
        use Indmoney MCP:networth_snapshot instead.

        Returns a unified response with per-broker status and a combined list.
        """
        return await _unified("get_holdings", broker)

    @mcp.tool()
    async def get_unified_positions(broker: str = "all") -> dict:
        """Returns open derivative positions from Zerodha + INDmoney.

        Args:
            broker: "zerodha" | "indmoney" | "all" (default "all")

        For stock details and live prices of positions,
        use Indmoney MCP:get_indian_stocks_details instead.

        Returns a unified response with per-broker status and a combined list.
        """
        return await _unified("get_positions", broker)

    @mcp.tool()
    async def get_unified_funds(broker: str = "all", segment: str | None = None) -> dict:
        """Returns available funds from zerodha, indmoney, or both brokers combined.

        Args:
            broker: "zerodha" | "indmoney" | "all" (default "all")
            segment: INDmoney only — read a specific key straight out of the
                account's detailed_avl_balance instead of the default
                option_buy/eq_cnc/sod_balance chain. Confirmed bug
                (2026-07-13): the default "available" figure under-reported
                real F&O buying power (returned 6852.35 vs the INDmoney
                app's confirmed 15,000+). Every fund entry's
                "segment_breakdown" field carries the account's real
                detailed_avl_balance verbatim — check that first to find the
                correct key name for your account before passing it here;
                the right key isn't independently confirmed yet (see
                INDmoneyBroker.get_funds' docstring for why).

        Returns a unified response with per-broker status and a combined list.
        """
        return await _unified("get_funds", broker, indmoney_kwargs={"segment": segment} if segment else None)

    @mcp.tool()
    async def get_unified_orders(broker: str = "all") -> dict:
        """Returns today's orders from zerodha, indmoney, or both brokers combined.

        Args:
            broker: "zerodha" | "indmoney" | "all" (default "all")

        Returns a unified response with per-broker status and a combined list.
        """
        return await _unified("get_orders", broker)

    @mcp.tool()
    async def get_broker_status() -> dict:
        """Returns authentication status for each configured broker (zerodha, indmoney)."""
        status = await _get_broker_status()
        m = _broker_meta(zerodha_connected=bool(status.get("zerodha", {}).get("authenticated")))
        return _meta.wrap(status, m)

    @mcp.tool()
    async def get_all_open_positions() -> dict:
        """Unified open-position view across Zerodha + INDmoney, all segments,
        in one call (Priority B6, 2026-07-11).

        Aggregates get_unified_positions (index F&O, equity F&O) and
        get_unified_holdings (equity CNC) into a single flat list, adding
        per-entry exchange and session_close_time ("15:30" for NSE/BSE,
        "23:30" for MCX) so extended-hours positions (commodities) are
        visibly distinct from ones that close at the regular NSE bell —
        the gap that let a gas position go unmonitored into MCX's close
        while attention had shifted elsewhere. MCX rows pass through
        whatever the broker API returns for `exchange` as-is; there is no
        dedicated MCX symbol/quote support in this platform yet (see
        docs/research/mcx_scope_20260711.md).

        sl_status/target_status are best-effort, from this platform's own
        position monitor where a match exists — not populated for every row.
        """
        positions_resp, holdings_resp = await asyncio.gather(
            _unified("get_positions", "all"),
            _unified("get_holdings", "all"),
        )

        sl_target_by_symbol = {}
        for broker_name in ("zerodha", "indmoney"):
            sl_target_by_symbol.update(await _sl_target_status_by_symbol(broker_name))

        conditions = MarketConditions()
        now_ist = datetime.now(_IST).replace(tzinfo=None)

        combined: list[dict] = []
        for entry in positions_resp["data"]["combined"] + holdings_resp["data"]["combined"]:
            symbol = entry.get("symbol", "")
            exchange = (entry.get("exchange") or "NSE").upper()
            sl_target = sl_target_by_symbol.get(symbol, {})
            sl_status = sl_target.get("sl_status", "unknown")

            # Priority B7 (2026-07-11) — MCX positions are never tracked by
            # this monitor's trailing-SL system (no MCX symbol resolution
            # exists yet, see docs/research/mcx_scope_20260711.md), so
            # sl_status is genuinely "no SL" for every MCX row today, not a
            # placeholder. Flag proactively when close is within the hour.
            has_sl = sl_status not in ("unknown", "not_set")
            triggered, session_close_note = conditions.check_session_close_risk(
                exchange=exchange,
                has_sl_or_target=has_sl,
                now=now_ist,
                exchange_close_time=_time(23, 30),
            )

            combined.append({
                "symbol": symbol,
                "broker": entry.get("broker"),
                "entry_price": entry.get("avg_price"),
                "current_price": entry.get("current_price"),
                "quantity": entry.get("quantity"),
                "unrealized_pnl": entry.get("pnl"),
                "exchange": exchange,
                "session_close_time": _SESSION_CLOSE_TIMES.get(exchange, "15:30"),
                "sl_status": sl_status,
                "target_status": sl_target.get("target_status", "unknown"),
                "SESSION_CLOSE_RISK": session_close_note if triggered else None,
            })

        payload = {
            "positions": combined,
            "total": len(combined),
            "brokers": {
                "positions": positions_resp["data"]["brokers"],
                "holdings": holdings_resp["data"]["brokers"],
            },
        }
        zerodha_connected = positions_resp["meta"]["zerodha_connected"] or holdings_resp["meta"]["zerodha_connected"]
        return _meta.wrap(payload, _broker_meta(zerodha_connected=zerodha_connected))

    @mcp.tool()
    async def get_indmoney_trades(order_id: str = "", segment: str = "") -> dict:
        """Returns past executed trades from INDmoney (today's filled trades).

        Args:
            order_id: optional — fetch trades for a specific order ID
                      (e.g. "DRV-28131451")
            segment:  "EQUITY" | "DERIVATIVE" | "" (default: both)

        Trade-book shows only filled/executed trades, unlike order-book which
        includes all statuses. Requires segment param per INDstocks API.
        """
        broker = INDmoneyBroker()
        oid = order_id.strip() or None
        seg = segment.strip().upper() or None
        trades = await broker.get_trades(order_id=oid, segment=seg)
        m = _broker_meta(zerodha_connected=await _check_zerodha_connected())
        return _meta.wrap({"trades": trades, "total": len(trades)}, m)

    @mcp.tool()
    async def get_indmoney_raw_data(kind: str = "positions") -> dict:
        """Diagnostic tool (2026-07-16) — returns the UNMODIFIED INDstocks
        response body for a given endpoint, bypassing this app's own
        Position/Holding/Fund normalization entirely.

        Args:
            kind: "positions" | "holdings" | "funds" | "orders"

        Added to investigate a confirmed live discrepancy: a same-day BUY
        order came back SUCCESS (confirmed filled, confirmed still open in
        the INDmoney app itself) yet get_positions() reported quantity=0 for
        it — i.e. get_positions()'s net_quantity/exchange_segment field
        assumptions may not hold for every row shape INDstocks actually
        returns. Use this to see the real JSON before changing that parsing
        again, rather than guess a second time.
        """
        broker = INDmoneyBroker()
        kind_norm = kind.strip().lower()
        if kind_norm == "positions":
            raw = await broker.get_raw_positions()
        elif kind_norm == "holdings":
            raw = await broker.get_raw_holdings()
        elif kind_norm == "funds":
            raw = await broker.get_raw_funds()
        elif kind_norm == "orders":
            raw = await broker.get_raw_order_book()
        else:
            return _meta.wrap(
                {"error": f"unknown kind '{kind}' — use positions|holdings|funds|orders"},
                _broker_meta(),
            )
        m = _broker_meta(zerodha_connected=await _check_zerodha_connected())
        return _meta.wrap({"kind": kind_norm, "raw": raw}, m)
