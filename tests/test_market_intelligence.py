"""Tests for Phase 9B — proactive market intelligence alerts.

Covers: new MarketConditions primitives (index move, asset move, risk-off
alignment), MarketIntelligence orchestration (each check + run_all_checks
concurrency/exception-isolation), scheduler wiring into
check_market_conditions, cooldown suppression, and the morning brief's
macro context line. All external API calls are mocked — no real network,
DB, or WhatsApp calls.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from src.monitor.conditions import MarketConditions
from src.monitor.market_intelligence import MarketIntelligence
from src.monitor.scheduler import MarketMonitor

# ---------------------------------------------------------------------------
# New MarketConditions primitives — pure functions
# ---------------------------------------------------------------------------

class TestNewConditionPrimitives:
    def setup_method(self):
        self.cond = MarketConditions()

    def test_check_index_move_triggered_up(self):
        triggered, reason = self.cond.check_index_move("NIFTY", current=24650, reference=24400, threshold_pct=1.0)
        assert triggered is True
        assert "NIFTY" in reason and "+1.0%" in reason

    def test_check_index_move_triggered_down(self):
        triggered, reason = self.cond.check_index_move("SENSEX", current=80500, reference=81500, threshold_pct=1.0)
        assert triggered is True
        assert "-1.2%" in reason

    def test_check_index_move_not_triggered(self):
        triggered, _ = self.cond.check_index_move("NIFTY", current=24450, reference=24400, threshold_pct=1.0)
        assert triggered is False

    def test_check_index_move_no_reference_never_triggers(self):
        triggered, _ = self.cond.check_index_move("NIFTY", current=24650, reference=0, threshold_pct=1.0)
        assert triggered is False

    def test_check_asset_move_triggered(self):
        triggered, reason = self.cond.check_asset_move("Crude", change_pct=2.5, threshold_pct=2.0)
        assert triggered is True
        assert "Crude" in reason and "+2.5%" in reason

    def test_check_asset_move_not_triggered(self):
        triggered, _ = self.cond.check_asset_move("Gold", change_pct=1.0, threshold_pct=1.5)
        assert triggered is False

    def test_check_risk_off_alignment_triggered(self):
        signals = {"crude_up": True, "gold_up": True, "sp500_down": True}
        triggered, reason = self.cond.check_risk_off_alignment(signals, min_count=3)
        assert triggered is True
        assert "3/3" in reason

    def test_check_risk_off_alignment_not_triggered_below_count(self):
        signals = {"crude_up": True, "gold_up": False, "sp500_down": True}
        triggered, _ = self.cond.check_risk_off_alignment(signals, min_count=3)
        assert triggered is False

    def test_check_risk_off_alignment_exact_threshold(self):
        signals = {"crude_up": True, "gold_up": True, "sp500_down": False}
        triggered, _ = self.cond.check_risk_off_alignment(signals, min_count=2)
        assert triggered is True


# ---------------------------------------------------------------------------
# MarketIntelligence orchestration
# ---------------------------------------------------------------------------

def _settings(**overrides) -> dict:
    base = {
        "crude_move_threshold": 2.0,
        "gold_move_threshold": 1.5,
        "nifty_move_threshold": 1.0,
        "sensex_move_threshold": 1.0,
        "vix_spike_threshold": 14.0,
        "pcr_shift_threshold": 0.3,
        "risk_off_count_threshold": 3,
    }
    base.update(overrides)
    return base


class TestMacroSignals:
    def setup_method(self):
        self.mi = MarketIntelligence()

    def test_crude_spike_detected(self):
        pulse = {"assets": {"crude_oil": {"change_pct": 3.0}, "gold": {"change_pct": 0.2}, "sp500": {"change_pct": 0.1}}}
        alerts = self.mi.check_macro_signals(pulse, _settings())
        types = [a["type"] for a in alerts]
        assert "macro_crude" in types

    def test_gold_spike_detected(self):
        pulse = {"assets": {"crude_oil": {"change_pct": 0.1}, "gold": {"change_pct": 2.0}, "sp500": {"change_pct": 0.1}}}
        alerts = self.mi.check_macro_signals(pulse, _settings())
        types = [a["type"] for a in alerts]
        assert "macro_gold" in types

    def test_no_macro_alert_below_thresholds(self):
        pulse = {"assets": {"crude_oil": {"change_pct": 0.5}, "gold": {"change_pct": 0.3}, "sp500": {"change_pct": 0.1}}}
        alerts = self.mi.check_macro_signals(pulse, _settings())
        assert alerts == []

    def test_risk_off_multi_signal_alignment(self):
        pulse = {"assets": {
            "crude_oil": {"change_pct": 2.5},
            "gold": {"change_pct": 1.8},
            "sp500": {"change_pct": -1.5},
        }}
        alerts = self.mi.check_macro_signals(pulse, _settings())
        risk_off = [a for a in alerts if a["type"] == "macro_risk_off"]
        assert len(risk_off) == 1
        assert risk_off[0]["severity"] == "critical"

    def test_risk_off_not_triggered_with_only_two_signals(self):
        pulse = {"assets": {
            "crude_oil": {"change_pct": 2.5},
            "gold": {"change_pct": 1.8},
            "sp500": {"change_pct": 0.2},
        }}
        alerts = self.mi.check_macro_signals(pulse, _settings())
        assert not any(a["type"] == "macro_risk_off" for a in alerts)

    def test_error_pulse_yields_no_alerts(self):
        alerts = self.mi.check_macro_signals({"error": "timeout"}, _settings())
        assert alerts == []

    def test_empty_pulse_yields_no_alerts(self):
        assert self.mi.check_macro_signals({}, _settings()) == []

    def test_macro_crude_alert_carries_dedup_fields(self):
        # Confirmed live (2026-07-13): fired 3x in ~61 min with no dedup at
        # all — only cooldown_macro (30 min) gated it, and consecutive polls
        # spaced ~31 min apart trivially cleared that with no value check.
        pulse = {"assets": {"crude_oil": {"change_pct": 3.0}, "gold": {"change_pct": 0.2}, "sp500": {"change_pct": 0.1}}}
        alerts = self.mi.check_macro_signals(pulse, _settings())
        crude_alert = next(a for a in alerts if a["type"] == "macro_crude")
        assert crude_alert["dedup_key"] == "last_fired_crude_pct"
        assert crude_alert["value"] == 3.0
        assert crude_alert["dedup_strict"] is True
        assert crude_alert["dedup_min_delta"] == 0.5
        assert crude_alert["dedup_min_minutes"] == 15


class TestVixCheck:
    def setup_method(self):
        self.mi = MarketIntelligence()

    def test_vix_spike_detected(self):
        alerts = self.mi.check_vix(current_vix=16.0, open_vix=13.0, settings=_settings())
        assert len(alerts) == 1
        assert alerts[0]["type"] == "macro_vix"

    def test_vix_no_spike_below_threshold(self):
        alerts = self.mi.check_vix(current_vix=13.5, open_vix=13.0, settings=_settings())
        assert alerts == []

    def test_vix_no_open_reference_yields_no_alert(self):
        alerts = self.mi.check_vix(current_vix=16.0, open_vix=None, settings=_settings())
        assert alerts == []


class TestIndexMovement:
    def setup_method(self):
        self.mi = MarketIntelligence()

    def test_nifty_move_detected(self):
        alerts = self.mi.check_index_movement(
            nifty_spot=24650, last_nifty_spot=24400,
            sensex_spot=80000, last_sensex_spot=80000,
            settings=_settings(),
        )
        types = [a["type"] for a in alerts]
        assert "index_move_nifty" in types
        assert "index_move_sensex" not in types

    def test_sensex_move_detected(self):
        alerts = self.mi.check_index_movement(
            nifty_spot=24400, last_nifty_spot=24400,
            sensex_spot=81500, last_sensex_spot=80500,
            settings=_settings(),
        )
        types = [a["type"] for a in alerts]
        assert "index_move_sensex" in types

    def test_no_move_no_alert(self):
        alerts = self.mi.check_index_movement(
            nifty_spot=24420, last_nifty_spot=24400,
            sensex_spot=80100, last_sensex_spot=80000,
            settings=_settings(),
        )
        assert alerts == []

    def test_no_prior_reference_yields_no_alert(self):
        alerts = self.mi.check_index_movement(
            nifty_spot=24650, last_nifty_spot=None,
            sensex_spot=80000, last_sensex_spot=None,
            settings=_settings(),
        )
        assert alerts == []


class TestOiWallBreak:
    """Priority 1 (2026-07-10): oi_call_wall_break/oi_put_wall_break now only
    reach Telegram after the hold has lasted wall_break_confirm_seconds
    continuously — the raw touch is logged (delivered=False) but not
    alerted, and a touch-then-revert fires oi_wall_rejection instead.

    Time-based (not poll-count-based) since Piece C (2026-07-11) — see
    conditions.py's update_wall_break_hold_since docstring for why a tick
    count stopped meaning anything fixed once checks can fire on live WS
    ticks instead of only once per poll."""

    def setup_method(self):
        self.mi = MarketIntelligence()
        self.t0 = datetime(2026, 7, 13, 10, 0, 0, tzinfo=timezone.utc)

    def test_single_touch_logs_raw_event_but_does_not_confirm(self):
        alerts, holds = self.mi.check_oi_walls(
            spot=24410, prev_spot=24390, call_wall=24400, put_wall=24000, now=self.t0,
        )
        raw = [a for a in alerts if a["type"] == "oi_call_wall_break"]
        assert len(raw) == 1
        assert raw[0]["delivered"] is False
        assert holds["call_wall_hold_since"] == self.t0.isoformat()
        assert "call_wall_break_confirmed" not in holds

    def test_put_wall_single_touch_logs_raw_event(self):
        alerts, holds = self.mi.check_oi_walls(
            spot=23990, prev_spot=24010, call_wall=24400, put_wall=24000, now=self.t0,
        )
        raw = [a for a in alerts if a["type"] == "oi_put_wall_break"]
        assert len(raw) == 1
        assert raw[0]["delivered"] is False
        assert holds["put_wall_hold_since"] == self.t0.isoformat()

    def test_no_break_no_alert_hold_clears(self):
        alerts, holds = self.mi.check_oi_walls(
            spot=24300, prev_spot=24290, call_wall=24400, put_wall=24000, now=self.t0,
        )
        assert alerts == []
        assert holds["call_wall_hold_since"] is None
        assert holds["put_wall_hold_since"] is None

    def test_missing_walls_yields_no_alert(self):
        alerts, holds = self.mi.check_oi_walls(spot=24410, prev_spot=24390, call_wall=None, put_wall=None)
        assert alerts == []
        assert holds == {}

    def test_confirmed_after_hold_duration_elapses(self):
        settings = {"wall_break_confirm_seconds": 60}
        session_state: dict = {}
        confirmed_alerts = []
        # Spot holds beyond the call wall continuously across polls at
        # t=0, t=30s, t=65s -- confirmation must fire once >= 60s elapsed.
        for offset, spot in ((0, 24410), (30, 24420), (65, 24430)):
            now = self.t0 + timedelta(seconds=offset)
            alerts, holds = self.mi.check_oi_walls(
                spot=spot, prev_spot=24390, call_wall=24400, put_wall=24000,
                session_state=session_state, settings=settings, now=now,
            )
            session_state.update(holds)
            confirmed_alerts.extend(a for a in alerts if a["type"] == "oi_call_wall_break" and a.get("delivered") is not False)
        assert len(confirmed_alerts) == 1
        assert session_state["call_wall_break_confirmed"] is True

    def test_confirmed_wall_break_alert_carries_dedup_key_and_value(self):
        """Priority B3 (2026-07-11) — the scheduler needs these to gate
        near-duplicate re-fires against the last FIRED spot value."""
        settings = {"wall_break_confirm_seconds": 60}
        session_state: dict = {}
        confirmed = None
        for offset, spot in ((0, 24410), (30, 24420), (65, 24430)):
            now = self.t0 + timedelta(seconds=offset)
            alerts, holds = self.mi.check_oi_walls(
                spot=spot, prev_spot=24390, call_wall=24400, put_wall=24000,
                session_state=session_state, settings=settings, now=now,
            )
            session_state.update(holds)
            for a in alerts:
                if a["type"] == "oi_call_wall_break" and a.get("delivered") is not False:
                    confirmed = a
        assert confirmed is not None
        assert confirmed["dedup_key"] == "last_fired_call_wall_break_spot"
        assert confirmed["value"] == 24430

    def test_rejection_fires_on_touch_then_revert_before_confirmation(self):
        settings = {"wall_break_confirm_seconds": 60}
        session_state: dict = {}
        # t=0: touch (hold starts). t=10s: reverts back inside before 60s elapse.
        alerts1, holds1 = self.mi.check_oi_walls(
            spot=24410, prev_spot=24390, call_wall=24400, put_wall=24000,
            session_state=session_state, settings=settings, now=self.t0,
        )
        session_state.update(holds1)
        alerts2, holds2 = self.mi.check_oi_walls(
            spot=24380, prev_spot=24410, call_wall=24400, put_wall=24000,
            session_state=session_state, settings=settings, now=self.t0 + timedelta(seconds=10),
        )
        rejection = [a for a in alerts2 if a["type"] == "oi_wall_rejection"]
        assert len(rejection) == 1
        assert "call wall" in rejection[0]["message"]

    def test_whipsaw_across_wall_confirms_once_not_repeatedly(self):
        """Regression test for the reported failure: spot bounces across the
        NIFTY 24200 call wall multiple times before finally holding — this
        must yield exactly one hold-confirmed alert and rejection alerts for
        the earlier bounces, not a fresh oi_call_wall_break every check."""
        settings = {"wall_break_confirm_seconds": 60}
        session_state: dict = {}
        confirmed = []
        rejections = []
        # Bounce sequence: touch, revert, touch, revert, then hold >= 60s.
        events = [
            (0, 24205), (10, 24195), (20, 24210), (30, 24190),
            (40, 24205), (105, 24215), (170, 24225),
        ]
        prev = 24190
        for offset, spot in events:
            now = self.t0 + timedelta(seconds=offset)
            alerts, holds = self.mi.check_oi_walls(
                spot=spot, prev_spot=prev, call_wall=24200, put_wall=24000,
                session_state=session_state, settings=settings, now=now,
            )
            session_state.update(holds)
            confirmed.extend(a for a in alerts if a["type"] == "oi_call_wall_break" and a.get("delivered") is not False)
            rejections.extend(a for a in alerts if a["type"] == "oi_wall_rejection")
            prev = spot
        assert len(confirmed) == 1
        assert len(rejections) >= 1


class TestPcrShiftCheck:
    def setup_method(self):
        self.mi = MarketIntelligence()

    def test_pcr_shift_detected(self):
        alerts = self.mi.check_pcr_shift(current_pcr=1.5, open_pcr=1.0, settings=_settings())
        assert len(alerts) == 1
        assert alerts[0]["type"] == "pcr_shift"

    def test_pcr_shift_alert_carries_dedup_key_and_value(self):
        """Priority B3 (2026-07-11) — the scheduler needs these to gate
        near-duplicate re-fires against the last FIRED value."""
        alerts = self.mi.check_pcr_shift(current_pcr=1.5, open_pcr=1.0, settings=_settings())
        assert alerts[0]["dedup_key"] == "last_fired_pcr"
        assert alerts[0]["value"] == 1.5

    def test_pcr_shift_alert_carries_strict_dedup_thresholds(self):
        # Tightened (2026-07-13): OR semantics let pure time-passing re-fire
        # this with no PCR movement — now strict (AND), with the delta
        # threshold raised from the generic 0.05 default to the requested >0.1.
        alerts = self.mi.check_pcr_shift(current_pcr=1.5, open_pcr=1.0, settings=_settings())
        assert alerts[0]["dedup_strict"] is True
        assert alerts[0]["dedup_min_delta"] == 0.1
        assert alerts[0]["dedup_min_minutes"] == 15

    def test_pcr_no_shift_no_alert(self):
        alerts = self.mi.check_pcr_shift(current_pcr=1.1, open_pcr=1.0, settings=_settings())
        assert alerts == []

    def test_pcr_missing_values_no_alert(self):
        assert self.mi.check_pcr_shift(None, 1.0, _settings()) == []
        assert self.mi.check_pcr_shift(1.5, None, _settings()) == []


class TestRunAllChecks:
    @pytest.mark.anyio
    async def test_run_all_checks_aggregates_all_triggered_alerts(self):
        mi = MarketIntelligence()
        market_data = {
            "global_pulse": {"assets": {
                "crude_oil": {"change_pct": 3.0}, "gold": {"change_pct": 0.1}, "sp500": {"change_pct": 0.1},
            }},
            "vix": 16.0,
            "nifty_spot": 24650,
            "sensex_spot": 80000,
            "nifty_pcr": 1.5,
            "nifty_call_wall": 24700,
            "nifty_put_wall": 24300,
        }
        session_state = {
            "open_vix": 13.0,
            "last_nifty_spot": 24400,
            "last_sensex_spot": 80000,
            "open_call_wall": 24700,
            "open_put_wall": 24300,
            "open_pcr": 1.0,
        }
        alerts, _streaks = await mi.run_all_checks(market_data, session_state, _settings())
        types = {a["type"] for a in alerts}
        assert "macro_crude" in types
        assert "macro_vix" in types
        assert "index_move_nifty" in types
        assert "pcr_shift" in types

    @pytest.mark.anyio
    async def test_run_all_checks_never_raises_when_one_sub_check_fails(self):
        mi = MarketIntelligence()
        # check_macro_signals will raise because "assets" is not a dict —
        # confirm the exception is swallowed and other checks still run.
        market_data = {
            "global_pulse": {"assets": "not-a-dict"},
            "vix": 16.0,
            "nifty_spot": 24650,
            "sensex_spot": 80000,
            "nifty_pcr": None,
            "nifty_call_wall": None,
            "nifty_put_wall": None,
        }
        session_state = {
            "open_vix": 13.0,
            "last_nifty_spot": 24400,
            "last_sensex_spot": 80000,
            "open_call_wall": None,
            "open_put_wall": None,
            "open_pcr": None,
        }
        # Should not raise despite the malformed global_pulse.
        alerts, _streaks = await mi.run_all_checks(market_data, session_state, _settings())
        types = {a["type"] for a in alerts}
        assert "index_move_nifty" in types
        assert "macro_vix" in types

    @pytest.mark.anyio
    async def test_run_all_checks_empty_data_yields_no_alerts(self):
        mi = MarketIntelligence()
        alerts, streaks = await mi.run_all_checks({}, {}, _settings())
        assert alerts == []
        assert streaks == {}


# ---------------------------------------------------------------------------
# Scheduler wiring — check_market_conditions calls run_all_checks, applies
# cooldown, persists alerts, and updates last_*_spot for the next poll.
# ---------------------------------------------------------------------------

class TestSchedulerCheckMarketConditions:
    def setup_method(self):
        with patch("src.monitor.scheduler.MonitorRepository"), \
             patch("src.monitor.scheduler.MonitorBootstrap"), \
             patch("src.monitor.scheduler.PositionTracker"):
            self.monitor = MarketMonitor()
        self.monitor.repo = AsyncMock()
        self.monitor.alerter = AsyncMock()

    @pytest.mark.anyio
    async def test_no_session_state_skips_checks_entirely(self):
        self.monitor.repo.get_user_settings.return_value = _settings()
        self.monitor.repo.get_session_state.return_value = None
        self.monitor._get_market_intelligence_data = AsyncMock()

        await self.monitor.check_market_conditions({"id": "u1"})

        self.monitor._get_market_intelligence_data.assert_not_called()
        self.monitor.alerter.send_macro_alert.assert_not_awaited()

    @pytest.mark.anyio
    async def test_triggered_alert_is_sent_and_persisted(self):
        self.monitor.repo.get_user_settings.return_value = _settings()
        self.monitor.repo.get_session_state.return_value = {
            "open_vix": 13.0, "last_nifty_spot": 24400, "last_sensex_spot": 80000,
            "open_call_wall": None, "open_put_wall": None, "open_pcr": None,
        }
        self.monitor.repo.get_last_alert_time.return_value = None
        self.monitor._get_market_intelligence_data = AsyncMock(return_value={
            "global_pulse": {}, "vix": 16.0,
            "nifty_spot": 24650, "sensex_spot": 80000,
            "nifty_pcr": None, "nifty_call_wall": None, "nifty_put_wall": None,
        })
        self.monitor.alerter.send_macro_alert = AsyncMock(return_value=True)

        await self.monitor.check_market_conditions({"id": "u1"})

        self.monitor.alerter.send_macro_alert.assert_awaited()
        self.monitor.repo.save_alert.assert_awaited()
        saved_alert = self.monitor.repo.save_alert.call_args.args[1]
        assert saved_alert["alert_type"] in {"macro_vix", "index_move_nifty"}
        assert "severity" in saved_alert

    @pytest.mark.anyio
    async def test_cooldown_suppresses_duplicate_alert(self):
        self.monitor.repo.get_user_settings.return_value = _settings()
        self.monitor.repo.get_session_state.return_value = {
            "open_vix": 13.0, "last_nifty_spot": 24400, "last_sensex_spot": 80000,
            "open_call_wall": None, "open_put_wall": None, "open_pcr": None,
        }
        # Alert already sent 10 seconds ago — well within any cooldown window.
        self.monitor.repo.get_last_alert_time.return_value = datetime.now(timezone.utc) - timedelta(seconds=10)
        self.monitor._get_market_intelligence_data = AsyncMock(return_value={
            "global_pulse": {}, "vix": 16.0,
            "nifty_spot": 24650, "sensex_spot": 80000,
            "nifty_pcr": None, "nifty_call_wall": None, "nifty_put_wall": None,
        })

        await self.monitor.check_market_conditions({"id": "u1"})

        self.monitor.alerter.send_macro_alert.assert_not_awaited()
        self.monitor.repo.save_alert.assert_not_awaited()

    @pytest.mark.anyio
    async def test_updates_last_spot_for_next_poll(self):
        self.monitor.repo.get_user_settings.return_value = _settings()
        self.monitor.repo.get_session_state.return_value = {
            "open_vix": None, "last_nifty_spot": 24400, "last_sensex_spot": 80000,
            "open_call_wall": None, "open_put_wall": None, "open_pcr": None,
        }
        self.monitor.repo.get_last_alert_time.return_value = None
        self.monitor._get_market_intelligence_data = AsyncMock(return_value={
            "global_pulse": {}, "vix": 0.0,
            "nifty_spot": 24500, "sensex_spot": 80200,
            "nifty_pcr": None, "nifty_call_wall": None, "nifty_put_wall": None,
        })

        await self.monitor.check_market_conditions({"id": "u1"})

        saved_state = self.monitor.repo.save_session_state.call_args.args[1]
        assert saved_state["last_nifty_spot"] == 24500
        assert saved_state["last_sensex_spot"] == 80200

    @pytest.mark.anyio
    async def test_dedup_gate_suppresses_near_identical_pcr_refire_past_cooldown(self):
        """Priority B3 (2026-07-11) — cooldown alone (900s default) would let
        this refire since >900s have passed, but the value (1.32 -> 1.35,
        delta 0.03) hasn't moved enough and <30 min have elapsed since the
        last FIRED value — the dedup gate must suppress it."""
        self.monitor.repo.get_user_settings.return_value = _settings(cooldown_pcr=900)
        self.monitor.repo.get_session_state.return_value = {
            "open_vix": None, "last_nifty_spot": 24400, "last_sensex_spot": 80000,
            "open_call_wall": None, "open_put_wall": None, "open_pcr": 1.0,
            "last_fired_pcr": 1.32,
        }
        # Cooldown (900s = 15min) has cleared, but only 20 min have passed —
        # still inside the 30-minute dedup window.
        self.monitor.repo.get_last_alert_time.return_value = datetime.now(timezone.utc) - timedelta(minutes=20)
        self.monitor._get_market_intelligence_data = AsyncMock(return_value={
            "global_pulse": {}, "vix": 0.0,
            "nifty_spot": 24400, "sensex_spot": 80000,
            "nifty_pcr": 1.35, "nifty_call_wall": None, "nifty_put_wall": None,
        })

        await self.monitor.check_market_conditions({"id": "u1"})

        self.monitor.alerter.send_macro_alert.assert_not_awaited()
        self.monitor.repo.save_alert.assert_not_awaited()

    @pytest.mark.anyio
    async def test_dedup_gate_allows_refire_when_value_moved_enough(self):
        self.monitor.repo.get_user_settings.return_value = _settings(cooldown_pcr=900)
        self.monitor.repo.get_session_state.return_value = {
            "open_vix": None, "last_nifty_spot": 24400, "last_sensex_spot": 80000,
            "open_call_wall": None, "open_put_wall": None, "open_pcr": 1.0,
            "last_fired_pcr": 1.32,
        }
        self.monitor.repo.get_last_alert_time.return_value = datetime.now(timezone.utc) - timedelta(minutes=20)
        self.monitor._get_market_intelligence_data = AsyncMock(return_value={
            "global_pulse": {}, "vix": 0.0,
            "nifty_spot": 24400, "sensex_spot": 80000,
            # 1.32 -> 1.50 is a 0.18 delta, well past the 0.05 default min_delta.
            "nifty_pcr": 1.50, "nifty_call_wall": None, "nifty_put_wall": None,
        })
        self.monitor.alerter.send_macro_alert = AsyncMock(return_value=True)

        await self.monitor.check_market_conditions({"id": "u1"})

        self.monitor.alerter.send_macro_alert.assert_awaited()
        saved_state = self.monitor.repo.save_session_state.call_args.args[1]
        assert saved_state["last_fired_pcr"] == 1.50

    @pytest.mark.anyio
    async def test_macro_crude_suppressed_on_repeat_poll_with_no_meaningful_move(self):
        """Confirmed live (2026-07-13): MACRO_CRUDE fired 3x in ~61 min with
        no dedup at all — cooldown_macro (default 1800s=30min) alone let it
        re-fire every ~31min since consecutive polls happened to be spaced
        just past that window, regardless of whether crude actually moved."""
        self.monitor.repo.get_user_settings.return_value = _settings()
        self.monitor.repo.get_session_state.return_value = {
            "open_vix": None, "last_nifty_spot": 24400, "last_sensex_spot": 80000,
            "open_call_wall": None, "open_put_wall": None, "open_pcr": None,
            "last_fired_crude_pct": 3.0,
        }
        # Cooldown (1800s=30min) has cleared (31 min passed) — under the old
        # code this alone was enough to re-fire.
        self.monitor.repo.get_last_alert_time.return_value = datetime.now(timezone.utc) - timedelta(minutes=31)
        self.monitor._get_market_intelligence_data = AsyncMock(return_value={
            "global_pulse": {"assets": {
                "crude_oil": {"change_pct": 3.1},  # 0.1 delta — below the 0.5 threshold
                "gold": {"change_pct": 0.2}, "sp500": {"change_pct": 0.1},
            }},
            "vix": 0.0, "nifty_spot": 24400, "sensex_spot": 80000,
            "nifty_pcr": None, "nifty_call_wall": None, "nifty_put_wall": None,
        })

        await self.monitor.check_market_conditions({"id": "u1"})

        self.monitor.alerter.send_macro_alert.assert_not_awaited()
        self.monitor.repo.save_alert.assert_not_awaited()

    @pytest.mark.anyio
    async def test_macro_crude_refires_when_move_genuinely_shifts(self):
        self.monitor.repo.get_user_settings.return_value = _settings()
        self.monitor.repo.get_session_state.return_value = {
            "open_vix": None, "last_nifty_spot": 24400, "last_sensex_spot": 80000,
            "open_call_wall": None, "open_put_wall": None, "open_pcr": None,
            "last_fired_crude_pct": 3.0,
        }
        self.monitor.repo.get_last_alert_time.return_value = datetime.now(timezone.utc) - timedelta(minutes=31)
        self.monitor._get_market_intelligence_data = AsyncMock(return_value={
            "global_pulse": {"assets": {
                "crude_oil": {"change_pct": 4.0},  # 1.0 delta — past the 0.5 threshold
                "gold": {"change_pct": 0.2}, "sp500": {"change_pct": 0.1},
            }},
            "vix": 0.0, "nifty_spot": 24400, "sensex_spot": 80000,
            "nifty_pcr": None, "nifty_call_wall": None, "nifty_put_wall": None,
        })
        self.monitor.alerter.send_macro_alert = AsyncMock(return_value=True)

        await self.monitor.check_market_conditions({"id": "u1"})

        self.monitor.alerter.send_macro_alert.assert_awaited()
        saved_state = self.monitor.repo.save_session_state.call_args.args[1]
        assert saved_state["last_fired_crude_pct"] == 4.0

    @pytest.mark.anyio
    async def test_pinning_risk_suppressed_on_repeat_poll_same_max_pain_and_distance(self):
        """Confirmed live (2026-07-13): PINNING_RISK fired 3x in ~65 min with
        no dedup at all."""
        self.monitor.repo.get_user_settings.return_value = _settings()
        self.monitor.repo.get_session_state.return_value = {
            "open_vix": None, "last_nifty_spot": 24400, "last_sensex_spot": 80000,
            "open_call_wall": None, "open_put_wall": None, "open_pcr": None,
            "last_fired_pinning_distance": 5.0,
            "last_fired_pinning_max_pain": 24200.0,
        }
        self.monitor.repo.get_last_alert_time.return_value = datetime.now(timezone.utc) - timedelta(minutes=31)
        self.monitor._get_market_intelligence_data = AsyncMock(return_value={
            "global_pulse": {}, "vix": 0.0,
            "nifty_spot": 24206, "sensex_spot": 80000,  # distance 6 — same max_pain, <15pt move
            "nifty_pcr": None, "nifty_call_wall": None, "nifty_put_wall": None,
            "nifty_max_pain": 24200.0, "nifty_is_expiry_week": True,
        })

        await self.monitor.check_market_conditions({"id": "u1"})

        self.monitor.alerter.send_macro_alert.assert_not_awaited()
        self.monitor.repo.save_alert.assert_not_awaited()

    @pytest.mark.anyio
    async def test_pinning_risk_refires_when_max_pain_strike_changes(self):
        # Distance stays ~identical, but the max-pain strike itself moved —
        # this alone must be enough to re-fire (the OR condition the user
        # explicitly asked for).
        self.monitor.repo.get_user_settings.return_value = _settings()
        self.monitor.repo.get_session_state.return_value = {
            "open_vix": None, "last_nifty_spot": 24400, "last_sensex_spot": 80000,
            "open_call_wall": None, "open_put_wall": None, "open_pcr": None,
            "last_fired_pinning_distance": 5.0,
            "last_fired_pinning_max_pain": 24200.0,
        }
        self.monitor.repo.get_last_alert_time.return_value = datetime.now(timezone.utc) - timedelta(minutes=31)
        self.monitor._get_market_intelligence_data = AsyncMock(return_value={
            "global_pulse": {}, "vix": 0.0,
            "nifty_spot": 24255, "sensex_spot": 80000,  # distance ~5 again, but...
            "nifty_pcr": None, "nifty_call_wall": None, "nifty_put_wall": None,
            "nifty_max_pain": 24250.0, "nifty_is_expiry_week": True,  # ...max_pain shifted
        })
        self.monitor.alerter.send_macro_alert = AsyncMock(return_value=True)

        await self.monitor.check_market_conditions({"id": "u1"})

        self.monitor.alerter.send_macro_alert.assert_awaited()

    @pytest.mark.anyio
    async def test_pinning_risk_refires_when_distance_moves_enough(self):
        self.monitor.repo.get_user_settings.return_value = _settings()
        self.monitor.repo.get_session_state.return_value = {
            "open_vix": None, "last_nifty_spot": 24400, "last_sensex_spot": 80000,
            "open_call_wall": None, "open_put_wall": None, "open_pcr": None,
            "last_fired_pinning_distance": 5.0,
            "last_fired_pinning_max_pain": 24200.0,
        }
        self.monitor.repo.get_last_alert_time.return_value = datetime.now(timezone.utc) - timedelta(minutes=31)
        self.monitor._get_market_intelligence_data = AsyncMock(return_value={
            "global_pulse": {}, "vix": 0.0,
            "nifty_spot": 24230, "sensex_spot": 80000,  # distance 30 — >15pt move, same max_pain
            "nifty_pcr": None, "nifty_call_wall": None, "nifty_put_wall": None,
            "nifty_max_pain": 24200.0, "nifty_is_expiry_week": True,
        })
        self.monitor.alerter.send_macro_alert = AsyncMock(return_value=True)

        await self.monitor.check_market_conditions({"id": "u1"})

        self.monitor.alerter.send_macro_alert.assert_awaited()


# ---------------------------------------------------------------------------
# Morning brief — macro context line
# ---------------------------------------------------------------------------

class TestMorningBriefMacroContext:
    def setup_method(self):
        with patch("src.monitor.scheduler.MonitorRepository"), \
             patch("src.monitor.scheduler.MonitorBootstrap"), \
             patch("src.monitor.scheduler.PositionTracker"):
            self.monitor = MarketMonitor()
        self.monitor.repo = AsyncMock()

    def test_macro_risk_note_risk_off_with_two_plus_signals(self):
        pulse = {"assets": {
            "crude_oil": {"change_pct": 2.5},
            "gold": {"change_pct": 1.8},
            "sp500": {"change_pct": 0.1},
        }}
        note = self.monitor._macro_risk_note(pulse, vix=13.0)
        assert note.startswith("RISK-OFF:")
        assert "Crude" in note and "Gold" in note

    def test_macro_risk_note_single_signal_is_a_watch(self):
        pulse = {"assets": {
            "crude_oil": {"change_pct": 2.5},
            "gold": {"change_pct": 0.1},
            "sp500": {"change_pct": 0.1},
        }}
        note = self.monitor._macro_risk_note(pulse, vix=13.0)
        assert note.startswith("Watch:")

    def test_macro_risk_note_neutral_when_no_signals(self):
        pulse = {"assets": {
            "crude_oil": {"change_pct": 0.1},
            "gold": {"change_pct": 0.1},
            "sp500": {"change_pct": 0.1},
        }}
        note = self.monitor._macro_risk_note(pulse, vix=13.0)
        assert note == "Global: neutral"

    def test_macro_risk_note_vix_counts_as_a_signal(self):
        pulse = {"assets": {
            "crude_oil": {"change_pct": 0.1},
            "gold": {"change_pct": 0.1},
            "sp500": {"change_pct": 0.1},
        }}
        note = self.monitor._macro_risk_note(pulse, vix=17.0)
        assert note.startswith("Watch:")
        assert "VIX" in note

    @pytest.mark.anyio
    async def test_send_morning_brief_includes_macro_note_in_message(self):
        self.monitor.repo.get_active_positions.return_value = []
        self.monitor._get_vix = AsyncMock(return_value=13.0)
        self.monitor._get_index_quote = AsyncMock(side_effect=[
            {"last_price": 24400, "previous_close": 24300},
            {"last_price": 80000, "previous_close": 79800},
        ])
        self.monitor._get_key_levels = AsyncMock(return_value={"support": 24000, "resistance": 24700})
        self.monitor._get_calendar = AsyncMock(return_value={"next_nse_expiry": "2026-07-10"})
        self.monitor._get_global_sentiment = AsyncMock(return_value="NEUTRAL")
        self.monitor._get_global_pulse_raw = AsyncMock(return_value={"assets": {
            "crude_oil": {"change_pct": 2.5}, "gold": {"change_pct": 1.8}, "sp500": {"change_pct": 0.1},
        }})
        self.monitor._get_option_chain = AsyncMock(return_value={
            "records": {"underlyingValue": 24400, "expiryDates": ["10-Jul-2026"]},
        })

        with patch("src.options.analytics.calculate_pcr", return_value={"pcr_oi": 1.2}):
            captured = {}

            async def _fake_send_morning_brief(user, data):
                captured["data"] = data
                return True

            self.monitor.alerter.send_morning_brief = _fake_send_morning_brief
            delivered = await self.monitor.send_morning_brief({"id": "u1", "name": "trader"})

        assert delivered is True
        assert captured["data"]["macro_note"].startswith("RISK-OFF:")

    @pytest.mark.anyio
    async def test_alerter_message_template_includes_macro_line(self):
        from src.monitor.alerts import WhatsAppAlerter

        alerter = WhatsAppAlerter()
        alerter.send = AsyncMock(return_value=True)
        data = {
            "date": "2026-07-08", "expiry": "2026-07-10", "nifty": 24400, "sensex": 80000,
            "vix": 13.0, "global_sentiment": "NEUTRAL", "macro_note": "RISK-OFF: Crude +2.5%",
            "positions": [], "support": 24000, "resistance": 24700,
        }
        await alerter.send_morning_brief({"whatsapp_phone": "1", "callmebot_key": "k"}, data)
        sent_message = alerter.send.call_args.args[2]
        assert "RISK-OFF: Crude +2.5%" in sent_message

    @pytest.mark.anyio
    async def test_alerter_message_template_omits_macro_line_when_absent(self):
        from src.monitor.alerts import WhatsAppAlerter

        alerter = WhatsAppAlerter()
        alerter.send = AsyncMock(return_value=True)
        data = {
            "date": "2026-07-08", "expiry": "2026-07-10", "nifty": 24400, "sensex": 80000,
            "vix": 13.0, "global_sentiment": "NEUTRAL",
            "positions": [], "support": 24000, "resistance": 24700,
        }
        await alerter.send_morning_brief({"whatsapp_phone": "1", "callmebot_key": "k"}, data)
        sent_message = alerter.send.call_args.args[2]
        assert "MORNING BRIEF" in sent_message
