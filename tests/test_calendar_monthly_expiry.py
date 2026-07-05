"""
Pre-Phase 4 fixes — monthly expiry calculation correctness.

NSE moved all index expiries to Tuesday (effective 2026).
BSE (SENSEX/BANKEX) retained Thursday expiry.

SEBI weekly-expiry rationalization: BANKNIFTY, FINNIFTY, MIDCPNIFTY (NSE)
and BANKEX (BSE) are monthly-only (last Tuesday / last Thursday of month).
NIFTY (NSE) and SENSEX (BSE) retain weekly series.

Fixture date: July 2026. Last weekday-of-month occurrences:
  Tuesday   28-Jul-2026  (NSE indices)
  Thursday  30-Jul-2026  (BSE indices)
"""
from __future__ import annotations

from datetime import date

import pytest

from src.market.calendar import (
    _last_weekday_of_month,
    _nearest_monthly_expiry,
    _nearest_expiry_algorithmic,
    _reset_holiday_cache,
    get_market_calendar,
)


@pytest.fixture(autouse=True)
def _reset_calendar():
    _reset_holiday_cache()
    yield
    _reset_holiday_cache()


class TestLastWeekdayOfMonth:
    def test_last_monday_july_2026(self):
        assert _last_weekday_of_month(2026, 7, 0) == date(2026, 7, 27)

    def test_last_tuesday_july_2026(self):
        assert _last_weekday_of_month(2026, 7, 1) == date(2026, 7, 28)

    def test_last_wednesday_july_2026(self):
        assert _last_weekday_of_month(2026, 7, 2) == date(2026, 7, 29)

    def test_last_thursday_july_2026(self):
        assert _last_weekday_of_month(2026, 7, 3) == date(2026, 7, 30)

    def test_december_rolls_into_next_year_bounds(self):
        # last Thursday of December 2026 must stay within December
        result = _last_weekday_of_month(2026, 12, 3)
        assert result.month == 12
        assert result.year == 2026


class TestNearestMonthlyExpiry:
    """From a date early in July 2026, each index's monthly expiry is this month's."""

    FROM_DATE = date(2026, 7, 4)  # Saturday

    def test_banknifty_last_tuesday(self):
        assert _nearest_monthly_expiry("banknifty", self.FROM_DATE) == date(2026, 7, 28)

    def test_finnifty_last_tuesday(self):
        assert _nearest_monthly_expiry("finnifty", self.FROM_DATE) == date(2026, 7, 28)

    def test_midcap_nifty_last_tuesday(self):
        assert _nearest_monthly_expiry("midcap_nifty", self.FROM_DATE) == date(2026, 7, 28)

    def test_nifty_last_tuesday(self):
        assert _nearest_monthly_expiry("nifty", self.FROM_DATE) == date(2026, 7, 28)

    def test_sensex_last_thursday(self):
        assert _nearest_monthly_expiry("sensex", self.FROM_DATE) == date(2026, 7, 30)

    def test_bankex_last_thursday(self):
        assert _nearest_monthly_expiry("bankex", self.FROM_DATE) == date(2026, 7, 30)

    def test_rolls_to_next_month_once_this_months_date_has_passed(self):
        after_expiry = date(2026, 7, 29)  # day after last Tuesday of July
        result = _nearest_monthly_expiry("nifty", after_expiry)
        # Last Tuesday of Aug 2026 = Aug 25, no holiday collision
        assert result == date(2026, 8, 25)


class TestNearestExpiryAlgorithmic:
    """banknifty/finnifty/midcap_nifty/bankex have no weekly series — their
    'nearest' expiry must equal their monthly expiry, not a weekly-weekday guess."""

    FROM_DATE = date(2026, 7, 4)

    def test_banknifty_nearest_equals_monthly(self):
        assert _nearest_expiry_algorithmic("banknifty", self.FROM_DATE) == date(2026, 7, 28)

    def test_finnifty_nearest_equals_monthly(self):
        assert _nearest_expiry_algorithmic("finnifty", self.FROM_DATE) == date(2026, 7, 28)

    def test_midcap_nifty_nearest_equals_monthly(self):
        assert _nearest_expiry_algorithmic("midcap_nifty", self.FROM_DATE) == date(2026, 7, 28)

    def test_bankex_nearest_equals_monthly(self):
        assert _nearest_expiry_algorithmic("bankex", self.FROM_DATE) == date(2026, 7, 30)

    def test_nifty_nearest_is_nearest_weekly_tuesday(self):
        # NIFTY weekly series — nearest Tuesday from Sat 4-Jul-2026 is 7-Jul-2026
        assert _nearest_expiry_algorithmic("nifty", self.FROM_DATE) == date(2026, 7, 7)

    def test_sensex_nearest_is_nearest_weekly_thursday(self):
        # SENSEX weekly series on Thursday — nearest from Sat 4-Jul-2026 is 9-Jul-2026
        assert _nearest_expiry_algorithmic("sensex", self.FROM_DATE) == date(2026, 7, 9)


class TestGetMarketCalendarMonthlyExpiries:
    def test_monthly_expiries_key_present(self):
        cal = get_market_calendar()
        assert "monthly_expiries" in cal

    def test_monthly_expiries_has_all_six_indices(self):
        cal = get_market_calendar()
        for idx in ("nifty", "banknifty", "finnifty", "midcap_nifty", "sensex", "bankex"):
            assert idx in cal["monthly_expiries"]


class TestLiveExpiriesUsesBSEOptionsService:
    """Sensex/Bankex live expiry falls back to BSEOptionsService when
    Zerodha instruments CSV is unavailable."""

    def test_bse_indices_use_bse_options_service(self, monkeypatch):
        from unittest.mock import MagicMock, AsyncMock
        from src.market import calendar as cal_mod
        from src.calendar import CalendarFetcher

        # Zerodha CSV unavailable (no cache, fetch returns empty)
        monkeypatch.setattr(cal_mod, "_load_zerodha_expiries_cache", lambda: {})
        async def _empty_fetch(self):
            return {}
        monkeypatch.setattr(CalendarFetcher, "fetch_all_expiries_from_zerodha", _empty_fetch)

        fake_svc = MagicMock()
        fake_svc.available_expiries.side_effect = lambda sym: {
            "SENSEX": ["30 Jul 2026", "27 Aug 2026"],
            "BANKEX": ["30 Jul 2026"],
        }[sym]
        monkeypatch.setattr(
            "src.options.bse_service.get_bse_options_service", lambda: fake_svc
        )
        # Avoid depending on live NSE options service in this test
        monkeypatch.setattr(
            "src.options.service.get_options_service",
            lambda: (_ for _ in ()).throw(RuntimeError("NSE unavailable")),
        )

        live = cal_mod._live_expiries()
        assert live.get("sensex") == "30 Jul 2026"
        assert live.get("bankex") == "30 Jul 2026"
