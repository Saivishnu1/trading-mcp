"""Tests for src/brokers/streaming.py — INDstocks WebSocket price + order-update
streams. No real network calls: websockets.connect is mocked with an async
context manager yielding canned messages."""
from __future__ import annotations

import json
import os

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class _FakeWebSocket:
    """Minimal async-iterable fake mimicking websockets.connect()'s context manager."""

    def __init__(self, messages: list[str], raise_after: Exception | None = None):
        self._messages = list(messages)
        self._raise_after = raise_after
        self.sent: list[str] = []

    async def send(self, msg: str) -> None:
        self.sent.append(msg)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._messages:
            return self._messages.pop(0)
        if self._raise_after is not None:
            raise self._raise_after
        raise StopAsyncIteration


def _connect_cm(ws: _FakeWebSocket):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=ws)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


class TestAuthHeader:

    def test_includes_token_when_set(self):
        from src.brokers.streaming import _auth_header
        with patch.dict(os.environ, {"INDSTOCKS_TOKEN": "tok123"}):
            assert _auth_header() == {"Authorization": "tok123"}

    def test_empty_when_no_token(self):
        from src.brokers.streaming import _auth_header
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INDSTOCKS_TOKEN", None)
            assert _auth_header() == {}


class TestStreamPrices:

    @pytest.mark.anyio
    async def test_subscribes_and_yields_parsed_messages(self):
        from src.brokers import streaming
        ws = _FakeWebSocket([
            json.dumps({"mode": "ltp", "instrument": "2885", "data": {"ltp": 1426}}),
        ])
        with patch.object(streaming.websockets, "connect", return_value=_connect_cm(ws)):
            received = []
            async for msg in streaming.stream_prices(["NSE:2885"], mode="ltp"):
                received.append(msg)
                break
        assert received == [{"mode": "ltp", "instrument": "2885", "data": {"ltp": 1426}}]
        sent = json.loads(ws.sent[0])
        assert sent == {"action": "subscribe", "mode": "ltp", "instruments": ["NSE:2885"]}

    @pytest.mark.anyio
    async def test_ignores_non_json_messages(self):
        from src.brokers import streaming
        ws = _FakeWebSocket(["not json", json.dumps({"mode": "ltp", "data": {"ltp": 1}})])
        with patch.object(streaming.websockets, "connect", return_value=_connect_cm(ws)):
            received = []
            async for msg in streaming.stream_prices(["NSE:2885"]):
                received.append(msg)
                if len(received) == 1:
                    break
        assert received == [{"mode": "ltp", "data": {"ltp": 1}}]

    @pytest.mark.anyio
    async def test_reconnects_after_drop(self):
        from src.brokers import streaming
        ws1 = _FakeWebSocket([json.dumps({"data": {"ltp": 1}})], raise_after=ConnectionError("dropped"))
        ws2 = _FakeWebSocket([json.dumps({"data": {"ltp": 2}})])
        connect_mock = MagicMock(side_effect=[_connect_cm(ws1), _connect_cm(ws2)])
        with patch.object(streaming.websockets, "connect", connect_mock), \
             patch("src.brokers.streaming.asyncio.sleep", AsyncMock()):
            received = []
            async for msg in streaming.stream_prices(["NSE:2885"]):
                received.append(msg)
                if len(received) == 2:
                    break
        assert received == [{"data": {"ltp": 1}}, {"data": {"ltp": 2}}]


class TestStreamOrderUpdates:

    @pytest.mark.anyio
    async def test_subscribes_with_order_updates_mode(self):
        from src.brokers import streaming
        ws = _FakeWebSocket([json.dumps({"type": "order", "order_id": "X1", "order_status": "FILLED"})])
        with patch.object(streaming.websockets, "connect", return_value=_connect_cm(ws)):
            received = []
            async for msg in streaming.stream_order_updates():
                received.append(msg)
                break
        assert received[0]["order_id"] == "X1"
        sent = json.loads(ws.sent[0])
        assert sent == {"action": "subscribe", "mode": "order_updates"}
