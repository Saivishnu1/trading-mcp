"""Tests for src/execution/browser_price_relay.py — fans one shared
upstream INDstocks price stream out to multiple browser WebSocket clients,
with refcounted subscribe/unsubscribe so N tabs watching the same instrument
only pay for one upstream subscription."""
from __future__ import annotations

import asyncio

import pytest
from unittest.mock import AsyncMock, patch


async def _fake_stream(messages):
    for m in messages:
        yield m


class TestRegisterUnregister:

    @pytest.mark.anyio
    async def test_register_starts_upstream_stream_once(self):
        from src.execution.browser_price_relay import BrowserPriceRelay
        relay = BrowserPriceRelay()
        with patch.object(relay, "_consume", AsyncMock(side_effect=lambda *a: asyncio.sleep(10))):
            sub_id1, _ = await relay.register(["NSE:2885"])
            sub_id2, _ = await relay.register(["NSE:2885"])
        assert relay._instrument_refcount["NSE:2885"] == 2
        assert sub_id1 != sub_id2
        await relay.unregister(sub_id1)
        await relay.unregister(sub_id2)

    @pytest.mark.anyio
    async def test_unregister_drops_refcount_to_zero(self):
        from src.execution.browser_price_relay import BrowserPriceRelay
        relay = BrowserPriceRelay()
        with patch.object(relay, "_consume", AsyncMock(side_effect=lambda *a: asyncio.sleep(10))):
            sub_id, _ = await relay.register(["NSE:2885"])
            await relay.unregister(sub_id)
        assert "NSE:2885" not in relay._instrument_refcount

    @pytest.mark.anyio
    async def test_second_subscriber_does_not_resend_subscribe_for_same_instrument(self):
        from src.execution.browser_price_relay import BrowserPriceRelay
        relay = BrowserPriceRelay()
        ensure_mock = AsyncMock()
        with patch.object(relay, "_consume", AsyncMock(side_effect=lambda *a: asyncio.sleep(10))), \
             patch.object(relay, "_ensure_subscribed", ensure_mock):
            await relay.register(["NSE:2885"])
            ensure_mock.assert_awaited_once()
            ensure_mock.reset_mock()
            await relay.register(["NSE:2885"])  # second subscriber, same instrument
            ensure_mock.assert_not_awaited()

    @pytest.mark.anyio
    async def test_unregister_unknown_id_is_noop(self):
        from src.execution.browser_price_relay import BrowserPriceRelay
        relay = BrowserPriceRelay()
        await relay.unregister(9999)  # must not raise


class TestSnapshot:

    def test_returns_none_when_no_data(self):
        from src.execution.browser_price_relay import BrowserPriceRelay
        relay = BrowserPriceRelay()
        assert relay.snapshot("NSE:2885") is None

    def test_returns_cached_value(self):
        from src.execution.browser_price_relay import BrowserPriceRelay
        import time
        relay = BrowserPriceRelay()
        relay._prices["NSE:2885"] = (1426.5, time.monotonic())
        assert relay.snapshot("NSE:2885") == 1426.5

    def test_returns_none_when_stale(self):
        from src.execution.browser_price_relay import BrowserPriceRelay
        import time
        relay = BrowserPriceRelay()
        relay._prices["NSE:2885"] = (1426.5, time.monotonic() - 999)
        assert relay.snapshot("NSE:2885") is None


class TestFanOut:

    @pytest.mark.anyio
    async def test_consume_updates_price_and_fans_out_to_matching_subscribers(self):
        from src.execution.browser_price_relay import BrowserPriceRelay, _Subscriber
        relay = BrowserPriceRelay()
        sub = _Subscriber()
        sub.instruments = {"NSE:2885"}
        relay._subscribers[0] = sub
        relay._instrument_refcount["NSE:2885"] = 1

        messages = [{"instrument": "2885", "data": {"ltp": 1426.5}}]
        with patch("src.execution.browser_price_relay.stream_prices", return_value=_fake_stream(messages)):
            await relay._consume(["NSE:2885"])

        assert relay._prices["NSE:2885"][0] == 1426.5
        tick = sub.queue.get_nowait()
        assert tick == {"instrument": "NSE:2885", "ltp": 1426.5}

    @pytest.mark.anyio
    async def test_does_not_fan_out_to_unsubscribed_tab(self):
        from src.execution.browser_price_relay import BrowserPriceRelay, _Subscriber
        relay = BrowserPriceRelay()
        sub = _Subscriber()
        sub.instruments = {"BSE:500325"}  # different instrument
        relay._subscribers[0] = sub
        relay._instrument_refcount["NSE:2885"] = 1

        messages = [{"instrument": "2885", "data": {"ltp": 1426.5}}]
        with patch("src.execution.browser_price_relay.stream_prices", return_value=_fake_stream(messages)):
            await relay._consume(["NSE:2885"])

        assert sub.queue.empty()

    @pytest.mark.anyio
    async def test_ignores_messages_without_ltp(self):
        from src.execution.browser_price_relay import BrowserPriceRelay
        relay = BrowserPriceRelay()
        relay._instrument_refcount["NSE:2885"] = 1
        messages = [{"instrument": "2885", "data": {}}, {}]
        with patch("src.execution.browser_price_relay.stream_prices", return_value=_fake_stream(messages)):
            await relay._consume(["NSE:2885"])
        assert "NSE:2885" not in relay._prices

    @pytest.mark.anyio
    async def test_full_queue_drops_tick_without_raising(self):
        from src.execution.browser_price_relay import BrowserPriceRelay, _Subscriber
        relay = BrowserPriceRelay()
        sub = _Subscriber()
        sub.instruments = {"NSE:2885"}
        sub.queue = asyncio.Queue(maxsize=1)
        sub.queue.put_nowait({"instrument": "NSE:2885", "ltp": 1.0})  # fill it up
        relay._subscribers[0] = sub
        relay._instrument_refcount["NSE:2885"] = 1

        messages = [{"instrument": "2885", "data": {"ltp": 1426.5}}]
        with patch("src.execution.browser_price_relay.stream_prices", return_value=_fake_stream(messages)):
            await relay._consume(["NSE:2885"])  # must not raise despite full queue


class TestGetRelay:

    def test_returns_singleton(self):
        from src.execution.browser_price_relay import get_relay
        assert get_relay() is get_relay()
