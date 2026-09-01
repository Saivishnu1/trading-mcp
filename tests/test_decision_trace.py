"""Priority 5 — Decision Trace regression tests.

DT-1  all 10 required trace fields present
DT-2  indicators_used only includes indicators with a real (non-None) value
DT-3  indicators_rejected includes indicators whose value was None
DT-4  evidence/counter_evidence mirror evidence_for/evidence_against from the setup
DT-5  data_quality is VALID when nothing is stale/unknown/rejected
DT-6  data_quality is DEGRADED when any indicator's freshness is STALE or UNKNOWN
DT-7  data_quality is PARTIAL when indicators are rejected but none are stale
DT-8  assumptions flags missing context and any rejected context sources
DT-9  generate_trade_setup_tf's output includes decision_trace
DT-10 generate_trade_setup (daily-only, unchanged) has no decision_trace key
"""
from __future__ import annotations

from datetime import UTC, datetime, timezone

from src.analysis.regime import generate_trade_setup, generate_trade_setup_tf
from src.timeframe.trace import build_decision_trace


def _fresh_daily_date() -> str:
    return datetime.now(UTC).date().isoformat()


def _sample_setup(**overrides) -> dict:
    base = {
        "horizon": "SWING",
        "interval": "day",
        "role": "EXECUTION",
        "signal": "BUY",
        "confidence": 74,
        "data_basis": {
            "last_candle_datetime": "2026-07-27 15:30:00",
            "last_candle_date": "2026-07-27",
            "staleness_days": 0,
        },
        "indicator_metadata": [
            {"indicator": "rsi", "value": 65.0, "timeframe": "day", "freshness": "LIVE"},
            {"indicator": "ema_20", "value": 95.0, "timeframe": "day", "freshness": "LIVE"},
            {"indicator": "adx", "value": None, "timeframe": "day", "freshness": "UNKNOWN"},
        ],
        "evidence_for": [{"indicator": "rsi", "text": "RSI bullish", "points": 20}],
        "evidence_against": [],
        "ignored": [],
        "context": ["week: RSI 55"],
        "rejected": [],
    }
    base.update(overrides)
    return base


class TestDT1AllFieldsPresent:
    def test_all_ten_fields_present(self):
        trace = build_decision_trace(_sample_setup())
        for field in ("trade_type", "recommendation", "confidence", "indicators_used",
                      "indicators_rejected", "timeframes", "data_timestamps",
                      "evidence", "counter_evidence", "assumptions", "data_quality"):
            assert field in trace


class TestDT2IndicatorsUsedExcludesNone:
    def test_only_real_values_in_used(self):
        trace = build_decision_trace(_sample_setup())
        used_names = {i["indicator"] for i in trace["indicators_used"]}
        assert "rsi" in used_names
        assert "ema_20" in used_names
        assert "adx" not in used_names


class TestDT3IndicatorsRejectedIncludesNone:
    def test_none_value_indicator_is_rejected(self):
        trace = build_decision_trace(_sample_setup())
        rejected_names = {i["indicator"] for i in trace["indicators_rejected"]}
        assert "adx" in rejected_names


class TestDT4EvidenceMirrorsSetup:
    def test_evidence_matches_evidence_for(self):
        setup = _sample_setup()
        trace = build_decision_trace(setup)
        assert trace["evidence"] == setup["evidence_for"]

    def test_counter_evidence_matches_evidence_against(self):
        setup = _sample_setup(evidence_against=[{"indicator": "ema_50", "text": "below EMA50", "points": 15}])
        trace = build_decision_trace(setup)
        assert trace["counter_evidence"] == setup["evidence_against"]


class TestDT5DataQualityValid:
    def test_valid_when_nothing_stale_or_rejected(self):
        setup = _sample_setup(indicator_metadata=[
            {"indicator": "rsi", "value": 65.0, "timeframe": "day", "freshness": "LIVE"},
        ])
        trace = build_decision_trace(setup)
        assert trace["data_quality"] == "VALID"


class TestDT6DataQualityDegraded:
    def test_degraded_when_stale_present(self):
        setup = _sample_setup(indicator_metadata=[
            {"indicator": "rsi", "value": 65.0, "timeframe": "day", "freshness": "STALE"},
        ])
        trace = build_decision_trace(setup)
        assert trace["data_quality"] == "DEGRADED"

    def test_degraded_when_unknown_present(self):
        # default sample has an UNKNOWN-freshness rejected indicator
        trace = build_decision_trace(_sample_setup())
        assert trace["data_quality"] == "DEGRADED"


class TestDT7DataQualityPartial:
    def test_partial_when_rejected_but_not_stale(self):
        setup = _sample_setup(indicator_metadata=[
            {"indicator": "rsi", "value": 65.0, "timeframe": "day", "freshness": "LIVE"},
            {"indicator": "adx", "value": None, "timeframe": "day", "freshness": "LIVE"},
        ])
        trace = build_decision_trace(setup)
        assert trace["data_quality"] == "PARTIAL"


class TestDT8AssumptionsFlagGaps:
    def test_no_context_flagged(self):
        setup = _sample_setup(context=[])
        trace = build_decision_trace(setup)
        assert any("no usable context" in a.lower() for a in trace["assumptions"])

    def test_rejected_sources_flagged(self):
        setup = _sample_setup(rejected=["stale data refused: interval='week'"])
        trace = build_decision_trace(setup)
        assert any("rejected" in a.lower() for a in trace["assumptions"])

    def test_has_context_and_no_rejections_still_has_base_assumption(self):
        trace = build_decision_trace(_sample_setup())
        assert len(trace["assumptions"]) >= 1


class TestDT9GenerateTradeSetupTfIncludesTrace:
    def test_execution_setup_has_decision_trace(self, monkeypatch):
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
        assert "decision_trace" in result
        trace = result["decision_trace"]
        assert trace["recommendation"] == result["signal"]
        assert trace["confidence"] == result["confidence"]
        assert trace["trade_type"] == "SWING"


class TestDT10DailyOnlyFunctionHasNoTrace:
    def test_generate_trade_setup_unaffected(self, monkeypatch):
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
        result = generate_trade_setup("NIFTY")
        assert "error" not in result
        assert "decision_trace" not in result
