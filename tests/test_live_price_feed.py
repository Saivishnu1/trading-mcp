"""Tests for src/monitor/live_price_feed.py — LivePriceCache (Piece B).

The WS stream is always mocked — no real network calls. InstrumentResolver's
KNOWN_SCRIP_CODES table resolves NIFTY/SENSEX/BANKNIFTY instantly with no I/O,
so these tests don't need to mock symbol resolution either.
"""
from __future__ import annotations

import asyncio

import pytest
from unittest.mock import patch


async def _fake_stream(messages):
    for m in messages:
        yield m


class TestInstrumentResolution:

    @pytest.mark.anyio
    async def test_nifty_and_sensex_resolve_to_known_scrip_codes(self):
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        with patch("src.monitor.live_price_feed.stream_prices", return_value=_fake_stream([])):
            await cache.refresh_subscriptions()

        assert cache._symbol_to_instrument["NIFTY"] == "NSE:NIFTY50"
        assert cache._symbol_to_instrument["SENSEX"] == "BSE:40000006"

    @pytest.mark.anyio
    async def test_extra_symbol_resolved_alongside_watched_indices(self):
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        with patch("src.monitor.live_price_feed.stream_prices", return_value=_fake_stream([])):
            await cache.refresh_subscriptions(["BANKNIFTY"])

        assert cache._symbol_to_instrument["BANKNIFTY"] == "NSE:BANKNIFTY"
        assert "NIFTY" in cache._symbol_to_instrument  # watched indices always included

    @pytest.mark.anyio
    async def test_unresolvable_symbol_is_skipped_not_fatal(self):
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        with patch("src.monitor.live_price_feed.stream_prices", return_value=_fake_stream([])), \
             patch.object(cache._resolver, "resolve", side_effect=lambda s, **kw:
                          {"NIFTY": "NSE_NIFTY50", "SENSEX": "BSE_40000006"}.get(s)):
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
        with patch("src.monitor.live_price_feed.stream_prices", return_value=_fake_stream([])):
            await cache.refresh_subscriptions()
            if cache._task is not None:
                await cache._task
        assert cache.get("NIFTY") is None

    def test_get_returns_none_for_stale_entry(self):
        import time
        from src.monitor.live_price_feed import LivePriceCache, _MAX_STALENESS_SECONDS

        cache = LivePriceCache()
        cache._symbol_to_instrument = {"NIFTY": "NSE:NIFTY50"}
        cache._prices["NSE:NIFTY50"] = (24500.0, time.monotonic() - (_MAX_STALENESS_SECONDS + 5))
        assert cache.get("NIFTY") is None

    def test_get_returns_fresh_value(self):
        import time
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        cache._symbol_to_instrument = {"NIFTY": "NSE:NIFTY50"}
        cache._prices["NSE:NIFTY50"] = (24500.0, time.monotonic())
        assert cache.get("NIFTY") == 24500.0

    def test_get_is_case_insensitive(self):
        import time
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        cache._symbol_to_instrument = {"NIFTY": "NSE:NIFTY50"}
        cache._prices["NSE:NIFTY50"] = (24500.0, time.monotonic())
        assert cache.get("nifty") == 24500.0


class TestStreamConsumption:

    @pytest.mark.anyio
    async def test_cache_updates_from_fake_stream(self):
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        messages = [
            {"mode": "ltp", "instrument": "NIFTY50", "timestamp": 1, "data": {"ltp": 24512.35}},
            {"mode": "ltp", "instrument": "40000006", "timestamp": 2, "data": {"ltp": 80123.1}},
        ]
        with patch("src.monitor.live_price_feed.stream_prices", return_value=_fake_stream(messages)):
            await cache.refresh_subscriptions()
            await cache._task  # fake stream is finite — task completes on its own

        assert cache.get("NIFTY") == 24512.35
        assert cache.get("SENSEX") == 80123.1

    @pytest.mark.anyio
    async def test_message_with_unknown_instrument_is_ignored(self):
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        messages = [{"mode": "ltp", "instrument": "999999", "data": {"ltp": 1.0}}]
        with patch("src.monitor.live_price_feed.stream_prices", return_value=_fake_stream(messages)):
            await cache.refresh_subscriptions()
            await cache._task

        assert cache.get("NIFTY") is None
        assert cache.get("SENSEX") is None

    @pytest.mark.anyio
    async def test_message_missing_ltp_is_ignored(self):
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        messages = [{"mode": "ltp", "instrument": "NIFTY50", "data": {}}]
        with patch("src.monitor.live_price_feed.stream_prices", return_value=_fake_stream(messages)):
            await cache.refresh_subscriptions()
            await cache._task

        assert cache.get("NIFTY") is None

    @pytest.mark.anyio
    async def test_no_subscriptions_means_no_task(self):
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        with patch("src.monitor.live_price_feed.stream_prices", return_value=_fake_stream([])), \
             patch.object(cache, "_symbol_to_instrument", {}), \
             patch.object(cache._resolver, "resolve", return_value=None):
            await cache.refresh_subscriptions([])
        assert cache._task is None


class TestResubscribeOnPositionChange:

    @pytest.mark.anyio
    async def test_same_symbol_set_does_not_restart_stream(self):
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        with patch("src.monitor.live_price_feed.stream_prices", return_value=_fake_stream([])), \
             patch.object(cache, "_restart_stream") as mock_restart:
            await cache.refresh_subscriptions(["BANKNIFTY"])
            assert mock_restart.call_count == 1
            await cache.refresh_subscriptions(["BANKNIFTY"])  # unchanged set
            assert mock_restart.call_count == 1  # no-op, no restart

    @pytest.mark.anyio
    async def test_new_position_symbol_restarts_stream(self):
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        with patch("src.monitor.live_price_feed.stream_prices", return_value=_fake_stream([])), \
             patch.object(cache, "_restart_stream") as mock_restart:
            await cache.refresh_subscriptions(["BANKNIFTY"])
            assert mock_restart.call_count == 1
            await cache.refresh_subscriptions(["BANKNIFTY", "FINNIFTY"])  # position opened
            assert mock_restart.call_count == 2
            assert "FINNIFTY" in cache._symbol_to_instrument

    @pytest.mark.anyio
    async def test_position_closed_restarts_stream_with_smaller_set(self):
        from src.monitor.live_price_feed import LivePriceCache

        cache = LivePriceCache()
        with patch("src.monitor.live_price_feed.stream_prices", return_value=_fake_stream([])), \
             patch.object(cache, "_restart_stream") as mock_restart:
            await cache.refresh_subscriptions(["BANKNIFTY", "FINNIFTY"])
            await cache.refresh_subscriptions(["BANKNIFTY"])  # FINNIFTY position closed
            assert mock_restart.call_count == 2
            assert "FINNIFTY" not in cache._symbol_to_instrument

    def test_stop_cancels_running_task(self):
        from src.monitor.live_price_feed import LivePriceCache
        from unittest.mock import MagicMock

        cache = LivePriceCache()
        fake_task = MagicMock()
        cache._task = fake_task
        cache.stop()
        fake_task.cancel.assert_called_once()
        assert cache._task is None
