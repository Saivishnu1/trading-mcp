"""Client-side trailing stop-loss manager.

INDstocks has no native trailing-SL field (confirmed absent from
api-docs.indstocks.com/smart_orders/ — see src/brokers/models.py's
OrderRequest docstring). A trailing SL is therefore synthesized here: once a
smart order with an SL leg is placed, we subscribe to that instrument's live
price via src/brokers/streaming.py and ratchet the SL leg's trigger/limit
price upward (for a BUY/long) or downward (for a SELL/short) as the price
moves favorably, calling POST /smart/order/modify each time the stop moves.

This is process-local, in-memory state (one asyncio task per trailing order) —
it does not survive a bot restart. That's an accepted limitation for this
first pass: it gives the feature a real, working implementation to build
persistence on top of later, rather than blocking on a durable-store design
now.
"""
from __future__ import annotations

import asyncio
import logging

from src.brokers.factory import get_broker_adapter
from src.brokers.streaming import stream_prices

logger = logging.getLogger(__name__)

# order_id -> asyncio.Task, so a caller can cancel_trailing_sl() later
# (e.g. when the position is closed or the user cancels the smart order).
_active_trailers: dict[str, asyncio.Task] = {}


def _instrument_key(exchange: str, security_id: str) -> str:
    return f"{exchange.upper()}:{security_id}"


async def _trail_loop(
    order_id: str,
    *,
    exchange: str,
    security_id: str,
    side: str,
    trail_points: float,
    initial_sl_trigger: float,
    initial_sl_limit: float,
    broker_name: str,
) -> None:
    """Ratchet the SL leg of ``order_id`` as price moves favorably.

    For a BUY (long): the stop only ever moves UP, tracking
    ``current_price - trail_points``, and never moves down.
    For a SELL (short): the stop only ever moves DOWN, tracking
    ``current_price + trail_points``, and never moves up.
    """
    adapter = get_broker_adapter(broker_name)
    sl_trigger = initial_sl_trigger
    sl_limit = initial_sl_limit
    instrument = _instrument_key(exchange, security_id)

    async for msg in stream_prices([instrument], mode="ltp"):
        data = msg.get("data") if isinstance(msg, dict) else None
        ltp = data.get("ltp") if isinstance(data, dict) else None
        if ltp is None:
            continue
        try:
            ltp = float(ltp)
        except (TypeError, ValueError):
            continue

        if side.upper() == "BUY":
            candidate = ltp - trail_points
            moved = candidate > sl_trigger
        else:
            candidate = ltp + trail_points
            moved = candidate < sl_trigger

        if not moved:
            continue

        delta = candidate - sl_trigger
        new_trigger = sl_trigger + delta
        new_limit = sl_limit + delta
        result = await adapter.modify_smart_order(
            order_id,
            sl_trigger_price=new_trigger,
            sl_limit_price=new_limit,
        )
        if result.get("status") == "ok":
            sl_trigger, sl_limit = new_trigger, new_limit
            logger.info("Trailing SL for %s moved to trigger=%.2f limit=%.2f", order_id, sl_trigger, sl_limit)
        else:
            logger.warning("Trailing SL modify failed for %s: %s", order_id, result.get("message") or result.get("body"))


def start_trailing_sl(
    order_id: str,
    *,
    exchange: str,
    security_id: str,
    side: str,
    trail_points: float,
    initial_sl_trigger: float,
    initial_sl_limit: float,
    broker_name: str = "indmoney",
) -> None:
    """Start a background task ratcheting ``order_id``'s SL leg. Idempotent —
    calling twice for the same order_id cancels the previous task first."""
    cancel_trailing_sl(order_id)
    task = asyncio.create_task(
        _trail_loop(
            order_id,
            exchange=exchange,
            security_id=security_id,
            side=side,
            trail_points=trail_points,
            initial_sl_trigger=initial_sl_trigger,
            initial_sl_limit=initial_sl_limit,
            broker_name=broker_name,
        )
    )
    _active_trailers[order_id] = task


def cancel_trailing_sl(order_id: str) -> bool:
    """Stop trailing ``order_id``'s SL, if a task is running for it.
    Returns True if a task was found and cancelled."""
    task = _active_trailers.pop(order_id, None)
    if task is None:
        return False
    task.cancel()
    return True


def is_trailing(order_id: str) -> bool:
    return order_id in _active_trailers
