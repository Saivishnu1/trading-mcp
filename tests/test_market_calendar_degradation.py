"""Verify src/market/calendar.py's _live_expiries() provider-tier failures
are (a) non-fatal — the calendar still returns a usable result via the
algorithmic fallback — and (b) NOT silent — a WARNING or DEBUG log is
actually emitted and get_calendar_health() surfaces the failure via
expiry_errors, rather than being swallowed by a bare `except: pass`.

This is the test class the fix commit added alongside the except-block
remediation in src/market/calendar.py — see that file's _live_expiries()
and get_calendar_health() for the (source, error) tracking this exercises.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import pytest


class TestLiveExpiriesDegradation:
    def setup_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def teardown_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def test_all_tiers_failing_returns_empty_dict_not_raise(self, caplog):
        """If every live-expiry provider tier raises, _live_expiries() must
        still return (an empty dict), never propagate the exception --
        get_market_calendar() falls back to the algorithmic expiry
        calculation per-index when a symbol is missing from this dict."""
        from src.market import calendar as _cal

        with (
            patch("src.calendar.CalendarFetcher", side_effect=RuntimeError("zerodha down")),
            patch("src.options.service.get_options_service", side_effect=RuntimeError("nse down")),
            patch("src.options.bse_service.get_bse_options_service", side_effect=RuntimeError("bse down")),
            caplog.at_level(logging.DEBUG, logger="src.market.calendar"),
        ):
            result = _cal._live_expiries()

        assert result == {}

    def test_all_tiers_failing_is_logged_not_silent(self, caplog):
        """The core regression this guards against: a provider tier failure
        must produce a log record. Before this fix, all three tiers used
        `except Exception: pass` with no logging at all."""
        from src.market import calendar as _cal

        with (
            patch("src.calendar.CalendarFetcher", side_effect=RuntimeError("zerodha down")),
            patch("src.options.service.get_options_service", side_effect=RuntimeError("nse down")),
            patch("src.options.bse_service.get_bse_options_service", side_effect=RuntimeError("bse down")),
            caplog.at_level(logging.DEBUG, logger="src.market.calendar"),
        ):
            _cal._live_expiries()

        messages = [r.message for r in caplog.records]
        assert any("zerodha" in m.lower() or "nse" in m.lower() or "bse" in m.lower()
                   for m in messages), (
            f"expected at least one log record naming the failing provider, got: {messages}"
        )

    def test_tier_failure_recorded_in_expiry_source_errors(self):
        """NSE and BSE tier failures (the two whole-tier `except Exception`
        blocks, not the per-index inner ones) must be appended to
        _expiry_source_errors so get_calendar_health() can report them."""
        from src.market import calendar as _cal

        with (
            patch("src.calendar.CalendarFetcher", side_effect=RuntimeError("zerodha down")),
            patch("src.options.service.get_options_service", side_effect=RuntimeError("nse down")),
            patch("src.options.bse_service.get_bse_options_service", side_effect=RuntimeError("bse down")),
        ):
            _cal._live_expiries()

        sources = [s for s, _ in _cal._expiry_source_errors]
        assert "zerodha_csv" in sources
        assert "nse_chain" in sources
        assert "bse_chain" in sources

    def test_expiry_source_errors_reset_on_success(self):
        """A clean _live_expiries() call must clear stale errors from a
        previous failing call -- otherwise get_calendar_health() would keep
        reporting a degradation that has since recovered."""
        from src.market import calendar as _cal

        with patch("src.calendar.CalendarFetcher", side_effect=RuntimeError("zerodha down")):
            _cal._live_expiries()
        assert _cal._expiry_source_errors  # precondition: something recorded

        with (
            patch("src.calendar.CalendarFetcher", side_effect=RuntimeError("still down")),
            patch("src.options.service.get_options_service", side_effect=RuntimeError("still down")),
            patch("src.options.bse_service.get_bse_options_service", side_effect=RuntimeError("still down")),
        ):
            _cal._live_expiries()
        # still 3 errors (one per tier), not accumulating across calls
        assert len(_cal._expiry_source_errors) == 3

    def test_per_index_failure_does_not_abort_the_tier(self):
        """A single index raising inside the NSE-tier loop (e.g. NIFTY's
        get_option_chain call fails) must not prevent other indices in the
        same tier from being attempted -- this is the inner per-index
        except, distinct from the outer whole-tier except tested above."""
        from src.market import calendar as _cal

        call_count = {"n": 0}

        def flaky_get_option_chain(symbol):
            call_count["n"] += 1
            if symbol == "NIFTY":
                raise RuntimeError("nifty chain unavailable")
            return {"records": {"expiryDates": ["25-Dec-2026"]}}

        mock_svc = type("Svc", (), {"get_option_chain": staticmethod(flaky_get_option_chain)})()

        with (
            patch("src.calendar.CalendarFetcher", side_effect=RuntimeError("skip zerodha tier")),
            patch("src.options.service.get_options_service", return_value=mock_svc),
            patch("src.options.bse_service.get_bse_options_service", side_effect=RuntimeError("skip bse")),
        ):
            result = _cal._live_expiries()

        # NIFTY failed but BANKNIFTY/FINNIFTY/MIDCPNIFTY should still have
        # been attempted (proving the loop wasn't aborted by NIFTY's error).
        assert call_count["n"] == 4
        assert "nifty" not in result
        assert result.get("banknifty") == "25-Dec-2026"


class TestGetCalendarHealthExpiryErrors:
    def setup_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def teardown_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def test_expiry_errors_present_and_empty_by_default(self):
        from src.market.calendar import get_calendar_health
        h = get_calendar_health()
        assert "expiry_errors" in h
        assert h["expiry_errors"] == []

    def test_expiry_errors_reflects_last_live_expiries_call(self):
        from src.market import calendar as _cal
        from src.market.calendar import get_calendar_health

        with patch("src.calendar.CalendarFetcher", side_effect=RuntimeError("zerodha down")):
            _cal._live_expiries()

        h = get_calendar_health()
        assert any(source == "zerodha_csv" for source, _ in h["expiry_errors"])
