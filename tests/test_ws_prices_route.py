"""Tests for GET /ws/prices — the raw ASGI websocket route that relays live
prices to the browser without ever exposing INDSTOCKS_TOKEN client-side (see
src/execution/browser_price_relay.py's module docstring).

Drives src.server.app() directly with a simulated ASGI websocket
scope/receive/send, same spirit as test_trade_web.py's HTTP harness.
"""
from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

import pytest

from src.server import app


class _FakeWebSocketSession:
    """Simulates one browser WS connection's receive()/send() for the ASGI
    contract: connect -> accept, then a scripted sequence of client events,
    then disconnect. Records every server->client send() call."""

    def __init__(self, client_events: list[dict]):
        self._events = [{"type": "websocket.connect"}] + list(client_events) + [{"type": "websocket.disconnect"}]
        self.sent: list[dict] = []

    async def receive(self):
        return self._events.pop(0)

    async def send(self, message: dict):
        self.sent.append(message)


async def _run_ws(path: str, query_string: bytes, client_events: list[dict] | None = None):
    session = _FakeWebSocketSession(client_events or [])
    scope = {"type": "websocket", "path": path, "query_string": query_string, "headers": []}
    await app(scope, session.receive, session.send)
    return session.sent


def _text_messages(sent: list[dict]) -> list[dict]:
    return [json.loads(m["text"]) for m in sent if m.get("type") == "websocket.send"]


@pytest.mark.anyio
async def test_rejects_bad_pin():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}):
        sent = await _run_ws("/ws/prices", b"pin=0000&instruments=NSE:2885")
    assert {"type": "websocket.accept"} in sent
    msgs = _text_messages(sent)
    assert msgs[0]["type"] == "error"
    assert "PIN" in msgs[0]["message"]
    assert {"type": "websocket.close"} in sent


@pytest.mark.anyio
async def test_rejects_missing_instruments():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}):
        sent = await _run_ws("/ws/prices", b"pin=1234")
    msgs = _text_messages(sent)
    assert msgs[0]["type"] == "error"
    assert "instrument" in msgs[0]["message"].lower()


@pytest.mark.anyio
async def test_disabled_when_pin_unset():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TRADE_PIN", None)
        sent = await _run_ws("/ws/prices", b"pin=&instruments=NSE:2885")
    msgs = _text_messages(sent)
    assert msgs[0]["type"] == "error"


@pytest.mark.anyio
async def test_sends_snapshot_then_registers_and_unregisters():
    from src.execution import browser_price_relay as bpr
    relay = bpr.BrowserPriceRelay()
    relay._prices["NSE:2885"] = (1426.5, __import__("time").monotonic())
    register_mock = AsyncMock(return_value=(1, __import__("asyncio").Queue()))
    unregister_mock = AsyncMock()
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch.object(bpr, "get_relay", return_value=relay), \
         patch.object(relay, "register", register_mock), \
         patch.object(relay, "unregister", unregister_mock):
        sent = await _run_ws("/ws/prices", b"pin=1234&instruments=NSE:2885")
    msgs = _text_messages(sent)
    assert msgs[0] == {"type": "snapshot", "prices": {"NSE:2885": 1426.5}}
    register_mock.assert_awaited_once_with(["NSE:2885"])
    unregister_mock.assert_awaited_once_with(1)


@pytest.mark.anyio
async def test_multiple_instruments_parsed_from_csv():
    from src.execution import browser_price_relay as bpr
    relay = bpr.BrowserPriceRelay()
    register_mock = AsyncMock(return_value=(1, __import__("asyncio").Queue()))
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch.object(bpr, "get_relay", return_value=relay), \
         patch.object(relay, "register", register_mock), \
         patch.object(relay, "unregister", AsyncMock()):
        await _run_ws("/ws/prices", b"pin=1234&instruments=NSE:2885,BSE:500325")
    register_mock.assert_awaited_once_with(["NSE:2885", "BSE:500325"])


@pytest.mark.anyio
async def test_ticks_from_queue_are_forwarded_to_client():
    import asyncio

    from src.execution import browser_price_relay as bpr
    relay = bpr.BrowserPriceRelay()
    queue: asyncio.Queue = asyncio.Queue()
    queue.put_nowait({"instrument": "NSE:2885", "ltp": 1430.0})
    register_mock = AsyncMock(return_value=(1, queue))

    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch.object(bpr, "get_relay", return_value=relay), \
         patch.object(relay, "register", register_mock), \
         patch.object(relay, "unregister", AsyncMock()):
        sent = await _run_ws("/ws/prices", b"pin=1234&instruments=NSE:2885")

    msgs = _text_messages(sent)
    tick_msgs = [m for m in msgs if m.get("type") == "tick"]
    assert tick_msgs[0] == {"type": "tick", "instrument": "NSE:2885", "ltp": 1430.0}


@pytest.mark.anyio
async def test_non_connect_first_event_is_ignored():
    events = [{"type": "websocket.disconnect"}]  # never sends connect

    async def receive():
        return events.pop(0)

    sent = []

    async def send(message):
        sent.append(message)

    scope = {"type": "websocket", "path": "/ws/prices", "query_string": b"", "headers": []}
    await app(scope, receive, send)
    assert sent == []  # never even accepted
