"""Priority 3 — Data Freshness Validation: refusal, not just a caution.

Finding (survey): every existing staleness mechanism in this codebase
(_data_basis/_staleness_days, meta.py's DQ_STALE, recommend_trade's caution)
only ever degrades gracefully — nothing anywhere refuses to hand back stale
data. This is the first place that does, scoped to the Timeframe Engine.

FR-1  EXECUTION-role stale candle (beyond interval-scaled threshold) is refused with an error
FR-2  FINE_ENTRY-role stale candle is also refused (same rule as EXECUTION)
FR-3  CONTEXT-role stale candle is NOT refused — degrades to a staleness_caution field instead
FR-4  fresh candle within threshold is never refused nor cautioned, for any role
FR-5  intraday and EOD thresholds are scaled differently (2h stale for 5minute, fine for day)
FR-6  a candle with no timestamp at all is not refused (can't measure an unknown age)
FR-7  generate_trade_setup_tf propagates the engine's stale refusal unchanged
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.analysis.regime import generate_trade_setup_tf
from src.timeframe.engine import get_technicals
from src.timeframe.policy import HoldingHorizon


def _daily_technicals(days_old: int) -> dict:
    stale_date = (datetime.now(timezone.utc).date() - timedelta(days=days_old)).isoformat()
    return {
        "symbol": "NIFTY", "last_close": 100.0, "candles_used": 150,
        "data_source": "yfinance_eod_adjusted", "last_candle_date": stale_date,
        "rsi_14": 55.0, "ema_20": 99.0, "ema_50": 95.0,
        "macd": {"macd": 0.1, "signal": 0.05, "histogram": 0.05},
        "adx_14": {"adx": 20.0, "plus_di": 18.0, "minus_di": 15.0},
        "atr_14": 2.0,
    }


def _intraday_candles(minutes_old: int, count: int = 30) -> list[dict]:
    base = datetime.now(timezone.utc) - timedelta(minutes=minutes_old)
    return [
        {"datetime": (base - timedelta(minutes=count - i)).strftime("%Y-%m-%d %H:%M:%S"),
         "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000}
        for i in range(count)
    ]


class TestFR1ExecutionStaleRefused:
    def test_swing_daily_stale_by_10_days_refused(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": _daily_technicals(10))
        result = get_technicals("NIFTY", HoldingHorizon.SWING, "day")
        assert "error" in result
        assert "stale" in result["error"].lower()
        assert result["role"] == "EXECUTION"

    @pytest.mark.anyio
    async def test_15minute_stale_by_2_hours_refused(self):
        candles = _intraday_candles(minutes_old=120)
        with patch("src.chart_awareness.engine.fetch_candles", new=AsyncMock(return_value=(candles, "yahoo"))):
            result = get_technicals("NIFTY", HoldingHorizon.INTRADAY_OPTIONS, "15minute")
        assert "error" in result
        assert "stale" in result["error"].lower()


class TestFR2FineEntryStaleRefused:
    @pytest.mark.anyio
    async def test_1minute_stale_refused(self):
        candles = _intraday_candles(minutes_old=120)
        with patch("src.chart_awareness.engine.fetch_candles", new=AsyncMock(return_value=(candles, "yahoo"))):
            result = get_technicals("NIFTY", HoldingHorizon.INTRADAY_OPTIONS, "1minute")
        assert "error" in result
        assert result["role"] == "FINE_ENTRY"


class TestFR3ContextStaleCautionsNotRefuses:
    def test_intraday_options_daily_context_stale_still_returns_data(self, monkeypatch):
        # day is CONTEXT-role under INTRADAY_OPTIONS; 10-day-old daily data
        # is stale by the EOD threshold too, but CONTEXT must not refuse.
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": _daily_technicals(10))
        result = get_technicals("NIFTY", HoldingHorizon.INTRADAY_OPTIONS, "day")
        assert "error" not in result
        assert result["role"] == "CONTEXT"
        assert "staleness_caution" in result
        assert "stale" in result["staleness_caution"].lower() or "CONTEXT" in result["staleness_caution"]

    def test_context_result_still_has_real_indicator_values(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": _daily_technicals(10))
        result = get_technicals("NIFTY", HoldingHorizon.INTRADAY_OPTIONS, "day")
        assert result["rsi_14"] == 55.0


class TestFR4FreshDataNeverFlagged:
    def test_fresh_daily_execution_no_error_no_caution(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": _daily_technicals(0))
        result = get_technicals("NIFTY", HoldingHorizon.SWING, "day")
        assert "error" not in result
        assert "staleness_caution" not in result

    @pytest.mark.anyio
    async def test_fresh_intraday_execution_no_error(self):
        candles = _intraday_candles(minutes_old=1)
        with patch("src.chart_awareness.engine.fetch_candles", new=AsyncMock(return_value=(candles, "yahoo"))):
            result = get_technicals("NIFTY", HoldingHorizon.INTRADAY_OPTIONS, "15minute")
        assert "error" not in result


class TestFR5ThresholdsScaleByInterval:
    @pytest.mark.anyio
    async def test_2_hour_old_5minute_candle_is_stale(self):
        candles = _intraday_candles(minutes_old=120)
        with patch("src.chart_awareness.engine.fetch_candles", new=AsyncMock(return_value=(candles, "yahoo"))):
            result = get_technicals("NIFTY", HoldingHorizon.INTRADAY_OPTIONS, "5minute")
        assert "error" in result

    def test_2_hour_old_daily_candle_is_not_stale(self, monkeypatch):
        # 2 hours is nothing for an EOD candle (5-day threshold).
        stale_ts = (datetime.now(timezone.utc) - timedelta(hours=2))
        tech = _daily_technicals(0)
        tech["last_candle_date"] = stale_ts.date().isoformat()
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": tech)
        result = get_technicals("NIFTY", HoldingHorizon.SWING, "day")
        assert "error" not in result


class TestFR6MissingTimestampNotRefused:
    def test_no_last_candle_date_not_refused(self, monkeypatch):
        tech = _daily_technicals(0)
        tech["last_candle_date"] = None
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": tech)
        result = get_technicals("NIFTY", HoldingHorizon.SWING, "day")
        assert "error" not in result


class TestFR7GenerateTradeSetupTfPropagatesRefusal:
    def test_stale_execution_setup_refused(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": _daily_technicals(10))
        result = generate_trade_setup_tf("NIFTY", "SWING", "day")
        assert "error" in result
        assert "stale" in result["error"].lower()
        assert "signal" not in result
