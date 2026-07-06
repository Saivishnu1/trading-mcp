"""Tests for src/monitor/ — Phase 9A live position monitor.

Pure-logic modules (trailing_sl, conditions, symbol_resolver parsing, alerts,
scheduler polling math) are tested directly. Repository/bootstrap tests are
skipped when SQLAlchemy is not installed (Windows dev — DB deps are Linux-only,
see src/db/base.py). No real broker, HTTP, or WhatsApp calls are made.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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

        # session.execute() is the only awaited call — its return value
        # (the Result object) is used synchronously (.scalars(), .first(),
        # .scalar_one_or_none()), so those must be MagicMock, not AsyncMock,
        # or calling them returns an unawaited coroutine instead of a value.
        mock_session = AsyncMock()
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

        mock_session = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.first.return_value = existing
        mock_session.execute.return_value = result

        with patch("src.monitor.bootstrap.get_session", return_value=_FakeSessionCtx(mock_session)):
            user = await MonitorBootstrap().ensure_default_user()

        assert user == {}
        mock_session.add.assert_not_called()


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
