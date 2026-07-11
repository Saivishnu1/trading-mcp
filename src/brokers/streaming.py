"""INDstocks WebSocket streaming — live price feed + live order updates.

Contract: api-docs.indstocks.com/Websockets/. Two independent endpoints:

  - Price feed:    wss://ws-prices.indstocks.com/api/v1/ws/prices
                   subscribe: {"action": "subscribe", "mode": "ltp"|"quote",
                               "instruments": ["NSE:2885", ...]}
                   push:      {"mode": "ltp", "instrument": "2885",
                               "timestamp": ..., "data": {"ltp": 1426}}

  - Order updates: wss://ws-order-updates.indstocks.com/api/v1/ws/trades
                   subscribe: {"action": "subscribe", "mode": "order_updates"}
                   push:      {"type": "order", "order_id": ..., "order_status": ...,
                               "filled_quantity": ..., "remaining_quantity": ...,
                               "average_price": ..., "timestamp": ...}

Auth is the same bearer-less ``Authorization`` header used by every INDstocks
REST call, sent at the WebSocket handshake.

Both streams are exposed as async generators (``stream_prices``/
``stream_order_updates``) so callers (the trailing-SL manager today; the
monitor loop, a live-quote dashboard tile, etc. later) can simply
``async for msg in stream_prices(...)`` without knowing anything about
reconnect/heartbeat handling — that's handled here, once.
"""
from __future__ import annotations

import asyncio
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


async def _connect_and_subscribe(url: str, subscribe_message: dict):
    """Yield raw decoded JSON messages from one WS connection. Raises on
    connect failure so the caller's reconnect loop can back off and retry."""
    headers = _auth_header()
    async with websockets.connect(url, additional_headers=headers) as ws:
        await ws.send(json.dumps(subscribe_message))
        async for raw in ws:
            try:
                yield json.loads(raw)
            except (ValueError, TypeError):
                logger.debug("Non-JSON message on %s: %r", url, raw)


async def _reconnecting_stream(url: str, subscribe_message: dict) -> AsyncIterator[dict]:
    """Wrap _connect_and_subscribe with indefinite reconnect + backoff.
    Runs until the caller stops iterating (e.g. breaks out of the for-loop
    or cancels the task) — there is no message-count/time limit here."""
    backoff = _RECONNECT_BASE_SECONDS
    while True:
        try:
            async for msg in _connect_and_subscribe(url, subscribe_message):
                backoff = _RECONNECT_BASE_SECONDS  # reset after any successful message
                yield msg
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("WS stream %s dropped (%s); reconnecting in %.1fs", url, exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _RECONNECT_MAX_SECONDS)


async def stream_prices(instruments: list[str], mode: str = "ltp") -> AsyncIterator[dict]:
    """Stream live prices for ``instruments`` (``"EXCHANGE:security_id"`` strings,
    e.g. ``"NSE:2885"``). ``mode`` is ``"ltp"`` or ``"quote"``.

    Reconnects automatically on drop. Runs until the consumer stops iterating.
    """
    subscribe_message = {"action": "subscribe", "mode": mode, "instruments": instruments}
    async for msg in _reconnecting_stream(PRICE_WS_URL, subscribe_message):
        yield msg


async def stream_order_updates() -> AsyncIterator[dict]:
    """Stream live order-status updates (fills, rejections, partial fills)
    for the authenticated account. Reconnects automatically on drop."""
    subscribe_message = {"action": "subscribe", "mode": "order_updates"}
    async for msg in _reconnecting_stream(ORDER_UPDATES_WS_URL, subscribe_message):
        yield msg
