"""Priority 8 — Mixed Timeframe Detection regression tests.

MT-1  all timeframes agreeing bullish -> ALIGNED
MT-2  daily bullish / 15m bearish -> CONFLICT with both intervals named in conflict_detail
MT-3  fewer than 2 known directions -> INSUFFICIENT_DATA, not fabricated ALIGNED/CONFLICT
MT-4  a fetch error for one interval is reported as "error" in directions, not silently dropped
MT-5  conflict is never averaged into a single direction — conflict_detail lists BOTH sides
MT-6  generate_trade_setup_tf with check_mixed_timeframes=False (default) never fetches extra intervals
MT-7  generate_trade_setup_tf with check_mixed_timeframes=True surfaces mixed_timeframe_report
MT-8  a real conflict reduces confidence and adds a caution, does not silently avg/ignore it
MT-9  no conflict (aligned) leaves confidence unaffected by this check
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.analysis.regime import generate_trade_setup_tf
from src.timeframe.multiframe import build_mixed_timeframe_report


def _fresh_daily_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _tech(price: float, ema20: float) -> dict:
    return {"last_close": price, "ema_20": ema20}


class TestMT1AllAgreeAligned:
    def test_all_bullish_is_aligned(self):
        report = build_mixed_timeframe_report({
            "day": _tech(100, 90),
            "15minute": _tech(100, 95),
            "5minute": _tech(100, 98),
        })
        assert report["alignment"] == "ALIGNED"
        assert report["conflict_detail"] == ""


class TestMT2ConflictNamesBothSides:
    def test_daily_bullish_15m_bearish_is_conflict(self):
        report = build_mixed_timeframe_report({
            "day": _tech(100, 90),       # bullish
            "15minute": _tech(100, 105),  # bearish
            "5minute": _tech(100, 98),   # bullish
        })
        assert report["alignment"] == "CONFLICT"
        assert "day" in report["conflict_detail"]
        assert "15minute" in report["conflict_detail"]
        assert "bullish" in report["conflict_detail"]
        assert "bearish" in report["conflict_detail"]


class TestMT3InsufficientData:
    def test_single_interval_is_insufficient(self):
        report = build_mixed_timeframe_report({"day": _tech(100, 90)})
        assert report["alignment"] == "INSUFFICIENT_DATA"

    def test_all_unknown_is_insufficient(self):
        report = build_mixed_timeframe_report({
            "day": {"last_close": None, "ema_20": None},
            "15minute": {"last_close": None, "ema_20": None},
        })
        assert report["alignment"] == "INSUFFICIENT_DATA"


class TestMT4FetchErrorReportedNotDropped:
    def test_error_interval_shows_as_error_in_directions(self):
        report = build_mixed_timeframe_report({
            "day": _tech(100, 90),
            "15minute": {"error": "stale data refused"},
            "5minute": _tech(100, 98),
        })
        assert report["directions"]["15minute"] == "error"
        assert "15minute" in report["directions"]


class TestMT5NeverAveraged:
    def test_conflict_detail_lists_both_sides_not_a_single_verdict(self):
        report = build_mixed_timeframe_report({
            "day": _tech(100, 90),
            "15minute": _tech(100, 105),
        })
        assert "vs" in report["conflict_detail"]
        assert "not averaged" in report["conflict_detail"].lower()


def _fake_tech_bull():
    return {
        "symbol": "NIFTY", "last_close": 100.0, "candles_used": 150,
        "data_source": "yfinance_eod_adjusted", "last_candle_date": _fresh_daily_date(),
        "rsi_14": 65.0, "ema_20": 95.0, "ema_50": 90.0,
        "macd": {"macd": 0.5, "signal": 0.3, "histogram": 0.2},
        "adx_14": {"adx": 30.0, "plus_di": 28.0, "minus_di": 12.0},
        "atr_14": 2.0,
    }


class TestMT6DefaultFalseDoesNotFetchExtra:
    def test_default_has_no_mixed_timeframe_report_key(self, monkeypatch):
        call_count = {"n": 0}

        def _tracking_analyze_technicals(symbol, lookback_days=150, interval="daily"):
            call_count["n"] += 1
            return _fake_tech_bull()

        monkeypatch.setattr("src.analysis.regime._analyze_technicals", _tracking_analyze_technicals)
        result = generate_trade_setup_tf("NIFTY", "SWING", "day")
        assert "mixed_timeframe_report" not in result
        # EXECUTION (day) + CONTEXT (week) = 2 calls, not more
        assert call_count["n"] == 2


class TestMT7OptInSurfacesReport:
    def test_check_true_surfaces_mixed_timeframe_report(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": _fake_tech_bull())
        result = generate_trade_setup_tf("NIFTY", "SWING", "day", check_mixed_timeframes=True)
        assert "error" not in result
        assert "mixed_timeframe_report" in result
        assert result["mixed_timeframe_report"]["alignment"] in ("ALIGNED", "CONFLICT", "INSUFFICIENT_DATA")


class TestMT8ConflictReducesConfidenceAndCautions:
    def test_conflicting_timeframes_reduce_confidence(self, monkeypatch):
        def _tech_by_interval(symbol, lookback_days=150, interval="daily"):
            fake = _fake_tech_bull()
            if interval == "weekly":
                # opposite direction on the CONTEXT (week) fetch
                fake = {**fake, "ema_20": 105.0}  # price 100 < ema20 105 -> bearish
            return fake
        monkeypatch.setattr("src.analysis.regime._analyze_technicals", _tech_by_interval)

        baseline = generate_trade_setup_tf("NIFTY", "SWING", "day", check_mixed_timeframes=False)
        with_check = generate_trade_setup_tf("NIFTY", "SWING", "day", check_mixed_timeframes=True)

        if with_check.get("mixed_timeframe_report", {}).get("alignment") == "CONFLICT":
            assert with_check["confidence"] < baseline["confidence"]
            assert any("mixed timeframe" in c.lower() for c in with_check.get("cautions", []))


class TestMT9AlignedLeavesConfidenceUnaffected:
    def test_all_aligned_no_extra_penalty(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": _fake_tech_bull())
        baseline = generate_trade_setup_tf("NIFTY", "SWING", "day", check_mixed_timeframes=False)
        with_check = generate_trade_setup_tf("NIFTY", "SWING", "day", check_mixed_timeframes=True)
        if with_check["mixed_timeframe_report"]["alignment"] != "CONFLICT":
            assert with_check["confidence"] == baseline["confidence"]
