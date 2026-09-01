"""Regression tests for Audit-C3 — get_market_calendar()'s session_active
flag must be IST-aware, not the OS/process-local clock.

Finding: the "Session active status" block inside get_market_calendar() used
`datetime.now()` (naive, OS-local) instead of `datetime.now(_IST)`, unlike
the sibling is_market_session_open()/meta.is_market_hours(). On the
documented production host (Oracle VM, UTC), this falsely reported
nse_session_active=True for ~6 hours after real NSE close (14:45-21:00 UTC =
20:15-02:30 IST) — and would symmetrically report False during part of the
real morning IST session.

CAL-1  session_active True only when the IST wall-clock time is within market hours
CAL-2  session_active False when IST wall-clock time is after market close,
       even if the OS-local clock (patched to UTC) would fall inside the old
       naive minute-of-day window
CAL-3  session_active matches is_market_session_open()'s IST-based judgment for
       the same instant (single source of truth, no drift between the two)
CAL-4  bse_session_active follows the same IST-aware gate as nse_session_active
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

import src.market.calendar as calendar_mod
from src.market.calendar import _IST, get_market_calendar, is_market_session_open


@pytest.fixture(autouse=True)
def _reset_calendar_cache():
    calendar_mod._reset_holiday_cache()
    yield
    calendar_mod._reset_holiday_cache()


def _freeze_ist(monkeypatch, ist_dt: datetime):
    """Freeze _today_ist() to ist_dt's date, and datetime.now(_IST) (used
    directly by the session_active block and is_market_session_open()) to
    ist_dt. Does NOT touch datetime.now() with no args, matching how the
    fixed code should behave — it must never call the naive form again."""
    monkeypatch.setattr(calendar_mod, "_today_ist", lambda: ist_dt.date())

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                raise AssertionError(
                    "get_market_calendar() must not call datetime.now() without "
                    "an explicit IST tzinfo — this is exactly the regression "
                    "Audit-C3 fixed."
                )
            return ist_dt

    monkeypatch.setattr(calendar_mod, "datetime", _FrozenDateTime)


class TestCAL1SessionActiveDuringMarketHours:
    def test_true_at_noon_ist_on_a_weekday(self, monkeypatch):
        # Wednesday 2026-07-15, 12:00 IST — well within 09:15-15:30
        ist_noon = datetime(2026, 7, 15, 12, 0, tzinfo=_IST)
        _freeze_ist(monkeypatch, ist_noon)
        cal = get_market_calendar()
        assert cal["nse_session_active"] is True


class TestCAL2SessionActiveFalseAfterCloseEvenIfNaiveClockWouldSayTrue:
    def test_false_after_ist_close_on_a_weekday(self, monkeypatch):
        # Wednesday 2026-07-15, 20:00 IST (after 15:30 close).
        # The OLD naive-clock bug used datetime.now() with no tz — on a UTC
        # host, 20:00 IST is 14:30 UTC, whose hour*60+minute (870) still
        # falls inside the old buggy [555, 930] window, so the old code
        # would have wrongly returned True here. The fix must return False.
        ist_evening = datetime(2026, 7, 15, 20, 0, tzinfo=_IST)
        _freeze_ist(monkeypatch, ist_evening)
        cal = get_market_calendar()
        assert cal["nse_session_active"] is False

    def test_false_before_ist_open_on_a_weekday(self, monkeypatch):
        # Wednesday 2026-07-15, 05:00 IST (before 09:15 open).
        ist_early = datetime(2026, 7, 15, 5, 0, tzinfo=_IST)
        _freeze_ist(monkeypatch, ist_early)
        cal = get_market_calendar()
        assert cal["nse_session_active"] is False


class TestCAL3MatchesIsMarketSessionOpen:
    @pytest.mark.parametrize("hour,minute", [(9, 0), (9, 15), (12, 0), (15, 30), (15, 31), (20, 0)])
    def test_no_drift_between_the_two_implementations(self, monkeypatch, hour, minute):
        ist_dt = datetime(2026, 7, 15, hour, minute, tzinfo=_IST)
        _freeze_ist(monkeypatch, ist_dt)
        cal = get_market_calendar()
        assert cal["nse_session_active"] == is_market_session_open(cal)


class TestCAL4BseFollowsSameGate:
    def test_bse_session_active_false_after_close(self, monkeypatch):
        ist_evening = datetime(2026, 7, 15, 20, 0, tzinfo=_IST)
        _freeze_ist(monkeypatch, ist_evening)
        cal = get_market_calendar()
        assert cal["bse_session_active"] is False

    def test_bse_session_active_true_during_hours(self, monkeypatch):
        ist_noon = datetime(2026, 7, 15, 12, 0, tzinfo=_IST)
        _freeze_ist(monkeypatch, ist_noon)
        cal = get_market_calendar()
        assert cal["bse_session_active"] is True
