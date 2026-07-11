"""Tests for src/monitor/position_price_feed.py (Piece C).

The WS stream and INDmoney F&O instruments CSV fetch are always mocked —
no real network calls.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch


async def _fake_stream(messages, subscription_updates=None, **_kw):
    for m in messages:
        yield m


_FNO_ROWS = [
    {
        "underlying_symbol": "BANKNIFTY", "option_type": "CE",
        "strike_price": "52000", "expiry": "2026-07-30",
        "security_id": "12345", "exchange": "NSE",
    },
    {
        "underlying_symbol": "NIFTY", "option_type": "PE",
        "strike_price": "24000", "expiry": "2026-07-09",
        "security_id": "67890", "exchange": "NSE",
    },
    {
        "underlying_symbol": "SENSEX", "option_type": "CE",
        "strike_price": "80000", "expiry": "30-Jul-2026",
        "security_id": "555", "exchange": "BSE",
    },
    # Monthly Zerodha contract — pos["expiry"] would be "2026-07-01" (day
    # forced to 01, exact day not encoded) but the CSV has the real date.
    {
        "underlying_symbol": "FINNIFTY", "option_type": "CE",
        "strike_price": "23000", "expiry": "2026-07-28",
        "security_id": "999", "exchange": "NSE",
    },
]


class TestPositionInstrumentResolver:

    def _resolver(self):
        from src.monitor.position_price_feed import PositionInstrumentResolver
        r = PositionInstrumentResolver()
        r._rows = list(_FNO_ROWS)
        import time
        r._rows_loaded_at = time.monotonic()
        return r

    @pytest.mark.anyio
    async def test_resolves_nse_option_to_nfo_instrument(self):
        r = self._resolver()
        result = await r.resolve(
            symbol="BANKNIFTY", expiry="2026-07-30", strike=52000.0,
            option_type="CE", exchange="NSE",
        )
        assert result == "NFO:12345"

    @pytest.mark.anyio
    async def test_resolves_bse_option_to_bfo_instrument(self):
        r = self._resolver()
        result = await r.resolve(
            symbol="SENSEX", expiry="2026-07-30", strike=80000.0,
            option_type="CE", exchange="BSE",
        )
        assert result == "BFO:555"

    @pytest.mark.anyio
    async def test_case_insensitive_symbol_and_option_type(self):
        r = self._resolver()
        result = await r.resolve(
            symbol="banknifty", expiry="2026-07-30", strike=52000.0,
            option_type="ce", exchange="nse",
        )
        assert result == "NFO:12345"

    @pytest.mark.anyio
    async def test_monthly_zerodha_placeholder_day_matches_by_year_month(self):
        """pos["expiry"] == "2026-07-01" for a Zerodha monthly contract (day
        not encoded) must still match the CSV's real "2026-07-28" expiry."""
        r = self._resolver()
        result = await r.resolve(
            symbol="FINNIFTY", expiry="2026-07-01", strike=23000.0,
            option_type="CE", exchange="NSE",
        )
        assert result == "NFO:999"

    @pytest.mark.anyio
    async def test_wrong_strike_does_not_match(self):
        r = self._resolver()
        result = await r.resolve(
            symbol="BANKNIFTY", expiry="2026-07-30", strike=53000.0,
            option_type="CE", exchange="NSE",
        )
        assert result is None

    @pytest.mark.anyio
    async def test_no_match_returns_none(self):
        r = self._resolver()
        result = await r.resolve(
            symbol="RELIANCE", expiry="2026-07-30", strike=3000.0,
            option_type="CE", exchange="NSE",
        )
        assert result is None

    @pytest.mark.anyio
    async def test_unknown_exchange_returns_none(self):
        r = self._resolver()
        result = await r.resolve(
            symbol="BANKNIFTY", expiry="2026-07-30", strike=52000.0,
            option_type="CE", exchange="MCX",
        )
        assert result is None


class TestPositionPriceCacheGet:

    def test_get_returns_none_when_never_subscribed(self):
        from src.monitor.position_price_feed import PositionPriceCache
        cache = PositionPriceCache()
        assert cache.get("pos-1") is None

    def test_get_returns_none_for_stale_entry(self):
        import time
        from src.monitor.position_price_feed import PositionPriceCache, _MAX_STALENESS_SECONDS

        cache = PositionPriceCache()
        cache._position_to_instrument = {"pos-1": "NFO:12345"}
        cache._prices["NFO:12345"] = (55.0, time.monotonic() - (_MAX_STALENESS_SECONDS + 5))
        assert cache.get("pos-1") is None

    def test_get_returns_fresh_value(self):
        import time
        from src.monitor.position_price_feed import PositionPriceCache

        cache = PositionPriceCache()
        cache._position_to_instrument = {"pos-1": "NFO:12345"}
        cache._prices["NFO:12345"] = (55.0, time.monotonic())
        assert cache.get("pos-1") == 55.0


