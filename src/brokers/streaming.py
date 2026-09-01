"""INDstocks WebSocket streaming — live price feed + live order updates.

Contract: api-docs.indstocks.com/Websockets/. Two independent endpoints:

  - Price feed:    wss://ws-prices.indstocks.com/api/v1/ws/prices
                   subscribe:   {"action": "subscribe", "mode": "ltp"|"quote",
                                 "instruments": ["NSE:2885", ...]}
                   unsubscribe: {"action": "unsubscribe", "mode": "ltp"|"quote",
                                 "instruments": ["NSE:2885", ...]}
                   push:        {"mode": "ltp", "instrument": "2885",
                                 "timestamp": ..., "data": {"ltp": 1426}}

    Instrument format is "SEGMENT:token" — NSE:/BSE: for equities (numeric
    security_id), NIDX:/BIDX: for indices (a *different* segment from
    equities, e.g. "NIDX:26000" for NIFTY, "BIDX:1" for SENSEX — see
    src/monitor/live_price_feed.py's module docstring for why this matters).

  - Order updates: wss://ws-order-updates.indstocks.com/api/v1/ws/trades
                   subscribe: {"action": "subscribe", "mode": "order_updates"}
                   push:      {"type": "order", "order_id": ..., "order_status": ...,
                               "filled_quantity": ..., "remaining_quantity": ...,
                               "average_price": ..., "timestamp": ...}

Auth is the same bearer-less ``Authorization`` header used by every INDstocks
REST call, sent at the WebSocket handshake.

Both streams are exposed as async generators (``stream_prices``/
``stream_order_updates``) so callers (the trailing-SL manager, the monitor's
LivePriceCache, a live-quote dashboard tile, etc.) can simply
``async for msg in stream_prices(...)`` without knowing anything about
reconnect/heartbeat handling — that's handled here, once.

``stream_prices`` additionally accepts an optional ``subscription_updates``
queue: pushing a ``{"action": "subscribe"|"unsubscribe", "mode": ...,
"instruments": [...]}`` dict onto it sends that message on the *current* live
connection (per the docs, subscribe/unsubscribe are ordinary messages on an
already-open socket — not a reconnect). The accumulated subscription state
(initial instruments + every update applied since) is replayed automatically
if the connection drops and reconnects, so a caller managing a changing
instrument set never has to reconnect by hand and never silently loses a
subscription across a drop. Callers that don't pass this (trailing_sl.py)
get the exact original fixed-instrument-list behavior.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from collections.abc import AsyncIterator

import websockets

logger = logging.getLogger(__name__)

_TOKEN_ENV = "INDSTOCKS_TOKEN"
PRICE_WS_URL = "wss://ws-prices.indstocks.com/api/v1/ws/prices"
ORDER_UPDATES_WS_URL = "wss://ws-order-updates.indstocks.com/api/v1/ws/trades"

# Reconnect with capped exponential backoff — a dropped connection must not
# take down whatever feature is consuming the stream (trailing-SL, a live
# dashboard, etc.); it should just resume once the socket comes back.
_RECONNECT_BASE_SECONDS = 1.0
_RECONNECT_MAX_SECONDS = 30.0


def _auth_header() -> dict:
    token = os.environ.get(_TOKEN_ENV, "")
    return {"Authorization": token} if token else {}


def _apply_update(update: dict, tracked: dict[str, dict]) -> None:
    """Fold one subscribe/unsubscribe message into `tracked` so a future
    reconnect knows the current accumulated subscription set."""
    mode = update.get("mode", "ltp")
    action = update.get("action")
    instruments = update.get("instruments") or []
    entry = tracked.setdefault(mode, {"instruments": set()})
    if "instruments" not in entry:
        entry["instruments"] = set()
    if action == "subscribe":
        entry["instruments"].update(instruments)
    elif action == "unsubscribe":
        entry["instruments"].difference_update(instruments)


def _drain_pending_updates(updates: asyncio.Queue[dict], tracked: dict[str, dict]) -> None:
    """Apply any updates already sitting in the queue (e.g. queued while the
    connection was down between a drop and this reconnect) synchronously,
    before this connection computes what to subscribe to. Using get_nowait()
    here — rather than relying on the pump task getting a scheduling turn
    before we start reading — avoids a real race: a connection that fails
    immediately (no genuine I/O wait ever occurs) could otherwise cancel the
    pump task before it ever ran, silently dropping a queued update."""
    while True:
        try:
            update = updates.get_nowait()
        except asyncio.QueueEmpty:
            return
        _apply_update(update, tracked)


async def _pump_updates(ws, updates: asyncio.Queue[dict], tracked: dict[str, dict]) -> None:
    """Drain `updates`, forward each subscribe/unsubscribe message onto the
    live connection `ws`, and keep `tracked` in sync so a future reconnect
    replays the current accumulated subscription set — not just whatever
    this generator started with."""
    while True:
        update = await updates.get()
        await ws.send(json.dumps(update))
        _apply_update(update, tracked)


async def _connect_and_subscribe(
    url: str,
    tracked: dict[str, dict],
    subscription_updates: asyncio.Queue[dict] | None,
):
    """Yield raw decoded JSON messages from one WS connection. Raises on
    connect failure so the caller's reconnect loop can back off and retry.

    (Re)plays every subscription in `tracked` on connect — on first connect
    that's just the caller's initial instruments; after a drop it's the full
    accumulated set (initial + every subscribe/unsubscribe applied via
    `subscription_updates` so far), so a reconnect is invisible to whoever is
    consuming stream_prices()."""
    if subscription_updates is not None:
        _drain_pending_updates(subscription_updates, tracked)

    headers = _auth_header()
    async with websockets.connect(url, additional_headers=headers) as ws:
        for mode, entry in tracked.items():
            if "instruments" in entry:
                instruments = sorted(entry["instruments"])
                if not instruments:
                    continue  # nothing to subscribe to yet for this mode
                payload = {"action": "subscribe", "mode": mode, "instruments": instruments}
            else:
                payload = {"action": "subscribe", "mode": mode}
            await ws.send(json.dumps(payload))

        pump_task = (
            asyncio.create_task(_pump_updates(ws, subscription_updates, tracked))
            if subscription_updates is not None else None
        )
        try:
            async for raw in ws:
                try:
                    yield json.loads(raw)
                except (ValueError, TypeError):
                    logger.debug("Non-JSON message on %s: %r", url, raw)
        finally:
            if pump_task is not None:
                pump_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pump_task


async def _reconnecting_stream(
    url: str,
    subscribe_message: dict,
    subscription_updates: asyncio.Queue[dict] | None = None,
) -> AsyncIterator[dict]:
    """Wrap _connect_and_subscribe with indefinite reconnect + backoff.
    Runs until the caller stops iterating (e.g. breaks out of the for-loop
    or cancels the task) — there is no message-count/time limit here."""
    mode = subscribe_message.get("mode", "ltp")
    tracked: dict[str, dict] = {mode: dict(subscribe_message)}
    if "instruments" in tracked[mode]:
        tracked[mode]["instruments"] = set(tracked[mode]["instruments"])

    backoff = _RECONNECT_BASE_SECONDS
    while True:
        try:
            async for msg in _connect_and_subscribe(url, tracked, subscription_updates):
                backoff = _RECONNECT_BASE_SECONDS  # reset after any successful message
                yield msg
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("WS stream %s dropped (%s); reconnecting in %.1fs", url, exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _RECONNECT_MAX_SECONDS)


async def stream_prices(
    instruments: list[str],
    mode: str = "ltp",
    subscription_updates: asyncio.Queue[dict] | None = None,
) -> AsyncIterator[dict]:
    """Stream live prices for ``instruments`` (``"EXCHANGE:security_id"`` strings,
    e.g. ``"NSE:2885"``, or ``"NIDX:token"``/``"BIDX:token"`` for indices).
    ``mode`` is ``"ltp"`` or ``"quote"``.

    ``subscription_updates``: optional ``asyncio.Queue`` the caller can push
    ``{"action": "subscribe"|"unsubscribe", "mode": ..., "instruments": [...]}``
    dicts onto to add/remove instruments on this *same* live connection,
    per api-docs.indstocks.com/Websockets/ — no reconnect required. Omit
    this for the original fixed-instrument-list behavior (trailing_sl.py's
    usage is unchanged).

    Reconnects automatically on drop, replaying the full accumulated
    subscription set. Runs until the consumer stops iterating.
    """
    subscribe_message = {"action": "subscribe", "mode": mode, "instruments": instruments}
    async for msg in _reconnecting_stream(PRICE_WS_URL, subscribe_message, subscription_updates):
        yield msg


async def stream_order_updates() -> AsyncIterator[dict]:
    """Stream live order-status updates (fills, rejections, partial fills)
    for the authenticated account. Reconnects automatically on drop."""
    subscribe_message = {"action": "subscribe", "mode": "order_updates"}
    async for msg in _reconnecting_stream(ORDER_UPDATES_WS_URL, subscribe_message):
        yield msg
