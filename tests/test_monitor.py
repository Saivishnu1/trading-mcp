"""Tests for src/monitor/ — Phase 9A live position monitor.

Pure-logic modules (trailing_sl, conditions, symbol_resolver parsing, alerts,
scheduler polling math) are tested directly. Repository/bootstrap tests are
skipped when SQLAlchemy is not installed (Windows dev — DB deps are Linux-only,
see src/db/base.py). No real broker, HTTP, or WhatsApp calls are made.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from src.monitor.alerts import WhatsAppAlerter
from src.monitor.conditions import MarketConditions
from src.monitor.scheduler import MarketMonitor
from src.monitor.symbol_resolver import (
    PositionSymbolResolver,
    _normalize_indmoney_row,
    _parse_zerodha_tradingsymbol,
)
from src.monitor.trailing_sl import TrailingSLCalculator

try:
    import sqlalchemy  # noqa: F401
    _HAS_SQLALCHEMY = True
except ImportError:
    _HAS_SQLALCHEMY = False

requires_sqlalchemy = pytest.mark.skipif(
    not _HAS_SQLALCHEMY, reason="sqlalchemy/asyncpg is Linux-only in this repo"
)

try:
    import fcntl  # noqa: F401
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

requires_fcntl = pytest.mark.skipif(
    not _HAS_FCNTL, reason="fcntl is POSIX-only — service.py singleton lock runs on the Oracle VM"
)


# ---------------------------------------------------------------------------
# TrailingSLCalculator
# ---------------------------------------------------------------------------

class TestTrailingSLCalculator:
    def setup_method(self):
        self.calc = TrailingSLCalculator()

    @pytest.mark.parametrize("dte,expected_base", [
        (0, 0.05), (1, 0.08), (2, 0.12), (3, 0.12), (5, 0.15), (7, 0.15), (10, 0.20),
    ])
    def test_calculate_pct_by_dte(self, dte, expected_base):
        pct = self.calc.calculate_pct(dte, "ATM", vix=15.0)
        assert pct == round(expected_base, 3)

    def test_calculate_pct_otm_scales_down(self):
        atm = self.calc.calculate_pct(5, "ATM", vix=15.0)
        otm = self.calc.calculate_pct(5, "OTM", vix=15.0)
        assert otm == round(atm * 0.8, 3)

    def test_calculate_pct_itm_scales_up(self):
        atm = self.calc.calculate_pct(5, "ATM", vix=15.0)
        itm = self.calc.calculate_pct(5, "ITM", vix=15.0)
        assert itm == round(atm * 1.2, 3)

    def test_calculate_pct_high_vix(self):
        normal = self.calc.calculate_pct(5, "ATM", vix=15.0)
        high = self.calc.calculate_pct(5, "ATM", vix=25.0)
        assert high == round(normal * 1.3, 3)

    def test_calculate_pct_low_vix(self):
        normal = self.calc.calculate_pct(5, "ATM", vix=15.0)
        low = self.calc.calculate_pct(5, "ATM", vix=10.0)
        assert low == round(normal * 0.9, 3)

    def test_get_trailing_sl_price(self):
        price = self.calc.get_trailing_sl_price(100.0, dte=5, moneyness="ATM", vix=15.0)
        assert price == round(100.0 * (1 - 0.15), 2)

    def test_get_moneyness_atm(self):
        assert self.calc.get_moneyness(24400, 24400, "CE") == "ATM"

    def test_get_moneyness_call_itm(self):
        assert self.calc.get_moneyness(24700, 24400, "CE") == "ITM"

    def test_get_moneyness_call_otm(self):
        assert self.calc.get_moneyness(24100, 24400, "CE") == "OTM"

    def test_get_moneyness_put_itm(self):
        assert self.calc.get_moneyness(24100, 24400, "PE") == "ITM"

    def test_get_moneyness_put_otm(self):
        assert self.calc.get_moneyness(24700, 24400, "PE") == "OTM"

    def test_should_stop_monitoring_below_threshold(self):
        assert self.calc.should_stop_monitoring(current_premium=5.0, entry_premium=100.0) is True

    def test_should_stop_monitoring_above_threshold(self):
        assert self.calc.should_stop_monitoring(current_premium=15.0, entry_premium=100.0) is False


# ---------------------------------------------------------------------------
# MarketConditions
# ---------------------------------------------------------------------------

class TestMarketConditions:
    def setup_method(self):
        self.cond = MarketConditions()

    def test_check_trailing_sl_triggered(self):
        triggered, reason = self.cond.check_trailing_sl(current=80.0, trailing_sl=85.0)
        assert triggered is True
        assert "Trailing SL breached" in reason

    def test_check_trailing_sl_not_triggered(self):
        triggered, _ = self.cond.check_trailing_sl(current=90.0, trailing_sl=85.0)
        assert triggered is False

    def test_check_profit_milestone_triggered(self):
        triggered, reason = self.cond.check_profit_milestone(entry=100.0, current=160.0, threshold_pct=0.5)
        assert triggered is True
        assert "+60%" in reason

    def test_check_profit_milestone_not_triggered(self):
        triggered, _ = self.cond.check_profit_milestone(entry=100.0, current=120.0, threshold_pct=0.5)
        assert triggered is False

    def test_check_pcr_shift_bullish(self):
        triggered, reason = self.cond.check_pcr_shift(current_pcr=1.5, open_pcr=1.0, threshold=0.3)
        assert triggered is True
        assert "bullish" in reason

    def test_check_pcr_shift_bearish(self):
        triggered, reason = self.cond.check_pcr_shift(current_pcr=0.5, open_pcr=1.0, threshold=0.3)
        assert triggered is True
        assert "bearish" in reason

    def test_check_pcr_shift_not_triggered(self):
        triggered, _ = self.cond.check_pcr_shift(current_pcr=1.1, open_pcr=1.0, threshold=0.3)
        assert triggered is False

    def test_check_vix_spike_triggered(self):
        triggered, _ = self.cond.check_vix_spike(current_vix=16.0, open_vix=13.0, threshold=14.0)
        assert triggered is True

    def test_check_vix_spike_not_triggered_below_threshold(self):
        triggered, _ = self.cond.check_vix_spike(current_vix=13.5, open_vix=13.0, threshold=14.0)
        assert triggered is False

    def test_check_vix_spike_not_triggered_no_relative_jump(self):
        triggered, _ = self.cond.check_vix_spike(current_vix=14.5, open_vix=14.0, threshold=14.0)
        assert triggered is False

    def test_check_wall_break_call(self):
        triggered, reason = self.cond.check_wall_break(spot=24410, prev_spot=24390, call_wall=24400, put_wall=24000)
        assert triggered is True
        assert "call wall" in reason

    def test_check_wall_break_put(self):
        triggered, reason = self.cond.check_wall_break(spot=23990, prev_spot=24010, call_wall=24400, put_wall=24000)
        assert triggered is True
        assert "put wall" in reason

    def test_check_wall_break_none(self):
        triggered, _ = self.cond.check_wall_break(spot=24300, prev_spot=24290, call_wall=24400, put_wall=24000)
        assert triggered is False

    def test_cooldown_suppresses_recent_alert(self):
        last_sent = datetime.now(timezone.utc) - timedelta(seconds=60)
        assert self.cond.is_alert_on_cooldown(last_sent, cooldown_seconds=300) is True

    def test_cooldown_allows_after_expiry(self):
        last_sent = datetime.now(timezone.utc) - timedelta(seconds=400)
        assert self.cond.is_alert_on_cooldown(last_sent, cooldown_seconds=300) is False

    def test_cooldown_allows_when_never_sent(self):
        assert self.cond.is_alert_on_cooldown(None, cooldown_seconds=300) is False

    # -----------------------------------------------------------------
    # Wall-break streak primitives (Priority 1, 2026-07-10)
    # -----------------------------------------------------------------

    def test_update_wall_break_streak_increments_while_beyond_call_wall(self):
        assert self.cond.update_wall_break_streak(spot=24410, wall=24400, streak=1, direction="above") == 2

    def test_update_wall_break_streak_resets_when_back_inside_call_wall(self):
        assert self.cond.update_wall_break_streak(spot=24390, wall=24400, streak=2, direction="above") == 0

    def test_update_wall_break_streak_increments_while_beyond_put_wall(self):
        assert self.cond.update_wall_break_streak(spot=23990, wall=24000, streak=1, direction="below") == 2

    def test_update_wall_break_streak_resets_when_back_inside_put_wall(self):
        assert self.cond.update_wall_break_streak(spot=24010, wall=24000, streak=2, direction="below") == 0

    def test_update_wall_break_streak_starts_fresh_from_zero(self):
        assert self.cond.update_wall_break_streak(spot=24410, wall=24400, streak=0, direction="above") == 1

    def test_check_wall_hold_true_at_threshold(self):
        assert self.cond.check_wall_hold(streak=3, confirm_candles=3) is True

    def test_check_wall_hold_true_above_threshold(self):
        assert self.cond.check_wall_hold(streak=5, confirm_candles=3) is True

    def test_check_wall_hold_false_below_threshold(self):
        assert self.cond.check_wall_hold(streak=2, confirm_candles=3) is False

    def test_check_wall_rejection_true_on_touch_then_fail(self):
        assert self.cond.check_wall_rejection(prev_streak=2, new_streak=0) is True

    def test_check_wall_rejection_false_when_streak_never_started(self):
        assert self.cond.check_wall_rejection(prev_streak=0, new_streak=0) is False

    def test_check_wall_rejection_false_while_streak_still_building(self):
        assert self.cond.check_wall_rejection(prev_streak=1, new_streak=2) is False


# ---------------------------------------------------------------------------
# Symbol resolver — pure parsing (no cache/broker I/O)
# ---------------------------------------------------------------------------

class TestZerodhaTradingsymbolParsing:
    def test_monthly_contract(self):
        resolved = _parse_zerodha_tradingsymbol("NIFTY26JUL24400CE")
        assert resolved == {
            "symbol": "NIFTY", "expiry": "2026-07-01", "strike": 24400.0,
            "option_type": "CE", "exchange": "NSE",
        }

    def test_weekly_contract(self):
        resolved = _parse_zerodha_tradingsymbol("NIFTY26709900PE")
        assert resolved is not None
        assert resolved["symbol"] == "NIFTY"
        assert resolved["option_type"] == "PE"

    def test_unparseable_returns_none(self):
        assert _parse_zerodha_tradingsymbol("NOTANOPTION") is None


class TestIndmoneyRowNormalization:
    def test_normalizes_valid_row(self):
        row = {
            "underlying_symbol": "NIFTY", "expiry": "2026-07-09",
            "strike_price": "24400", "option_type": "CE", "exchange": "NSE_FO",
        }
        resolved = _normalize_indmoney_row(row)
        assert resolved == {
            "symbol": "NIFTY", "expiry": "2026-07-09", "strike": 24400.0,
            "option_type": "CE", "exchange": "NSE",
        }

    def test_rejects_non_option_row(self):
        row = {"underlying_symbol": "NIFTY", "option_type": "EQ"}
        assert _normalize_indmoney_row(row) is None


class TestPositionSymbolResolverCacheHit:
    @pytest.mark.anyio
    async def test_memory_cache_hit_skips_repo_and_broker(self):
        repo = AsyncMock()
        resolver = PositionSymbolResolver(repo=repo)
        cached = {"symbol": "NIFTY", "expiry": "2026-07-09", "strike": 24400.0, "option_type": "CE", "exchange": "NSE"}
        resolver.memory_cache["zerodha:NIFTY26JUL24400CE"] = cached

        result = await resolver.resolve("zerodha", "NIFTY26JUL24400CE")

        assert result == cached
        repo.get_cached_instrument.assert_not_called()

    @pytest.mark.anyio
    async def test_zerodha_resolves_without_broker_or_cache(self):
        repo = AsyncMock()
        repo.get_cached_instrument.return_value = None
        resolver = PositionSymbolResolver(repo=repo)

        result = await resolver.resolve("zerodha", "NIFTY26JUL24400CE")

        assert result["symbol"] == "NIFTY"
        assert result["option_type"] == "CE"
        repo.cache_instrument.assert_awaited_once()


# ---------------------------------------------------------------------------
# WhatsAppAlerter — mocked HTTP, no real messages sent
# ---------------------------------------------------------------------------

class TestWhatsAppAlerter:
    @pytest.mark.anyio
    async def test_send_success(self):
        alerter = WhatsAppAlerter()
        mock_response = AsyncMock()
        mock_response.status_code = 200
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            result = await alerter.send("911234567890", "key123", "test")
        assert result is True

    @pytest.mark.anyio
    async def test_send_failure_returns_false_after_retries(self):
        alerter = WhatsAppAlerter()
        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_response.text = "error"
        with patch("httpx.AsyncClient") as mock_client_cls, \
             patch("asyncio.sleep", new=AsyncMock()):
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            result = await alerter.send("911234567890", "key123", "test")
        assert result is False

    @pytest.mark.anyio
    async def test_send_never_raises_on_exception(self):
        alerter = WhatsAppAlerter()
        with patch("httpx.AsyncClient", side_effect=Exception("network down")), \
             patch("asyncio.sleep", new=AsyncMock()):
            result = await alerter.send("911234567890", "key123", "test")
        assert result is False

    @pytest.mark.anyio
    async def test_telegram_not_attempted_when_not_configured(self):
        """No telegram_bot_token/chat_id on the user -> only CallMeBot fires."""
        alerter = WhatsAppAlerter()
        with patch.object(alerter, "_send_callmebot", new=AsyncMock(return_value=True)) as cb, \
             patch.object(alerter, "_send_telegram", new=AsyncMock(return_value=True)) as tg:
            result = await alerter.send("911234567890", "key123", "test", user={})
        assert result is True
        cb.assert_awaited_once()
        tg.assert_not_awaited()

    @pytest.mark.anyio
    async def test_telegram_fires_when_configured(self):
        alerter = WhatsAppAlerter()
        user = {"telegram_bot_token": "bot-token", "telegram_chat_id": "12345"}
        with patch.object(alerter, "_send_callmebot", new=AsyncMock(return_value=False)), \
             patch.object(alerter, "_send_telegram", new=AsyncMock(return_value=True)) as tg:
            result = await alerter.send("911234567890", "key123", "test", user=user)
        assert result is True
        tg.assert_awaited_once_with("bot-token", "12345", "test")

    @pytest.mark.anyio
    async def test_overall_success_if_either_channel_succeeds(self):
        alerter = WhatsAppAlerter()
        user = {"telegram_bot_token": "bot-token", "telegram_chat_id": "12345"}
        with patch.object(alerter, "_send_callmebot", new=AsyncMock(return_value=True)), \
             patch.object(alerter, "_send_telegram", new=AsyncMock(return_value=False)):
            result = await alerter.send("911234567890", "key123", "test", user=user)
        assert result is True

    @pytest.mark.anyio
    async def test_overall_failure_if_both_channels_fail(self):
        alerter = WhatsAppAlerter()
        user = {"telegram_bot_token": "bot-token", "telegram_chat_id": "12345"}
        with patch.object(alerter, "_send_callmebot", new=AsyncMock(return_value=False)), \
             patch.object(alerter, "_send_telegram", new=AsyncMock(return_value=False)):
            result = await alerter.send("911234567890", "key123", "test", user=user)
        assert result is False

    @pytest.mark.anyio
    async def test_telegram_send_success(self):
        alerter = WhatsAppAlerter()
        mock_response = AsyncMock()
        mock_response.status_code = 200
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            result = await alerter._send_telegram("bot-token", "12345", "test")
        assert result is True
        mock_client.post.assert_awaited_once()
        call_kwargs = mock_client.post.call_args.kwargs
        assert call_kwargs["json"] == {"chat_id": "12345", "text": "test"}

    @pytest.mark.anyio
    async def test_telegram_send_failure_returns_false(self):
        alerter = WhatsAppAlerter()
        mock_response = AsyncMock()
        mock_response.status_code = 400
        mock_response.text = "bad request"
        with patch("httpx.AsyncClient") as mock_client_cls, \
             patch("asyncio.sleep", new=AsyncMock()):
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            result = await alerter._send_telegram("bot-token", "12345", "test")
        assert result is False

    def test_position_alert_message_format(self):
        alerter = WhatsAppAlerter()
        user = {"whatsapp_phone": "91123", "callmebot_key": "key"}
        position = {
            "symbol": "NIFTY", "strike": 24400, "option_type": "CE",
            "expiry": "2026-07-09", "current_premium": 120.0, "pnl": 500.0, "spot": 24380.0,
        }
        import asyncio
        with patch.object(alerter, "send", new=AsyncMock(return_value=True)) as mock_send:
            asyncio.run(alerter.send_position_alert(user, position, "Test reason"))
        message = mock_send.call_args.args[2]
        assert "POSITION ALERT" in message
        assert "NIFTY 24400 CE" in message
        assert "Test reason" in message

    def test_morning_brief_message_format(self):
        alerter = WhatsAppAlerter()
        user = {"whatsapp_phone": "91123", "callmebot_key": "key"}
        data = {
            "date": "2026-07-06", "expiry": "2026-07-09", "nifty": 24380, "sensex": 80000,
            "vix": 13.5, "global_sentiment": "neutral", "positions": [], "support": 24200, "resistance": 24500,
        }
        import asyncio
        with patch.object(alerter, "send", new=AsyncMock(return_value=True)) as mock_send:
            asyncio.run(alerter.send_morning_brief(user, data))
        message = mock_send.call_args.args[2]
        assert "MORNING BRIEF" in message
        assert "None" in message  # no open positions

    def test_eod_summary_message_format(self):
        alerter = WhatsAppAlerter()
        user = {"whatsapp_phone": "91123", "callmebot_key": "key"}
        data = {
            "date": "2026-07-06", "nifty_close": 24380, "nifty_change": 0.2,
            "sensex_close": 80000, "sensex_change": 0.1, "realized_pnl": 0,
            "open_count": 0, "tomorrow_note": "",
        }
        import asyncio
        with patch.object(alerter, "send", new=AsyncMock(return_value=True)) as mock_send:
            asyncio.run(alerter.send_eod_summary(user, data))
        message = mock_send.call_args.args[2]
        assert "EOD SUMMARY" in message


# ---------------------------------------------------------------------------
# MarketMonitor — adaptive polling math (no DB/broker required)
# ---------------------------------------------------------------------------

class TestAdaptivePolling:
    def setup_method(self):
        with patch("src.monitor.scheduler.MonitorRepository"), \
             patch("src.monitor.scheduler.MonitorBootstrap"), \
             patch("src.monitor.scheduler.PositionTracker"):
            self.monitor = MarketMonitor()

    def test_zero_dte_high_premium(self):
        assert self.monitor.get_poll_interval(min_dte=0, max_premium=250) == 60

    def test_zero_dte_low_premium(self):
        assert self.monitor.get_poll_interval(min_dte=0, max_premium=10) == 60

    def test_one_dte(self):
        assert self.monitor.get_poll_interval(min_dte=1, max_premium=10) == 120

    def test_far_dte_low_premium(self):
        assert self.monitor.get_poll_interval(min_dte=10, max_premium=10) == 900

    def test_far_dte_high_premium_overrides_to_faster(self):
        assert self.monitor.get_poll_interval(min_dte=10, max_premium=250) == 60

    def test_is_market_open_boundaries(self):
        assert self.monitor.MARKET_OPEN.hour == 9 and self.monitor.MARKET_OPEN.minute == 15
        assert self.monitor.MARKET_CLOSE.hour == 15 and self.monitor.MARKET_CLOSE.minute == 30


# ---------------------------------------------------------------------------
# MarketMonitor data-fetching helpers — real sources mocked at the module
# boundary, so these prove the wiring (function names, dict keys) is right
# without hitting the network.
# ---------------------------------------------------------------------------

class TestSchedulerDataFetchers:
    def setup_method(self):
        with patch("src.monitor.scheduler.MonitorRepository"), \
             patch("src.monitor.scheduler.MonitorBootstrap"), \
             patch("src.monitor.scheduler.PositionTracker"):
            self.monitor = MarketMonitor()

    @pytest.mark.anyio
    async def test_get_vix_reads_level_field(self):
        with patch("src.intelligence.vix.get_india_vix", return_value={"level": 13.5}):
            result = await self.monitor._get_vix()
        assert result == 13.5

    @pytest.mark.anyio
    async def test_get_vix_returns_zero_on_error(self):
        with patch("src.intelligence.vix.get_india_vix", side_effect=Exception("down")):
            result = await self.monitor._get_vix()
        assert result == 0.0

    @pytest.mark.anyio
    async def test_get_index_quote_nifty_uses_nse_chain_underlying_value(self):
        chain = {"records": {"underlyingValue": 24380.5}}
        quote = {"last_price": 24350.0, "previous_close": 24300.0}
        with patch("src.options.service.OptionsService.get_option_chain", return_value=chain), \
             patch("src.market.service.MarketService.get_quote", return_value=quote):
            result = await self.monitor._get_index_quote("NIFTY")
        # last_price comes from the option chain, not the yfinance quote
        assert result == {"last_price": 24380.5, "previous_close": 24300.0}

    @pytest.mark.anyio
    async def test_get_index_quote_sensex_uses_bse_chain_underlying_value(self):
        """Regression test: previously used MarketService.get_quote("SENSEX")
        (yfinance ^BSESN), which returned a stale/incorrect spot (e.g. 80000
        vs the confirmed-correct 78241 from the BSE option chain)."""
        chain = {"records": {"underlyingValue": 78241.0}}
        quote = {"last_price": 80000.0, "previous_close": 79500.0}
        with patch("src.options.bse_service.BSEOptionsService.get_option_chain", return_value=chain), \
             patch("src.market.service.MarketService.get_quote", return_value=quote):
            result = await self.monitor._get_index_quote("SENSEX")
        assert result["last_price"] == 78241.0
        assert result["previous_close"] == 79500.0

    @pytest.mark.anyio
    async def test_get_index_quote_falls_back_to_yfinance_quote_if_chain_fails(self):
        quote = {"last_price": 24350.0, "previous_close": 24300.0}
        with patch("src.options.service.OptionsService.get_option_chain", side_effect=RuntimeError("blocked")), \
             patch("src.market.service.MarketService.get_quote", return_value=quote):
            result = await self.monitor._get_index_quote("NIFTY")
        assert result == {"last_price": 24350.0, "previous_close": 24300.0}

    @pytest.mark.anyio
    async def test_get_index_quote_returns_zeros_on_total_failure(self):
        with patch("src.options.service.OptionsService.get_option_chain", side_effect=Exception("down")), \
             patch("src.market.service.MarketService.get_quote", side_effect=Exception("down")):
            result = await self.monitor._get_index_quote("NIFTY")
        assert result == {"last_price": 0.0, "previous_close": 0.0}

    @pytest.mark.anyio
    async def test_get_key_levels_reads_nearest_support_resistance(self):
        chain = {"records": {"data": []}}
        levels = {
            "nearest_support": {"strike": 24200, "oi": 100, "basis": "high put OI"},
            "nearest_resistance": {"strike": 24500, "oi": 200, "basis": "high call OI"},
        }
        with patch("src.options.service.OptionsService.get_option_chain", return_value=chain), \
             patch("src.options.analytics.identify_support_resistance_from_oi", return_value=levels):
            result = await self.monitor._get_key_levels()
        assert result == {"support": 24200, "resistance": 24500}

    @pytest.mark.anyio
    async def test_get_key_levels_handles_missing_levels(self):
        chain = {"records": {"data": []}}
        levels = {"nearest_support": None, "nearest_resistance": None}
        with patch("src.options.service.OptionsService.get_option_chain", return_value=chain), \
             patch("src.options.analytics.identify_support_resistance_from_oi", return_value=levels):
            result = await self.monitor._get_key_levels()
        assert result == {"support": "", "resistance": ""}

    @pytest.mark.anyio
    async def test_get_key_levels_returns_empty_on_error(self):
        with patch("src.options.service.OptionsService.get_option_chain", side_effect=RuntimeError("blocked")):
            result = await self.monitor._get_key_levels()
        assert result == {"support": "", "resistance": ""}

    @pytest.mark.anyio
    async def test_get_calendar_returns_dict(self):
        cal = {"next_nse_expiry": "2026-07-09", "nse_holidays": []}
        with patch("src.market.calendar.get_market_calendar", return_value=cal):
            result = await self.monitor._get_calendar()
        assert result == cal

    @pytest.mark.anyio
    async def test_get_calendar_returns_empty_dict_on_error(self):
        with patch("src.market.calendar.get_market_calendar", side_effect=Exception("down")):
            result = await self.monitor._get_calendar()
        assert result == {}

    @pytest.mark.anyio
    async def test_get_global_sentiment_reads_overall_sentiment(self):
        with patch("src.intelligence.global_pulse.get_global_pulse", return_value={"overall_sentiment": "RISK_ON"}):
            result = await self.monitor._get_global_sentiment()
        assert result == "RISK_ON"

    @pytest.mark.anyio
    async def test_get_global_sentiment_returns_empty_on_error(self):
        with patch("src.intelligence.global_pulse.get_global_pulse", side_effect=Exception("down")):
            result = await self.monitor._get_global_sentiment()
        assert result == ""

    @pytest.mark.anyio
    async def test_get_realized_pnl_today_unwraps_body_data(self):
        raw = {"status_code": 200, "body": {"data": {"realized_pnl": "1234.5"}}}
        mock_broker = AsyncMock()
        mock_broker.get_raw_funds.return_value = raw
        with patch("src.brokers.indmoney.INDmoneyBroker", return_value=mock_broker):
            result = await self.monitor._get_realized_pnl_today()
        assert result == 1234.5

    @pytest.mark.anyio
    async def test_get_realized_pnl_today_returns_zero_when_not_configured(self):
        mock_broker = AsyncMock()
        mock_broker.get_raw_funds.return_value = {"error": "not_configured"}
        with patch("src.brokers.indmoney.INDmoneyBroker", return_value=mock_broker):
            result = await self.monitor._get_realized_pnl_today()
        assert result == 0.0

    def test_tomorrow_note_empty_calendar(self):
        assert self.monitor._tomorrow_note({}) == ""

    def test_tomorrow_note_with_expiry_no_holiday(self):
        cal = {"next_nse_expiry": "2026-07-09", "nse_holidays": []}
        note = self.monitor._tomorrow_note(cal)
        assert "2026-07-09" in note
        assert "holiday" not in note.lower()

    def test_tomorrow_note_flags_holiday(self):
        tomorrow = (self.monitor._today_ist() + timedelta(days=1)).isoformat()
        cal = {"next_nse_expiry": "2026-07-09", "nse_holidays": [tomorrow]}
        note = self.monitor._tomorrow_note(cal)
        assert "holiday" in note.lower()
        assert "2026-07-09" in note

    def test_today_ist_uses_ist_not_utc_date(self):
        """Regression: the Oracle VM runs in UTC. IST is UTC+5:30, so at
        23:45 UTC on 2026-07-06 it's already 05:15 IST on 2026-07-07 —
        date.today() (OS/UTC date) would wrongly report 2026-07-06."""
        utc_late_evening = pytz.utc.localize(datetime(2026, 7, 6, 23, 45))
        with patch("src.monitor.scheduler.datetime") as mock_dt:
            mock_dt.now.side_effect = lambda tz=None: (
                utc_late_evening.astimezone(tz) if tz else utc_late_evening
            )
            result = self.monitor._today_ist()
        assert result == date(2026, 7, 7)

    def test_today_ist_before_ist_midnight_matches_utc_date(self):
        """Sanity check the other side of the boundary: at 12:00 UTC (17:30
        IST, same calendar day), both dates should agree."""
        utc_noon = pytz.utc.localize(datetime(2026, 7, 6, 12, 0))
        with patch("src.monitor.scheduler.datetime") as mock_dt:
            mock_dt.now.side_effect = lambda tz=None: (
                utc_noon.astimezone(tz) if tz else utc_noon
            )
            result = self.monitor._today_ist()
        assert result == date(2026, 7, 6)


# ---------------------------------------------------------------------------
# PositionTracker DTE calculation — must use the IST date, not the OS date
# (the Oracle VM runs in UTC), or a same-day-expiry position gets bucketed
# one DTE too high right when the tightest 0-DTE trailing-SL should apply.
# ---------------------------------------------------------------------------

class TestPositionTrackerDTETimezone:
    def _make_tracker(self):
        from src.monitor.position_tracker import PositionTracker
        repo = AsyncMock()
        repo.get_active_positions.return_value = [{
            "id": "pos-1",
            "broker": "zerodha",
            "symbol": "NIFTY",
            "expiry": "2026-07-07",
            "strike": 24400,
            "option_type": "CE",
            "entry_premium": 100.0,
            "qty": 50,
            "spot": 0.0,
        }]
        repo.get_user_settings.return_value = {
            "profit_alert_pct": 0.5,
            "cooldown_trailing": 300,
            "cooldown_profit": 86400,
        }
        repo.get_peak.return_value = None
        tracker = PositionTracker(repo=repo)
        tracker._get_current_premium = AsyncMock(return_value=110.0)
        return tracker

    @pytest.mark.anyio
    async def test_dte_zero_on_expiry_day_in_ist_even_if_utc_is_prior_day(self):
        """At 23:45 UTC on 2026-07-06, it's already 2026-07-07 05:15 IST —
        the exact expiry date in the mocked position. DTE must be 0 (using
        the IST date), not 1 (which date.today()/UTC would have produced)."""
        tracker = self._make_tracker()
        utc_late_evening = pytz.utc.localize(datetime(2026, 7, 6, 23, 45))

        captured_dte = {}

        def _fake_trailing_sl_price(peak_premium, dte, moneyness, vix):
            captured_dte["dte"] = dte
            return peak_premium * 0.9

        tracker.trailing_sl.get_trailing_sl_price = _fake_trailing_sl_price

        with patch("src.monitor.position_tracker.datetime") as mock_dt:
            mock_dt.now.side_effect = lambda tz=None: (
                utc_late_evening.astimezone(tz) if tz else utc_late_evening
            )
            mock_dt.strptime = datetime.strptime
            await tracker.check_positions({"id": "u1"}, vix=13.0)

        assert captured_dte["dte"] == 0

class TestBriefDedup:
    def setup_method(self):
        with patch("src.monitor.scheduler.MonitorRepository"), \
             patch("src.monitor.scheduler.MonitorBootstrap"), \
             patch("src.monitor.scheduler.PositionTracker"):
            self.monitor = MarketMonitor()
        self.monitor.repo = AsyncMock()
        self.monitor.bootstrap = AsyncMock()
        self.monitor.tracker = AsyncMock()

    @pytest.mark.anyio
    async def test_run_skips_morning_brief_if_already_sent_today(self):
        today_str = datetime.now(self.monitor.IST).date().isoformat()
        self.monitor.repo.get_active_users.return_value = [{"id": "u1", "name": "Vishnu"}]
        self.monitor.repo.get_session_state.return_value = {"last_morning_brief": today_str, "last_eod_summary": today_str}
        self.monitor.repo.get_active_positions.return_value = []
        self.monitor.send_morning_brief = AsyncMock()
        self.monitor.send_eod_summary = AsyncMock()

        async def _raise_stop(*a, **k):
            raise StopAsyncIteration

        with patch("asyncio.sleep", new=AsyncMock(side_effect=_raise_stop)):
            with pytest.raises(StopAsyncIteration):
                await self.monitor.run()

        self.monitor.send_morning_brief.assert_not_awaited()
        self.monitor.send_eod_summary.assert_not_awaited()

    @pytest.mark.anyio
    async def test_run_sends_morning_brief_once_and_persists_date(self):
        self.monitor.repo.get_active_users.return_value = [{"id": "u1", "name": "Vishnu"}]
        self.monitor.repo.get_session_state.return_value = {}
        self.monitor.repo.get_active_positions.return_value = []
        self.monitor.send_morning_brief = AsyncMock()
        self.monitor.send_eod_summary = AsyncMock()
        self.monitor.check_market_conditions = AsyncMock()
        self.monitor._get_vix = AsyncMock(return_value=13.0)
        # Force "now" past MORNING_BRIEF_TIME but before EOD_SUMMARY_TIME
        fixed_now = self.monitor.IST.localize(datetime.combine(date.today(), time(10, 0)))

        async def _raise_stop(*a, **k):
            raise StopAsyncIteration

        with patch("src.monitor.scheduler.datetime") as mock_dt, \
             patch("asyncio.sleep", new=AsyncMock(side_effect=_raise_stop)):
            mock_dt.now.return_value = fixed_now
            with pytest.raises(StopAsyncIteration):
                await self.monitor.run()

        self.monitor.send_morning_brief.assert_awaited_once()
        self.monitor.send_eod_summary.assert_not_awaited()
        saved = self.monitor.repo.save_session_state.call_args_list
        assert any(c.args[1].get("last_morning_brief") == fixed_now.date().isoformat() for c in saved)


# ---------------------------------------------------------------------------
# Bootstrap — requires sqlalchemy (Linux-only in this repo); real DB
# integration is exercised on the Oracle VM, not Windows dev.
# ---------------------------------------------------------------------------

class _FakeSessionCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


@requires_sqlalchemy
class TestMonitorBootstrap:
    @pytest.mark.anyio
    async def test_creates_default_user_when_empty(self, monkeypatch):
        monkeypatch.setenv("DEFAULT_USER_NAME", "Vishnu")
        monkeypatch.setenv("DEFAULT_WHATSAPP_PHONE", "91XXXXXXXXXX")
        monkeypatch.setenv("DEFAULT_CALLMEBOT_API_KEY", "testkey")

        from src.monitor.bootstrap import MonitorBootstrap

        # A real AsyncSession mixes sync and async methods: add()/add_all()
        # are plain sync calls, while execute()/flush()/commit() are
        # awaited. Mocking the whole session as AsyncMock makes add()
        # return an unawaited coroutine (RuntimeWarning, and silently wrong
        # if bootstrap.py ever grew an accidental `await session.add(...)`).
        # MagicMock the session and only mark the actually-async methods.
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_session.flush = AsyncMock()
        no_user_result = MagicMock()
        no_user_result.scalars.return_value.first.return_value = None
        no_settings_result = MagicMock()
        no_settings_result.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_user_result, no_settings_result]

        with patch("src.monitor.bootstrap.get_session", return_value=_FakeSessionCtx(mock_session)):
            user = await MonitorBootstrap().ensure_default_user()

        assert user["name"] == "Vishnu"
        assert user["is_default"] is True
        mock_session.add.assert_called()

    @pytest.mark.anyio
    async def test_skips_creation_when_user_exists(self):
        from src.monitor.bootstrap import MonitorBootstrap

        existing = type("Row", (), {})()
        existing.name = "Vishnu"
        existing.__table__ = type("T", (), {"columns": []})()

        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.first.return_value = existing
        mock_session.execute.return_value = result

        with patch("src.monitor.bootstrap.get_session", return_value=_FakeSessionCtx(mock_session)):
            user = await MonitorBootstrap().ensure_default_user()

        assert user == {}
        mock_session.add.assert_not_called()

    @pytest.mark.anyio
    async def test_creates_user_with_telegram_only_no_callmebot(self, monkeypatch):
        """CallMeBot's WhatsApp opt-in can be slow/unavailable — a user who's
        only configured Telegram should still bootstrap successfully."""
        monkeypatch.setenv("DEFAULT_USER_NAME", "Vishnu")
        monkeypatch.delenv("DEFAULT_WHATSAPP_PHONE", raising=False)
        monkeypatch.delenv("DEFAULT_CALLMEBOT_API_KEY", raising=False)
        monkeypatch.setenv("DEFAULT_TELEGRAM_BOT_TOKEN", "bot-token")
        monkeypatch.setenv("DEFAULT_TELEGRAM_CHAT_ID", "12345")

        from src.monitor.bootstrap import MonitorBootstrap

        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_session.flush = AsyncMock()
        no_user_result = MagicMock()
        no_user_result.scalars.return_value.first.return_value = None
        no_settings_result = MagicMock()
        no_settings_result.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_user_result, no_settings_result]

        with patch("src.monitor.bootstrap.get_session", return_value=_FakeSessionCtx(mock_session)):
            user = await MonitorBootstrap().ensure_default_user()

        assert user["name"] == "Vishnu"
        assert user["telegram_bot_token"] == "bot-token"
        assert user["telegram_chat_id"] == "12345"

    @pytest.mark.anyio
    async def test_raises_when_no_channel_configured(self, monkeypatch):
        monkeypatch.setenv("DEFAULT_USER_NAME", "Vishnu")
        monkeypatch.delenv("DEFAULT_WHATSAPP_PHONE", raising=False)
        monkeypatch.delenv("DEFAULT_CALLMEBOT_API_KEY", raising=False)
        monkeypatch.delenv("DEFAULT_TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("DEFAULT_TELEGRAM_CHAT_ID", raising=False)

        from src.monitor.bootstrap import MonitorBootstrap

        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        no_user_result = MagicMock()
        no_user_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = no_user_result

        with patch("src.monitor.bootstrap.get_session", return_value=_FakeSessionCtx(mock_session)):
            with pytest.raises(RuntimeError, match="at least one alert channel"):
                await MonitorBootstrap().ensure_default_user()


# ---------------------------------------------------------------------------
# get_monitor_status staleness detection — pure function, no DB required.
# ---------------------------------------------------------------------------

class TestStaleness:
    def test_never_started(self):
        from src.tools.monitor import _staleness
        healthy, status = _staleness(None)
        assert healthy is False
        assert status == "NEVER_STARTED"

    def test_recent_heartbeat_is_healthy(self):
        from src.tools.monitor import _staleness
        recent = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        healthy, status = _staleness(recent)
        assert healthy is True
        assert status == "ACTIVE"

    def test_old_heartbeat_is_stale(self):
        from src.tools.monitor import _staleness
        from src.monitor.scheduler import MarketMonitor
        old = (datetime.now(timezone.utc) - timedelta(seconds=MarketMonitor.STALE_AFTER_SECONDS + 60)).isoformat()
        healthy, status = _staleness(old)
        assert healthy is False
        assert status == "STALE"

    def test_boundary_just_under_threshold_is_healthy(self):
        from src.tools.monitor import _staleness
        from src.monitor.scheduler import MarketMonitor
        just_under = (datetime.now(timezone.utc) - timedelta(seconds=MarketMonitor.STALE_AFTER_SECONDS - 60)).isoformat()
        healthy, status = _staleness(just_under)
        assert healthy is True
        assert status == "ACTIVE"


# ---------------------------------------------------------------------------
# MonitorRepository.save_heartbeat — field validation runs before any DB I/O,
# so it doesn't need sqlalchemy to be installed.
# ---------------------------------------------------------------------------

class TestSaveHeartbeatValidation:
    @pytest.mark.anyio
    async def test_rejects_unknown_field(self):
        from src.monitor.repository import MonitorRepository
        with pytest.raises(ValueError, match="Unknown heartbeat field"):
            await MonitorRepository().save_heartbeat("user-1", "not_a_real_field")


# ---------------------------------------------------------------------------
# repository._today_ist — module-level free function, no sqlalchemy needed.
# session_date is an IST trading-session concept; must not fall back to the
# UTC date on the Oracle VM.
# ---------------------------------------------------------------------------

class TestRepositoryTodayIst:
    def test_uses_ist_not_utc_date(self):
        from src.monitor.repository import _today_ist
        utc_late_evening = pytz.utc.localize(datetime(2026, 7, 6, 23, 45))
        with patch("src.monitor.repository.datetime") as mock_dt:
            mock_dt.now.side_effect = lambda tz=None: (
                utc_late_evening.astimezone(tz) if tz else utc_late_evening
            )
            result = _today_ist()
        assert result == "2026-07-07"


# ---------------------------------------------------------------------------
# service.py singleton lock — POSIX-only (fcntl), exercised on the Oracle VM.
# ---------------------------------------------------------------------------

@requires_fcntl
class TestSingletonLock:
    def test_second_process_cannot_acquire_lock(self, tmp_path, monkeypatch):
        lock_path = str(tmp_path / "monitor.lock")
        monkeypatch.setenv("MONITOR_LOCK_FILE", lock_path)

        import importlib
        import src.monitor.service as service_module
        importlib.reload(service_module)

        first = service_module._acquire_singleton_lock()
        try:
            with pytest.raises(SystemExit):
                service_module._acquire_singleton_lock()
        finally:
            first.close()

    def test_lock_released_after_close_allows_reacquire(self, tmp_path, monkeypatch):
        lock_path = str(tmp_path / "monitor.lock")
        monkeypatch.setenv("MONITOR_LOCK_FILE", lock_path)

        import importlib
        import src.monitor.service as service_module
        importlib.reload(service_module)

        first = service_module._acquire_singleton_lock()
        first.close()

        second = service_module._acquire_singleton_lock()
        second.close()


# ---------------------------------------------------------------------------
# INDmoney as a monitor position source (Zerodha unauthenticated / broken).
#
# INDmoneyBroker.get_raw_positions() wraps the parsed JSON one level deeper
# under "body" (see INDmoneyBroker._raw_get), but _raw_option_items used to
# read raw.get("data", raw) directly — silently dropping every INDmoney
# position. These tests pin the fixed unwrap behaviour and confirm the
# monitor tracks an INDmoney position end-to-end when Zerodha has none.
# ---------------------------------------------------------------------------

class TestRawOptionItemsIndmoneyUnwrap:
    def test_indmoney_raw_positions_are_unwrapped_from_body(self):
        from src.monitor.position_tracker import _raw_option_items

        raw = {
            "status_code": 200,
            "body": {
                "data": {
                    "net_positions": [{"security_id": "OPT1", "net_quantity": 50}],
                    "day_positions": [{"security_id": "OPT2", "net_quantity": 25}],
                }
            },
        }
        items = _raw_option_items("indmoney", raw)
        assert {i["security_id"] for i in items} == {"OPT1", "OPT2"}

    def test_indmoney_error_response_yields_no_items(self):
        from src.monitor.position_tracker import _raw_option_items

        assert _raw_option_items("indmoney", {"error": "not_configured"}) == []
        assert _raw_option_items("indmoney", {"status_code": 401, "body": "unauthorized"}) == []

    def test_zerodha_raw_positions_unaffected(self):
        from src.monitor.position_tracker import _raw_option_items

        raw = {"net": [{"tradingsymbol": "NIFTY26JUL24400CE"}], "day": []}
        items = _raw_option_items("zerodha", raw)
        assert items == [{"tradingsymbol": "NIFTY26JUL24400CE"}]


class TestSyncFromBrokerIndmoneyFallback:
    """Zerodha unauthenticated (empty net/day) + INDmoney has one open F&O
    position -> sync_from_broker must still pick up the INDmoney position,
    resolve it, and persist it with broker='indmoney' so trailing SL and
    alerts cover it."""

    @pytest.mark.anyio
    async def test_indmoney_position_synced_when_zerodha_has_none(self):
        from src.monitor.position_tracker import PositionTracker

        user = {"id": "u1", "broker_type": "zerodha+indmoney"}

        zerodha_adapter = MagicMock()
        zerodha_adapter.get_raw_positions = AsyncMock(return_value={"net": [], "day": []})

        indmoney_raw_position = {
            "security_id": "OPT123",
            "net_quantity": 75,
            "average_price": 42.5,
        }
        indmoney_adapter = MagicMock()
        indmoney_adapter.get_raw_positions = AsyncMock(return_value={
            "status_code": 200,
            "body": {
                "data": {
                    "net_positions": [indmoney_raw_position],
                    "day_positions": [],
                }
            },
        })

        def _fake_get_broker_adapter(name):
            return {"zerodha": zerodha_adapter, "indmoney": indmoney_adapter}[name]

        resolved = {
            "symbol": "BANKNIFTY",
            "expiry": "2026-07-30",
            "strike": 52000.0,
            "option_type": "CE",
            "exchange": "NSE",
        }

        repo = AsyncMock()
        repo.get_active_positions.return_value = []

        tracker = PositionTracker(repo=repo)
        tracker.resolver.resolve = AsyncMock(return_value=resolved)

        with patch("src.monitor.position_tracker.get_broker_adapter", side_effect=_fake_get_broker_adapter):
            await tracker.sync_from_broker(user)

        tracker.resolver.resolve.assert_awaited_once_with("indmoney", "OPT123")
        repo.upsert_position.assert_awaited_once()
        (user_id_arg, position_arg), _ = repo.upsert_position.call_args
        assert user_id_arg == "u1"
        assert position_arg["broker"] == "indmoney"
        assert position_arg["symbol"] == "BANKNIFTY"
        assert position_arg["qty"] == 75
        assert position_arg["entry_premium"] == 42.5

    @pytest.mark.anyio
    async def test_indmoney_position_then_tracked_for_trailing_sl(self):
        """Once synced, the position (broker='indmoney') must flow through
        check_positions like any other tracked position — trailing SL logic
        is broker-agnostic and dispatches via get_broker_adapter(pos['broker'])."""
        from src.monitor.position_tracker import PositionTracker

        repo = AsyncMock()
        repo.get_active_positions.return_value = [{
            "id": "pos-ind-1",
            "broker": "indmoney",
            "symbol": "BANKNIFTY",
            "expiry": "2026-07-30",
            "strike": 52000.0,
            "option_type": "CE",
            "entry_premium": 42.5,
            "qty": 75,
            "spot": 0.0,
        }]
        repo.get_user_settings.return_value = {
            "profit_alert_pct": 0.5,
            "cooldown_trailing": 300,
            "cooldown_profit": 86400,
        }
        repo.get_peak.return_value = None

        tracker = PositionTracker(repo=repo)

        indmoney_adapter = MagicMock()
        quote = MagicMock(ltp=55.0)
        indmoney_adapter.get_quote = AsyncMock(return_value=[quote])

        with patch("src.monitor.position_tracker.get_broker_adapter", return_value=indmoney_adapter) as mock_get_adapter:
            await tracker.check_positions({"id": "u1"}, vix=13.0)

        mock_get_adapter.assert_called_with("indmoney")
        repo.upsert_peak.assert_awaited_once()
        peak_call = repo.upsert_peak.call_args
        assert peak_call[0][1]["peak_premium"] == 55.0


class TestGetMonitorStatusBrokerVisibility:
    @pytest.mark.anyio
    async def test_positions_by_broker_summary_present(self):
        from mcp.server.fastmcp import FastMCP as _FastMCP
        from src.tools import monitor as monitor_tools

        mcp = _FastMCP("test")
        monitor_tools.register(mcp)
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}

        mock_repo = AsyncMock()
        mock_repo.get_active_users.return_value = [{"id": "u1", "name": "trader"}]
        mock_repo.get_active_positions.return_value = [
            {"id": "p1", "broker": "zerodha", "symbol": "NIFTY"},
            {"id": "p2", "broker": "indmoney", "symbol": "BANKNIFTY"},
            {"id": "p3", "broker": "indmoney", "symbol": "SENSEX"},
        ]
        mock_repo.get_peak.return_value = None
        mock_repo.get_session_state.return_value = {"last_heartbeat": None}
        mock_repo.get_recent_alerts.return_value = []

        with patch("src.tools.monitor.MonitorRepository", return_value=mock_repo):
            result = await tools["get_monitor_status"].fn()

        assert result["data"]["positions_by_broker"] == {"zerodha": 1, "indmoney": 2}
