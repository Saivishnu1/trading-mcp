"""Order submission orchestrator — the single entry point for placing an order.

Both surfaces (Telegram bot, web app) call submit_order() so order-placement
logic is never duplicated. It:
  1. optionally resolves a trading symbol → security_id (INDmoney only),
  2. places the order via the broker adapter,
  3. logs the attempt to zerodha.orders (best-effort — never blocks the order),
  4. returns a uniform result dict.
"""
from __future__ import annotations

import asyncio
import logging

from src.brokers.factory import get_broker_adapter
from src.brokers.models import OrderRequest

from .repository import ExecutionRepository

logger = logging.getLogger(__name__)

_repo = ExecutionRepository()


async def resolve_symbol(symbol: str, *, exchange: str, segment: str) -> str | None:
    """Resolve a trading symbol to an INDmoney security_id.

    Uses the fno instrument master for derivatives, equity otherwise.
    Returns None if unresolved.
    """
    broker = get_broker_adapter("indmoney")
    source = "fno" if segment.upper() == "DERIVATIVE" else "equity"
    return await broker.resolve_security_id(symbol, source=source)


async def search_symbols(query: str, *, segment: str | None = None, limit: int = 15) -> list[dict]:
    """Search tradable symbols for autocomplete/dropdown UIs (web + Telegram).

    Without a segment hint, searches both the equity and fno instrument
    masters IN PARALLEL (asyncio.gather — these are two independent HTTP/cache
    lookups with no shared state) and interleaves results so a bare stock
    query ("RELIANCE") and an options query ("NIFTY24200CE") both work from
    one search box. On a cold cache this halves worst-case latency versus
    awaiting the two sources one after another.
    """
    broker = get_broker_adapter("indmoney")
    sources = ["fno" if segment and segment.upper() == "DERIVATIVE" else "equity"] \
        if segment else ["equity", "fno"]

    per_source = await asyncio.gather(
        *(broker.search_instruments(query, source=source, limit=limit) for source in sources)
    )

    # Dedup by security_id (the only column guaranteed unique per contract),
    # not the display symbol — index options (NIFTY/SENSEX) can have several
    # weekly contracts sharing one TRADING_SYMBOL string, distinguished only
    # by security_id/expiry (see search_instruments' docstring).
    seen: set[str] = set()
    results: list[dict] = []
    for source, rows in zip(sources, per_source):
        for row in rows:
            key = row.get("security_id") or row["symbol"]
            if key in seen:
                continue
            seen.add(key)
            # lot_size comes straight from row (INDmoneyBroker.search_instruments
            # parses it from the instrument master's LOT_UNITS column, confirmed
            # 2026-07-12) — real per-contract data, not a guessed/maintained table.
            results.append({**row, "segment": "DERIVATIVE" if source == "fno" else "EQUITY"})
    return results[:limit]


async def get_positions_for_web() -> dict:
    """Unified open-position view for the web /positions page — equity
    holdings + derivative positions from INDmoney, each enriched with the
    security_id needed to subscribe to a live price (Position/Holding
    dataclasses don't carry it — see src/brokers/models.py — so it's
    resolved on demand via resolve_symbol, same path the trade form already
    uses when no dropdown pick is available) and any active SL/target this
    app placed for that symbol (ExecutionRepository.find_active_smart_order_for_symbol).

    Zerodha is deliberately excluded: order placement/modification in this
    stack only ever goes through INDmoney (see ZerodhaBroker.place_order's
    permanent "not available" stub), so a Zerodha-sourced position could be
    displayed but never actionable here — better to keep this view honest
    about what it can actually manage.
    """
    broker = get_broker_adapter("indmoney")
    positions, holdings = await asyncio.gather(broker.get_positions(), broker.get_holdings())

    rows: list[dict] = []
    for entry, kind in [(p, "position") for p in positions] + [(h, "holding") for h in holdings]:
        symbol = entry.symbol
        exchange = entry.exchange.upper()
        segment = "DERIVATIVE" if kind == "position" else "EQUITY"
        security_id = None
        try:
            security_id = await resolve_symbol(symbol, exchange=exchange, segment=segment)
        except Exception as exc:
            logger.debug("get_positions_for_web: resolve_symbol(%s) failed: %s", symbol, exc)

        active_order = None
        try:
            active_order = await _repo.find_active_smart_order_for_symbol(symbol)
        except Exception as exc:
            logger.debug("get_positions_for_web: SL/target lookup for %s failed: %s", symbol, exc)

        rows.append({
            "symbol": symbol,
            "kind": kind,
            "exchange": exchange,
            "segment": segment,
            "security_id": security_id,
            "quantity": entry.quantity,
            "avg_price": entry.avg_price,
            "current_price": entry.current_price,
            "pnl": entry.pnl,
            "product": getattr(entry, "product", "CNC" if kind == "holding" else ""),
            "sl_target": (
                {
                    "broker_order_id": active_order.get("broker_order_id"),
                    "sl_trigger_price": active_order.get("sl_trigger_price"),
                    "tgt_trigger_price": active_order.get("tgt_trigger_price"),
                    "trailing_sl_points": active_order.get("trailing_sl_points"),
                }
                if active_order else None
            ),
        })

    return {"positions": rows, "total": len(rows)}


async def submit_order(
    req: OrderRequest,
    *,
    source: str,
    user_id: str | None,
    broker: str = "indmoney",
) -> dict:
    """Place an order and log it. Never raises — errors come back in the dict.

    Args:
        req:     the fully-populated OrderRequest (security_id must be set).
        source:  "telegram" | "web" | "mcp" — recorded for audit.
        user_id: owner id for multi-user isolation (may be None).
        broker:  adapter name; defaults to indmoney (the only live executor).
    """
    if not req.security_id:
        return {"status": "error", "message": "security_id not resolved for symbol"}

    adapter = get_broker_adapter(broker)
    result = await adapter.place_order(req)

    # Best-effort audit log — a logging failure must not fail the order.
    try:
        await _repo.save_order(
            user_id=user_id,
            broker=broker,
            source=source,
            request=req.to_dict(),
            result=result,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.error("order placed but audit log failed: %s", exc)

    if (
        result.get("status") == "ok"
        and req.trailing_sl_points is not None
        and req.sl_trigger_price is not None
        and result.get("order_id")
    ):
        # INDstocks has no native trailing-SL — start the client-side ratchet
        # (see src/execution/trailing_sl.py) now that the smart order exists.
        from .trailing_sl import start_trailing_sl

        start_trailing_sl(
            result["order_id"],
            exchange=req.exchange,
            security_id=req.security_id,
            side=req.transaction_type,
            trail_points=req.trailing_sl_points,
            initial_sl_trigger=req.sl_trigger_price,
            initial_sl_limit=req.sl_limit_price or req.sl_trigger_price,
            broker_name=broker,
        )

    return result