class TestPositionPriceCacheSubscriptions:

    def _pos(self, pos_id, symbol="BANKNIFTY", expiry="2026-07-30", strike=52000.0, option_type="CE"):
        return {"id": pos_id, "symbol": symbol, "expiry": expiry, "strike": strike,
                "option_type": option_type, "exchange": "NSE"}

    @pytest.mark.anyio
    async def test_first_refresh_starts_task_and_subscribes(self):
        from src.monitor.position_price_feed import PositionPriceCache

        cache = PositionPriceCache()
        with patch("src.monitor.position_price_feed.stream_prices", side_effect=_fake_stream), \
             patch.object(cache._resolver, "resolve", return_value="NFO:12345"):
            await cache.refresh_subscriptions([self._pos("pos-1")])

        assert cache._task is not None
        assert cache._position_to_instrument["pos-1"] == "NFO:12345"

    @pytest.mark.anyio
    async def test_unresolvable_position_is_skipped_not_fatal(self):
        from src.monitor.position_price_feed import PositionPriceCache

        cache = PositionPriceCache()
        with patch("src.monitor.position_price_feed.stream_prices", side_effect=_fake_stream), \
             patch.object(cache._resolver, "resolve", return_value=None):
            await cache.refresh_subscriptions([self._pos("pos-1")])

        assert "pos-1" not in cache._position_to_instrument
        assert cache._task is None

    @pytest.mark.anyio
    async def test_closed_position_pushes_unsubscribe_and_evicts_price(self):
        import time
        from src.monitor.position_price_feed import PositionPriceCache

        cache = PositionPriceCache()
        with patch("src.monitor.position_price_feed.stream_prices", side_effect=_fake_stream), \
             patch.object(cache._resolver, "resolve", return_value="NFO:12345"):
            await cache.refresh_subscriptions([self._pos("pos-1")])
            cache._prices["NFO:12345"] = (55.0, time.monotonic())

            await cache.refresh_subscriptions([])  # position closed

        assert cache.get("pos-1") is None
        assert "NFO:12345" not in cache._prices
        update = cache._updates.get_nowait()
        assert update == {"action": "unsubscribe", "mode": "ltp", "instruments": ["NFO:12345"]}

    def test_stop_cancels_task_and_clears_updates(self):
        from src.monitor.position_price_feed import PositionPriceCache
        from unittest.mock import MagicMock

        cache = PositionPriceCache()
        fake_task = MagicMock()
        cache._task = fake_task
        cache._updates = AsyncMock()
        cache.stop()
        fake_task.cancel.assert_called_once()
        assert cache._task is None
        assert cache._updates is None


class TestPositionPriceCacheOnTick:

    @pytest.mark.anyio
    async def test_on_tick_fires_for_matching_position(self):
        from src.monitor.position_price_feed import PositionPriceCache

        ticks = []

        async def on_tick(position_id, ltp):
            ticks.append((position_id, ltp))

        messages = [{"mode": "ltp", "instrument": "12345", "data": {"ltp": 55.5}}]
        cache = PositionPriceCache(on_tick=on_tick)
        with patch("src.monitor.position_price_feed.stream_prices",
                   side_effect=lambda *a, **kw: _fake_stream(messages)), \
             patch.object(cache._resolver, "resolve", return_value="NFO:12345"):
            await cache.refresh_subscriptions([{
                "id": "pos-1", "symbol": "BANKNIFTY", "expiry": "2026-07-30",
                "strike": 52000.0, "option_type": "CE", "exchange": "NSE",
            }])
            await cache._task

        assert ticks == [("pos-1", 55.5)]
        assert cache.get("pos-1") == 55.5

    @pytest.mark.anyio
    async def test_on_tick_exception_does_not_kill_stream(self):
        from src.monitor.position_price_feed import PositionPriceCache

        async def bad_on_tick(position_id, ltp):
            raise RuntimeError("boom")

        messages = [
            {"mode": "ltp", "instrument": "12345", "data": {"ltp": 55.0}},
            {"mode": "ltp", "instrument": "12345", "data": {"ltp": 56.0}},
        ]
        cache = PositionPriceCache(on_tick=bad_on_tick)
        with patch("src.monitor.position_price_feed.stream_prices",
                   side_effect=lambda *a, **kw: _fake_stream(messages)), \
             patch.object(cache._resolver, "resolve", return_value="NFO:12345"):
            await cache.refresh_subscriptions([{
                "id": "pos-1", "symbol": "BANKNIFTY", "expiry": "2026-07-30",
                "strike": 52000.0, "option_type": "CE", "exchange": "NSE",
            }])
            await cache._task

        # both messages processed despite on_tick raising each time
        assert cache.get("pos-1") == 56.0
