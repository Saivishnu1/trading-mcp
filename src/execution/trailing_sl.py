"""Client-side trailing stop-loss manager.

INDstocks has no native trailing-SL field (confirmed absent from
api-docs.indstocks.com/smart_orders/ — see src/brokers/models.py's
OrderRequest docstring). A trailing SL is therefore synthesized here: once a
smart order with an SL leg is placed, we subscribe to that instrument's live
price via src/brokers/streaming.py and ratchet the SL leg's trigger/limit
price upward (for a BUY/long) or downward (for a SELL/short) as the price
moves favorably, calling POST /smart/order/modify each time the stop moves.

The current SL snapshot is persisted to zerodha.trailing_sl_state
(ExecutionRepository) on start and after every successful ratchet — see
rehydrate_trailing_sl(), called once at monitor startup, which resumes every
still-active row so a bot/monitor restart no longer silently drops an
in-flight trailing SL (2026-07-11; previously in-memory only).
"""
from __future__ import annotations

import asyncio
import logging

from src.brokers.factory import get_broker_adapter
from src.brokers.streaming import stream_prices
from src.execution.repository import ExecutionRepository

logger = logging.getLogger(__name__)

# order_id -> asyncio.Task, so a caller can cancel_trailing_sl() later
# (e.g. when the position is closed or the user cancels the smart order).
_active_trailers: dict[str, asyncio.Task] = {}

_repo = ExecutionRepository()


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
            await _repo.upsert_trailing_sl_state(
                order_id=order_id, exchange=exchange, security_id=security_id,
                side=side, broker=broker_name, trail_points=trail_points,
                sl_trigger_price=sl_trigger, sl_limit_price=sl_limit,
            )
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
    _persist: bool = True,
) -> None:
    """Start a background task ratcheting ``order_id``'s SL leg. Idempotent —
    calling twice for the same order_id cancels the previous task first.

    ``_persist=False`` is used by rehydrate_trailing_sl() only — the row
    already exists (that's how we know to resume it), so re-writing it on
    resume would just be a redundant round-trip, not incorrect, but skipped
    for clarity of intent."""
    cancel_trailing_sl(order_id, _deactivate=False)
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
    if _persist:
        try:
            asyncio.get_running_loop()
            asyncio.ensure_future(_repo.upsert_trailing_sl_state(
                order_id=order_id, exchange=exchange, security_id=security_id,
                side=side, broker=broker_name, trail_points=trail_points,
                sl_trigger_price=initial_sl_trigger, sl_limit_price=initial_sl_limit,
            ))
        except RuntimeError:
            pass  # no running loop — nothing to schedule the write onto


def cancel_trailing_sl(order_id: str, *, _deactivate: bool = True) -> bool:
    """Stop trailing ``order_id``'s SL, if a task is running for it, and mark
    its persisted state inactive so a later rehydrate doesn't resume it.
    Returns True if a task was found and cancelled. Safe to call with no
    running event loop (e.g. from a sync context/test) — the DB write is
    simply skipped in that case rather than raising."""
    task = _active_trailers.pop(order_id, None)
    if _deactivate:
        try:
            asyncio.get_running_loop()
            asyncio.ensure_future(_repo.deactivate_trailing_sl_state(order_id))
        except RuntimeError:
            pass  # no running loop — nothing to schedule the write onto
    if task is None:
        return False
    task.cancel()
    return True


def is_trailing(order_id: str) -> bool:
    return order_id in _active_trailers


async def rehydrate_trailing_sl() -> int:
    """Resume every still-active trailing-SL row from the DB. Called once at
    monitor startup (src/monitor/service.py), before the main poll loop, so a
    restart mid-trail doesn't silently strand a stop at its last position.
    Returns the number of trailers resumed. Never raises — a row that fails
    to resume is logged and skipped, not fatal to startup."""
    rows = await _repo.list_active_trailing_sl_state()
    resumed = 0
    for row in rows:
        try:
            start_trailing_sl(
                row["order_id"],
                exchange=row["exchange"],
                security_id=row["security_id"],
                side=row["side"],
                trail_points=row["trail_points"],
                initial_sl_trigger=row["sl_trigger_price"],
                initial_sl_limit=row["sl_limit_price"],
                broker_name=row["broker"],
                _persist=False,
            )
            resumed += 1
        except Exception as exc:
            logger.error("rehydrate_trailing_sl: failed to resume order_id=%s: %s", row.get("order_id"), exc)
    if resumed:
        logger.info("rehydrate_trailing_sl: resumed %d trailing-SL order(s)", resumed)
    return resumed
