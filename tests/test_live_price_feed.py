"""Tests for src/monitor/live_price_feed.py — LivePriceCache (Piece B).

The WS stream is always mocked — no real network calls. Index resolution
uses _INDEX_WS_TOKENS (NIDX:/BIDX:, a different namespace from
InstrumentResolver's REST scrip-code convention); equity resolution goes
through InstrumentResolver.KNOWN_SCRIP_CODES + a separator swap, which is
also instant/no-I/O for the symbols these tests use.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest


async def _fake_stream(messages, subscription_updates=None, **_kw):
    for m in messages:
        yield m


class TestInstrumentResolution:

    @pytest.mark.anyio
    async def test_nifty_and_sensex_resolve_to_index_ws_tokens(self):
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        with patch("src.monitor.live_price_feed.stream_prices", side_effect=_fake_stream):
            await cache.refresh_subscriptions()

        assert cache._symbol_to_instrument["NIFTY"] == "NIDX:26000"
        assert cache._symbol_to_instrument["SENSEX"] == "BIDX:1"

    @pytest.mark.anyio
    async def test_banknifty_extra_symbol_resolves_to_index_ws_token(self):
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        with patch("src.monitor.live_price_feed.stream_prices", side_effect=_fake_stream):
            await cache.refresh_subscriptions(["BANKNIFTY"])

        assert cache._symbol_to_instrument["BANKNIFTY"] == "NIDX:26009"
        assert "NIFTY" in cache._symbol_to_instrument  # watched indices always included

    @pytest.mark.anyio
    async def test_bankex_has_no_verified_token_stays_unresolved(self):
        """BANKEX is a known index (InstrumentResolver.KNOWN_SCRIP_CODES) but
        has no confirmed NIDX:/BIDX: token — it must NOT fall through to the
        REST NSE_/BSE_ scrip code, which would silently subscribe to the
        wrong segment for an index."""
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        with patch("src.monitor.live_price_feed.stream_prices", side_effect=_fake_stream):
            await cache.refresh_subscriptions(["BANKEX"])

        assert "BANKEX" not in cache._symbol_to_instrument
        assert cache.get("BANKEX") is None

    @pytest.mark.anyio
    async def test_equity_symbol_resolves_via_resolver_with_separator_swap(self):
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        with patch("src.monitor.live_price_feed.stream_prices", side_effect=_fake_stream), \
             patch.object(cache._resolver, "resolve", side_effect=lambda s, **kw:
                          "NSE_2885" if s == "INFY" else None):
            await cache.refresh_subscriptions(["INFY"])

        assert cache._symbol_to_instrument["INFY"] == "NSE:2885"

    @pytest.mark.anyio
    async def test_unresolvable_symbol_is_skipped_not_fatal(self):
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        with patch("src.monitor.live_price_feed.stream_prices", side_effect=_fake_stream), \
             patch.object(cache._resolver, "resolve", return_value=None):
            await cache.refresh_subscriptions(["NOTAREALSYMBOL"])

        assert "NOTAREALSYMBOL" not in cache._symbol_to_instrument
        assert "NIFTY" in cache._symbol_to_instrument


class TestCacheGet:

    def test_get_returns_none_when_never_subscribed(self):
        from src.monitor.live_price_feed import LivePriceCache
        cache = LivePriceCache()
        assert cache.get("NIFTY") is None

    @pytest.mark.anyio
    async def test_get_returns_none_when_subscribed_but_no_message_yet(self):
        from src.monitor.live_price_feed import LivePriceCache
        cache = LivePriceCache()
        with patch("src.monitor.live_price_feed.stream_prices", side_effect=_fake_stream):
            await cache.refresh_subscriptions()
            if cache._task is not None:
                await cache._task
        assert cache.get("NIFTY") is None

    def test_get_returns_none_for_stale_entry(self):
        import time

        from src.monitor.live_price_feed import _MAX_STALENESS_SECONDS, LivePriceCache

        cache = LivePriceCache()
        cache._symbol_to_instrument = {"NIFTY": "NIDX:26000"}
        cache._prices["NIDX:26000"] = (24500.0, time.monotonic() - (_MAX_STALENESS_SECONDS + 5))
        assert cache.get("NIFTY") is None

    def test_get_returns_fresh_value(self):
        import time

        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        cache._symbol_to_instrument = {"NIFTY": "NIDX:26000"}
        cache._prices["NIDX:26000"] = (24500.0, time.monotonic())
        assert cache.get("NIFTY") == 24500.0

    def test_get_is_case_insensitive(self):
        import time

        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        cache._symbol_to_instrument = {"NIFTY": "NIDX:26000"}
        cache._prices["NIDX:26000"] = (24500.0, time.monotonic())
        assert cache.get("nifty") == 24500.0


class TestStreamConsumption:

    @pytest.mark.anyio
    async def test_cache_updates_from_fake_stream(self):
        from src.monitor.live_price_feed import LivePriceCache

        messages = [
            {"mode": "ltp", "instrument": "26000", "timestamp": 1, "data": {"ltp": 24512.35}},
            {"mode": "ltp", "instrument": "1", "timestamp": 2, "data": {"ltp": 80123.1}},
        ]
        cache = LivePriceCache()
        with patch("src.monitor.live_price_feed.stream_prices",
                   side_effect=lambda *a, **kw: _fake_stream(messages)):
            await cache.refresh_subscriptions()
            await cache._task  # fake stream is finite — task completes on its own

        assert cache.get("NIFTY") == 24512.35
        assert cache.get("SENSEX") == 80123.1

    @pytest.mark.anyio
    async def test_message_with_unknown_instrument_is_ignored(self):
        from src.monitor.live_price_feed import LivePriceCache

        messages = [{"mode": "ltp", "instrument": "999999", "data": {"ltp": 1.0}}]
        cache = LivePriceCache()
        with patch("src.monitor.live_price_feed.stream_prices",
                   side_effect=lambda *a, **kw: _fake_stream(messages)):
            await cache.refresh_subscriptions()
            await cache._task

        assert cache.get("NIFTY") is None
        assert cache.get("SENSEX") is None

    @pytest.mark.anyio
    async def test_message_missing_ltp_is_ignored(self):
        from src.monitor.live_price_feed import LivePriceCache

        messages = [{"mode": "ltp", "instrument": "26000", "data": {}}]
        cache = LivePriceCache()
        with patch("src.monitor.live_price_feed.stream_prices",
                   side_effect=lambda *a, **kw: _fake_stream(messages)):
            await cache.refresh_subscriptions()
            await cache._task

        assert cache.get("NIFTY") is None

    @pytest.mark.anyio
    async def test_no_resolvable_symbols_starts_no_task(self, monkeypatch):
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        monkeypatch.setattr("src.monitor.live_price_feed._INDEX_WS_TOKENS", {})
        with patch("src.monitor.live_price_feed.stream_prices", side_effect=_fake_stream), \
             patch.object(cache._resolver, "KNOWN_SCRIP_CODES", {}), \
             patch.object(cache._resolver, "resolve", return_value=None):
            await cache.refresh_subscriptions([])
        assert cache._task is None


class TestLivePriceCacheOnTick:
    """Piece C (2026-07-11) — on_tick lets index-move/wall-hold checks fire
    the instant a price ticks, instead of waiting for the next poll."""

    @pytest.mark.anyio
    async def test_on_tick_fires_for_matching_symbol(self):
        from src.monitor.live_price_feed import LivePriceCache

        ticks = []

        async def on_tick(symbol, ltp):
            ticks.append((symbol, ltp))

        messages = [{"mode": "ltp", "instrument": "26000", "data": {"ltp": 24555.5}}]
        cache = LivePriceCache(on_tick=on_tick)
        with patch("src.monitor.live_price_feed.stream_prices",
                   side_effect=lambda *a, **kw: _fake_stream(messages)):
            await cache.refresh_subscriptions()
            await cache._task

        assert ("NIFTY", 24555.5) in ticks

    @pytest.mark.anyio
    async def test_on_tick_exception_does_not_kill_stream(self):
        from src.monitor.live_price_feed import LivePriceCache

        async def bad_on_tick(symbol, ltp):
            raise RuntimeError("boom")

        messages = [
            {"mode": "ltp", "instrument": "26000", "data": {"ltp": 24500.0}},
            {"mode": "ltp", "instrument": "26000", "data": {"ltp": 24510.0}},
        ]
        cache = LivePriceCache(on_tick=bad_on_tick)
        with patch("src.monitor.live_price_feed.stream_prices",
                   side_effect=lambda *a, **kw: _fake_stream(messages)):
            await cache.refresh_subscriptions()
            await cache._task

        assert cache.get("NIFTY") == 24510.0

    @pytest.mark.anyio
    async def test_no_on_tick_configured_does_not_error(self):
        from src.monitor.live_price_feed import LivePriceCache

        messages = [{"mode": "ltp", "instrument": "26000", "data": {"ltp": 24500.0}}]
        cache = LivePriceCache()  # on_tick=None by default
        with patch("src.monitor.live_price_feed.stream_prices",
                   side_effect=lambda *a, **kw: _fake_stream(messages)):
            await cache.refresh_subscriptions()
            await cache._task

        assert cache.get("NIFTY") == 24500.0


class TestPersistentConnectionSubscribeUnsubscribe:
    """Confirmed against api-docs.indstocks.com/Websockets/: subscribe/
    unsubscribe are messages on an already-open connection, not a
    reconnect — so refresh_subscriptions must push incremental updates
    rather than restarting the stream."""

    @pytest.mark.anyio
    async def test_first_call_starts_exactly_one_task(self):
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        with patch("src.monitor.live_price_feed.stream_prices", side_effect=_fake_stream):
            await cache.refresh_subscriptions(["BANKNIFTY"])
            first_task = cache._task
            assert first_task is not None

            await cache.refresh_subscriptions(["BANKNIFTY"])  # unchanged set — no-op
            assert cache._task is first_task  # same task, never restarted

    @pytest.mark.anyio
    async def test_new_position_pushes_subscribe_not_restart(self):
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        with patch("src.monitor.live_price_feed.stream_prices", side_effect=_fake_stream):
            await cache.refresh_subscriptions(["BANKNIFTY"])
            first_task = cache._task

            await cache.refresh_subscriptions(["BANKNIFTY", "FINNIFTY"])  # position opened
            assert cache._task is first_task  # still the same connection
            assert cache._updates.qsize() == 1
            update = cache._updates.get_nowait()
            assert update == {"action": "subscribe", "mode": "ltp", "instruments": ["NIDX:26037"]}
            assert "FINNIFTY" in cache._symbol_to_instrument

    @pytest.mark.anyio
    async def test_closed_position_pushes_unsubscribe(self):
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        with patch("src.monitor.live_price_feed.stream_prices", side_effect=_fake_stream):
            await cache.refresh_subscriptions(["BANKNIFTY", "FINNIFTY"])
            await cache.refresh_subscriptions(["BANKNIFTY"])  # FINNIFTY position closed

            update = cache._updates.get_nowait()
            assert update == {"action": "unsubscribe", "mode": "ltp", "instruments": ["NIDX:26037"]}
            assert "FINNIFTY" not in cache._symbol_to_instrument

    @pytest.mark.anyio
    async def test_closed_position_price_evicted_from_cache(self):
        import time

        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        with patch("src.monitor.live_price_feed.stream_prices", side_effect=_fake_stream):
            await cache.refresh_subscriptions(["BANKNIFTY"])
            cache._prices["NIDX:26009"] = (50000.0, time.monotonic())
            assert cache.get("BANKNIFTY") == 50000.0

            await cache.refresh_subscriptions([])  # position closed
            assert cache.get("BANKNIFTY") is None
            assert "NIDX:26009" not in cache._prices

    def test_stop_cancels_running_task_and_clears_updates_queue(self):
        from unittest.mock import MagicMock

        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        fake_task = MagicMock()
        cache._task = fake_task
        cache._updates = asyncio.Queue()
        cache.stop()
        fake_task.cancel.assert_called_once()
        assert cache._task is None
        assert cache._updates is None
