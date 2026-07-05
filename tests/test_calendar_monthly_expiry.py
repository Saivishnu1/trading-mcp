"""
Pre-Phase 4 fixes — monthly expiry calculation correctness.

SEBI's weekly-expiry rationalization (effective Nov 2024) left only NIFTY
(NSE) and SENSEX (BSE) with a weekly series; BANKNIFTY, FINNIFTY,
MIDCPNIFTY, and BANKEX trade monthly contracts only (last occurrence of
their expiry weekday in the month).

Fixture date: July 2026. Last weekday-of-month occurrences:
  Monday    27-Jul-2026
  Tuesday   28-Jul-2026
  Wednesday 29-Jul-2026
  Thursday  30-Jul-2026
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

    def test_banknifty_last_wednesday(self):
        assert _nearest_monthly_expiry("banknifty", self.FROM_DATE) == date(2026, 7, 29)

    def test_finnifty_last_tuesday(self):
        assert _nearest_monthly_expiry("finnifty", self.FROM_DATE) == date(2026, 7, 28)

    def test_midcap_nifty_last_monday(self):
        assert _nearest_monthly_expiry("midcap_nifty", self.FROM_DATE) == date(2026, 7, 27)

    def test_nifty_last_thursday(self):
        assert _nearest_monthly_expiry("nifty", self.FROM_DATE) == date(2026, 7, 30)

    def test_sensex_last_thursday(self):
        assert _nearest_monthly_expiry("sensex", self.FROM_DATE) == date(2026, 7, 30)

    def test_bankex_last_thursday(self):
        assert _nearest_monthly_expiry("bankex", self.FROM_DATE) == date(2026, 7, 30)

    def test_rolls_to_next_month_once_this_months_date_has_passed(self):
        after_expiry = date(2026, 7, 31)  # the day after this month's last Thursday
        result = _nearest_monthly_expiry("nifty", after_expiry)
        # Aug 27 is Ganesh Chaturthi holiday → expiry rolls back to Aug 26 (Wednesday)
        assert result == date(2026, 8, 26)


class TestNearestExpiryAlgorithmic:
    """banknifty/finnifty/midcap_nifty/bankex have no weekly series — their
    'nearest' expiry must equal their monthly expiry, not a weekly-weekday guess."""

    FROM_DATE = date(2026, 7, 4)

    def test_banknifty_nearest_equals_monthly(self):
        assert _nearest_expiry_algorithmic("banknifty", self.FROM_DATE) == date(2026, 7, 29)

    def test_finnifty_nearest_equals_monthly(self):
        assert _nearest_expiry_algorithmic("finnifty", self.FROM_DATE) == date(2026, 7, 28)

    def test_midcap_nifty_nearest_equals_monthly(self):
        assert _nearest_expiry_algorithmic("midcap_nifty", self.FROM_DATE) == date(2026, 7, 27)

    def test_bankex_nearest_equals_monthly(self):
        assert _nearest_expiry_algorithmic("bankex", self.FROM_DATE) == date(2026, 7, 30)

    def test_nifty_nearest_is_nearest_weekly_thursday(self):
        # NIFTY retains its weekly series — nearest Thursday from Sat 4-Jul-2026 is 9-Jul-2026
        assert _nearest_expiry_algorithmic("nifty", self.FROM_DATE) == date(2026, 7, 9)

    def test_sensex_nearest_is_nearest_weekly_thursday(self):
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
    """Sensex/Bankex live expiry must come from the same BSEOptionsService used
    by get_sensex_option_chain/get_bankex_option_chain — not a speculative
    INDmoney endpoint."""

    def test_bse_indices_use_bse_options_service(self, monkeypatch):
        from unittest.mock import MagicMock
        from src.market import calendar as cal_mod

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
