"""Priority 10 — Regression test matrix for the phase brief's explicit list.

Most items in the brief's list (wrong timeframe, daily-for-intraday, stale
candle, mixed timeframe, missing metadata, failed broker response,
conflicting signals) already have dedicated coverage in earlier priorities'
test files — see the cross-reference in each class docstring below. This
file closes the remaining gaps: holiday, market-closed, missing options
chain, missing IV, and incorrect/corrupt timestamps, framed explicitly as
the scenarios the brief names rather than left implicit inside other
tests.

Holiday and market-closed are NOT separately modeled anywhere in the
Timeframe Engine — there is no market-calendar/holiday check in
src.timeframe.engine or generate_trade_setup_tf at all (confirmed: no
reference to src.market.calendar anywhere in src/timeframe/). The
mechanism that actually protects against acting on stale post-holiday/
closed-market data is Priority 3's freshness refusal: on a real holiday or
after market close, the most recent candle is simply older than the
EXECUTION-role staleness threshold, and the SAME refusal path already
tested in test_freshness_refusal.py fires. These tests model that exact
scenario (a candle timestamped days before "now", as a holiday/closed
market would actually produce) rather than inventing a parallel calendar
check that would duplicate src/market/calendar.py's own logic.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from src.analysis.regime import generate_trade_setup_tf
from src.timeframe.engine import get_technicals
from src.timeframe.layers import attach_options_layer
from src.timeframe.policy import HoldingHorizon


def _daily_technicals(as_of_date: str) -> dict:
    return {
        "symbol": "NIFTY", "last_close": 100.0, "candles_used": 150,
        "data_source": "yfinance_eod_adjusted", "last_candle_date": as_of_date,
        "rsi_14": 55.0, "ema_20": 95.0, "ema_50": 90.0,
        "macd": {"macd": 0.1, "signal": 0.05, "histogram": 0.05},
        "adx_14": {"adx": 20.0, "plus_di": 18.0, "minus_di": 15.0},
        "atr_14": 2.0,
    }


class TestP10HolidayScenario:
    """A 3-day holiday weekend (e.g. Friday close -> Tuesday reopen) leaves
    the most recent daily candle several calendar days old by the time a
    caller asks for an EXECUTION-role setup on the closed days. Priority 3's
    refusal (test_freshness_refusal.py FR-1) is the mechanism that actually
    catches this — verified here framed explicitly as the holiday scenario."""

    def test_stale_candle_across_a_holiday_gap_is_refused(self, monkeypatch):
        # A multi-day holiday closure (e.g. a festival block) leaving the
        # most recent daily candle beyond the 5-calendar-day EOD staleness
        # threshold (src.timeframe.metadata's _EOD_STALE_SECONDS).
        stale_date = (datetime.now(timezone.utc).date() - timedelta(days=10)).isoformat()
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": _daily_technicals(stale_date))
        result = generate_trade_setup_tf("NIFTY", "SWING", "day")
        assert "error" in result
        assert "stale" in result["error"].lower()


class TestP10MarketClosedScenario:
    """After-hours: the last EOD candle is from the prior session. For a
    SWING/POSITIONAL horizon (daily EXECUTION) this is normal and must NOT
    be refused — a daily candle is only ever updated once per session
    regardless of the current wall-clock time, so "market closed right
    now" is not itself a staleness problem for a daily-EXECUTION horizon."""

    def test_after_hours_same_day_candle_not_refused(self, monkeypatch):
        today = datetime.now(timezone.utc).date().isoformat()
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": _daily_technicals(today))
        result = generate_trade_setup_tf("NIFTY", "SWING", "day")
        assert "error" not in result

    def test_intraday_horizon_closed_market_stale_candle_is_refused(self):
        # For an INTRADAY_OPTIONS horizon, a candle from well before the
        # current session (e.g. market closed hours ago, last tick is old)
        # must be refused for the EXECUTION-role intraday interval.
        stale_candles = [
            {"datetime": (datetime.now(timezone.utc) - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S"),
             "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000}
        ]
        with patch("src.chart_awareness.engine.fetch_candles", return_value=(stale_candles, "yahoo")):
            result = get_technicals("NIFTY", HoldingHorizon.INTRADAY_OPTIONS, "5minute")
        assert "error" in result
        assert "stale" in result["error"].lower()


class TestP10MissingOptionsChain:
    """Brief's explicit scenario: 'Missing options chain'."""

    def test_no_chain_available_surfaces_as_unavailable_not_exception(self):
        with patch("src.options_awareness.engine.OptionsAwarenessEngine.analyze",
                   return_value={"symbol": "SOMESTOCK", "expiry": None,
                                 "error": "no option chain available for this symbol"}):
            result = attach_options_layer("SOMESTOCK")
        assert result["available"] is False
        assert "no option chain" in result["reason"].lower()


class TestP10MissingIv:
    """Brief's explicit scenario: 'Missing IV' / 'Stale IV'."""

    def test_missing_iv_fields_still_surface_available_true_with_none_iv(self):
        # The options engine succeeded (no error) but IV data itself is
        # absent for this expiry/strike — must not be silently dropped or
        # crash; atm_iv/iv_skew simply come through as None.
        with patch("src.options_awareness.engine.OptionsAwarenessEngine.analyze",
                   return_value={"symbol": "NIFTY", "expiry": "2026-07-31", "spot": 24000.0,
                                 "pcr": 1.0, "pcr_interpretation": "neutral",
                                 "max_pain": 24000.0, "distance_from_max_pain": 0.0,
                                 "iv": {"atm_iv": None, "iv_skew": None}}):
            result = attach_options_layer("NIFTY")
        assert result["available"] is True
        assert result["atm_iv"] is None
        assert result["iv_skew"] is None


class TestP10IncorrectTimestamps:
    """Brief's explicit scenario: 'Incorrect timestamps'."""

    def test_unparseable_timestamp_does_not_crash_and_is_not_treated_as_fresh(self, monkeypatch):
        bad_tech = _daily_technicals("not-a-real-date")
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": bad_tech)
        result = generate_trade_setup_tf("NIFTY", "SWING", "day")
        # Unparseable/unknown age must not be refused (can't measure it) but
        # also must never silently be reported as LIVE/fresh; verified via
        # the per-indicator metadata's freshness label.
        assert "error" not in result
        assert all(m["freshness"] == "UNKNOWN" for m in result["indicator_metadata"])

    def test_future_dated_candle_does_not_crash(self, monkeypatch):
        # A corrupt feed reporting a candle "from the future" — age would be
        # negative; must clamp to non-negative, not crash or refuse
        # spuriously due to a negative-duration computation.
        future_date = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": _daily_technicals(future_date))
        result = generate_trade_setup_tf("NIFTY", "SWING", "day")
        assert "error" not in result
