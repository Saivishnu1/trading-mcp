"""Priority 2 — per-indicator metadata envelope regression tests.

IM-1  build_indicator_metadata returns all 8 required fields
IM-2  confidence is explicitly None for pure indicators (present key, null value)
IM-3  calculation_period is correct per indicator (rsi=14, adx=14, atr=14)
IM-4  macd carries calculation_detail with full (fast,slow,signal) triple
IM-5  freshness LIVE/RECENT/STALE/UNKNOWN classification is correct
IM-6  intraday intervals use a much tighter staleness threshold than daily
IM-7  build_indicator_metadata_list produces one entry per indicator, from a real technicals dict
IM-8  get_technicals() (Timeframe Engine) output includes indicator_metadata additively
IM-9  generate_trade_setup_tf's output includes indicator_metadata
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from src.timeframe.metadata import (
    build_indicator_metadata,
    build_indicator_metadata_list,
)


def _fresh_daily_date() -> str:
    from datetime import datetime
    return datetime.now(UTC).date().isoformat()


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class TestIM1AllFieldsPresent:
    def test_all_eight_fields_present(self):
        entry = build_indicator_metadata(
            "rsi", 55.0, timeframe="day", candle_timestamp="2026-07-22 15:30:00", source="yahoo",
        )
        for field in ("indicator", "value", "timeframe", "candle_timestamp",
                      "source", "freshness", "confidence", "calculation_period"):
            assert field in entry


class TestIM2ConfidenceExplicitlyNone:
    def test_confidence_key_present_and_none(self):
        entry = build_indicator_metadata(
            "adx", 28.4, timeframe="15minute", candle_timestamp="2026-07-22 09:45:00", source="indmoney",
        )
        assert "confidence" in entry
        assert entry["confidence"] is None


class TestIM3CalculationPeriodCorrect:
    def test_rsi_period_14(self):
        entry = build_indicator_metadata("rsi", 50.0, timeframe="day", candle_timestamp=None, source=None)
        assert entry["calculation_period"] == 14

    def test_adx_period_14(self):
        entry = build_indicator_metadata("adx", 25.0, timeframe="day", candle_timestamp=None, source=None)
        assert entry["calculation_period"] == 14

    def test_atr_period_14(self):
        entry = build_indicator_metadata("atr", 2.0, timeframe="day", candle_timestamp=None, source=None)
        assert entry["calculation_period"] == 14

    def test_unknown_indicator_period_none(self):
        entry = build_indicator_metadata("something_new", 1.0, timeframe="day", candle_timestamp=None, source=None)
        assert entry["calculation_period"] is None


class TestIM4MacdCalculationDetail:
    def test_macd_has_full_triple_detail(self):
        entry = build_indicator_metadata("macd", 0.5, timeframe="day", candle_timestamp=None, source=None)
        assert "calculation_detail" in entry
        assert "12" in entry["calculation_detail"]
        assert "26" in entry["calculation_detail"]
        assert "9" in entry["calculation_detail"]

    def test_non_macd_has_no_calculation_detail(self):
        entry = build_indicator_metadata("rsi", 50.0, timeframe="day", candle_timestamp=None, source=None)
        assert "calculation_detail" not in entry


class TestIM5FreshnessClassification:
    def test_live_when_under_60_seconds(self):
        ts = _iso(datetime.now(UTC) - timedelta(seconds=10))
        entry = build_indicator_metadata("rsi", 50.0, timeframe="5minute", candle_timestamp=ts, source="yahoo")
        assert entry["freshness"] == "LIVE"

    def test_recent_when_within_intraday_threshold(self):
        ts = _iso(datetime.now(UTC) - timedelta(seconds=120))
        entry = build_indicator_metadata("rsi", 50.0, timeframe="5minute", candle_timestamp=ts, source="yahoo")
        assert entry["freshness"] == "RECENT"

    def test_stale_when_beyond_intraday_threshold(self):
        ts = _iso(datetime.now(UTC) - timedelta(seconds=600))
        entry = build_indicator_metadata("rsi", 50.0, timeframe="5minute", candle_timestamp=ts, source="yahoo")
        assert entry["freshness"] == "STALE"

    def test_unknown_when_timestamp_missing(self):
        entry = build_indicator_metadata("rsi", 50.0, timeframe="day", candle_timestamp=None, source="yahoo")
        assert entry["freshness"] == "UNKNOWN"

    def test_unknown_when_timestamp_unparseable(self):
        entry = build_indicator_metadata("rsi", 50.0, timeframe="day", candle_timestamp="not-a-date", source="yahoo")
        assert entry["freshness"] == "UNKNOWN"


class TestIM6IntradayVsEodStaleThreshold:
    def test_daily_candle_2_hours_old_is_not_stale(self):
        # 2 hours is normal mid-session for a daily candle; would be very
        # stale for a 5-minute one.
        ts = _iso(datetime.now(UTC) - timedelta(hours=2))
        entry = build_indicator_metadata("rsi", 50.0, timeframe="day", candle_timestamp=ts, source="yahoo")
        assert entry["freshness"] != "STALE"

    def test_5minute_candle_2_hours_old_is_stale(self):
        ts = _iso(datetime.now(UTC) - timedelta(hours=2))
        entry = build_indicator_metadata("rsi", 50.0, timeframe="5minute", candle_timestamp=ts, source="yahoo")
        assert entry["freshness"] == "STALE"


class TestIM7BuildListFromTechnicals:
    def _technicals(self):
        return {
            "interval": "day",
            "last_candle_date": _fresh_daily_date(),
            "last_candle_datetime": "2026-07-22",
            "data_source": "yfinance_eod_adjusted",
            "rsi_14": 65.0,
            "ema_20": 95.0,
            "ema_50": 90.0,
            "macd": {"macd": 0.5, "signal": 0.3, "histogram": 0.2},
            "adx_14": {"adx": 30.0},
            "atr_14": 2.0,
        }

    def test_six_indicators_present(self):
        entries = build_indicator_metadata_list(self._technicals())
        names = {e["indicator"] for e in entries}
        assert names == {"rsi", "ema_20", "ema_50", "macd", "adx", "atr"}

    def test_values_match_source_technicals(self):
        entries = build_indicator_metadata_list(self._technicals())
        by_name = {e["indicator"]: e for e in entries}
        assert by_name["rsi"]["value"] == 65.0
        assert by_name["adx"]["value"] == 30.0
        assert by_name["macd"]["value"] == 0.5

    def test_all_entries_share_the_same_timeframe_and_source(self):
        entries = build_indicator_metadata_list(self._technicals())
        assert all(e["timeframe"] == "day" for e in entries)
        assert all(e["source"] == "yfinance_eod_adjusted" for e in entries)

    def test_missing_indicator_value_still_gets_an_entry(self):
        tech = self._technicals()
        tech["rsi_14"] = None
        entries = build_indicator_metadata_list(tech)
        rsi_entry = next(e for e in entries if e["indicator"] == "rsi")
        assert rsi_entry["value"] is None
        assert "calculation_period" in rsi_entry


class TestIM8TimeframeEngineIncludesMetadata:
    def test_daily_execution_result_has_indicator_metadata(self, monkeypatch):
        from src.timeframe.engine import get_technicals
        from src.timeframe.policy import HoldingHorizon

        fake = {
            "symbol": "NIFTY", "last_close": 100.0, "candles_used": 150,
            "data_source": "yfinance_eod_adjusted", "last_candle_date": _fresh_daily_date(),
            "rsi_14": 55.0, "ema_20": 99.0, "ema_50": 95.0,
            "macd": {"macd": 0.1, "signal": 0.05, "histogram": 0.05},
            "adx_14": {"adx": 20.0, "plus_di": 18.0, "minus_di": 15.0},
            "atr_14": 2.0,
        }
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": fake)
        result = get_technicals("NIFTY", HoldingHorizon.SWING, "day")
        assert "indicator_metadata" in result
        assert len(result["indicator_metadata"]) == 6


class TestIM9GenerateTradeSetupTfIncludesMetadata:
    def test_execution_setup_has_indicator_metadata(self, monkeypatch):
        from src.analysis.regime import generate_trade_setup_tf

        fake = {
            "symbol": "NIFTY", "last_close": 100.0, "candles_used": 150,
            "data_source": "yfinance_eod_adjusted", "last_candle_date": _fresh_daily_date(),
            "rsi_14": 65.0, "ema_20": 95.0, "ema_50": 90.0,
            "macd": {"macd": 0.5, "signal": 0.3, "histogram": 0.2},
            "adx_14": {"adx": 30.0, "plus_di": 28.0, "minus_di": 12.0},
            "atr_14": 2.0,
        }
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": fake)
        result = generate_trade_setup_tf("NIFTY", "SWING", "day")
        assert "error" not in result
        assert "indicator_metadata" in result
        assert len(result["indicator_metadata"]) == 6
