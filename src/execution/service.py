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
            results.append({**row, "segment": "DERIVATIVE" if source == "fno" else "EQUITY"})
    return results[:limit]


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

    return result
