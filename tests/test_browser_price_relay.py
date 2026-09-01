"""Tests for src/execution/browser_price_relay.py — fans one shared
upstream INDstocks price stream out to multiple browser WebSocket clients,
with refcounted subscribe/unsubscribe so N tabs watching the same instrument
only pay for one upstream subscription."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


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


class TestConsumeDeathRecovery:
    """Regression coverage for the confirmed live bug: once _consume exits
    for any reason not internally retried by stream_prices()'s own
    reconnect loop, self._task stayed set to the now-completed task
    forever, so _ensure_subscribed's `if self._task is None` check never
    re-triggered for any later subscriber. The relay's browser-facing
    WebSocket handshake always succeeds (it's a separate connection from
    the upstream one), so this was invisible as a "connects fine, badge
    says Live, price never updates again" symptom -- indistinguishable
    from a quiet market unless reproduced directly like this."""

    @pytest.mark.anyio
    async def test_task_resets_to_none_after_consume_raises(self):
        from src.execution.browser_price_relay import BrowserPriceRelay

        relay = BrowserPriceRelay()

        async def dying_stream(*a, **kw):
            raise RuntimeError("simulated upstream failure")
            yield  # pragma: no cover - makes this an async generator

        with patch("src.execution.browser_price_relay.stream_prices", side_effect=dying_stream):
            await relay.register(["NSE:2885"])
            await asyncio.sleep(0.05)  # let the background task run to completion

        assert relay._task is None, (
            "self._task must reset to None once _consume exits, or every "
            "future subscriber silently pushes into a dead queue forever"
        )
        assert relay._updates is None

    @pytest.mark.anyio
    async def test_second_subscriber_recovers_after_first_consume_dies(self):
        """The actual end-to-end regression: subscriber #2 (e.g. a page
        reload, or a second symbol picked on trade.html) must receive real
        ticks even though subscriber #1's underlying stream already died."""
        from src.execution.browser_price_relay import BrowserPriceRelay

        relay = BrowserPriceRelay()

        async def dying_stream(*a, **kw):
            raise RuntimeError("simulated upstream failure")
            yield  # pragma: no cover

        with patch("src.execution.browser_price_relay.stream_prices", side_effect=dying_stream):
            sub_id1, _ = await relay.register(["NSE:2885"])
            await asyncio.sleep(0.05)
            await relay.unregister(sub_id1)

        with patch("src.execution.browser_price_relay.stream_prices", return_value=_fake_stream(
            [{"instrument": "2885", "data": {"ltp": 1500.0}}]
        )):
            sub_id2, queue2 = await relay.register(["NSE:2885"])
            await asyncio.sleep(0.05)

        tick = queue2.get_nowait()
        assert tick == {"instrument": "NSE:2885", "ltp": 1500.0}
        await relay.unregister(sub_id2)


class TestSnapshot:

    def test_returns_none_when_no_data(self):
        from src.execution.browser_price_relay import BrowserPriceRelay
        relay = BrowserPriceRelay()
        assert relay.snapshot("NSE:2885") is None

    def test_returns_cached_value(self):
        import time

        from src.execution.browser_price_relay import BrowserPriceRelay
        relay = BrowserPriceRelay()
        relay._prices["NSE:2885"] = (1426.5, time.monotonic())
        assert relay.snapshot("NSE:2885") == 1426.5

    def test_returns_none_when_stale(self):
        import time

        from src.execution.browser_price_relay import BrowserPriceRelay
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
