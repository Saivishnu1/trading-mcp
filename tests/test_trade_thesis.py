"""Priority 6 — Trade Thesis Engine regression tests.

TT-1  thesis_because mirrors evidence_for's text for a bullish setup
TT-2  direction is LONG for BUY/NEUTRAL_BULLISH, SHORT for SELL/NEUTRAL_BEARISH, NONE for NEUTRAL
TT-3  bullish invalidation conditions reference EMA20/EMA50 closing BELOW (the failure direction)
TT-4  bearish invalidation conditions reference EMA20/EMA50 closing ABOVE (the failure direction)
TT-5  invalidation always includes a premium/price stop and a time stop, regardless of direction
TT-6  NEUTRAL signal produces a no-thesis invalidation line, not fabricated directional conditions
TT-7  missing ema_20/ema_50 in technicals doesn't crash — those lines are simply omitted
TT-8  generate_trade_setup_tf's output includes a thesis with both halves populated
TT-9  generate_trade_setup (daily-only, unchanged) has no thesis key
"""
from __future__ import annotations

from datetime import UTC, datetime, timezone

from src.analysis.regime import generate_trade_setup, generate_trade_setup_tf
from src.timeframe.thesis import build_trade_thesis


def _fresh_daily_date() -> str:
    return datetime.now(UTC).date().isoformat()


def _setup(signal: str, evidence_for=None) -> dict:
    return {
        "signal": signal,
        "evidence_for": evidence_for if evidence_for is not None else [
            {"indicator": "rsi", "text": "RSI bullish", "points": 20},
        ],
    }


def _technicals(ema20=95.0, ema50=90.0, rsi=65.0) -> dict:
    return {"ema_20": ema20, "ema_50": ema50, "rsi_14": rsi}


class TestTT1ThesisBecauseMirrorsEvidenceFor:
    def test_thesis_because_matches_evidence_for_text(self):
        setup = _setup("BUY", evidence_for=[
            {"indicator": "rsi", "text": "RSI bullish", "points": 20},
            {"indicator": "ema_20", "text": "Above EMA20", "points": 15},
        ])
        thesis = build_trade_thesis(setup, _technicals())
        assert thesis["thesis_because"] == ["RSI bullish", "Above EMA20"]


class TestTT2DirectionMapping:
    def test_buy_is_long(self):
        assert build_trade_thesis(_setup("BUY"), _technicals())["direction"] == "LONG"

    def test_neutral_bullish_is_long(self):
        assert build_trade_thesis(_setup("NEUTRAL_BULLISH"), _technicals())["direction"] == "LONG"

    def test_sell_is_short(self):
        assert build_trade_thesis(_setup("SELL"), _technicals())["direction"] == "SHORT"

    def test_neutral_bearish_is_short(self):
        assert build_trade_thesis(_setup("NEUTRAL_BEARISH"), _technicals())["direction"] == "SHORT"

    def test_neutral_is_none(self):
        assert build_trade_thesis(_setup("NEUTRAL"), _technicals())["direction"] == "NONE"


class TestTT3BullishInvalidationDirection:
    def test_invalidation_mentions_closes_below(self):
        thesis = build_trade_thesis(_setup("BUY"), _technicals(ema20=95.0, ema50=90.0))
        joined = " ".join(thesis["invalidation_conditions"])
        assert "below EMA20 (95.00)" in joined
        assert "below EMA50 (90.00)" in joined
        assert "RSI drops below 45" in joined


class TestTT4BearishInvalidationDirection:
    def test_invalidation_mentions_closes_above(self):
        thesis = build_trade_thesis(_setup("SELL"), _technicals(ema20=95.0, ema50=90.0))
        joined = " ".join(thesis["invalidation_conditions"])
        assert "above EMA20 (95.00)" in joined
        assert "above EMA50 (90.00)" in joined
        assert "RSI rises above 55" in joined


class TestTT5UniversalStopsAlwaysPresent:
    def test_premium_and_time_stop_present_for_long(self):
        thesis = build_trade_thesis(_setup("BUY"), _technicals())
        joined = " ".join(thesis["invalidation_conditions"]).lower()
        assert "premium/price stop" in joined
        assert "time stop" in joined

    def test_premium_and_time_stop_present_for_short(self):
        thesis = build_trade_thesis(_setup("SELL"), _technicals())
        joined = " ".join(thesis["invalidation_conditions"]).lower()
        assert "premium/price stop" in joined
        assert "time stop" in joined


class TestTT6NeutralSignalNoFabricatedDirection:
    def test_neutral_has_no_thesis_line(self):
        thesis = build_trade_thesis(_setup("NEUTRAL"), _technicals())
        assert any("no directional thesis" in c.lower() for c in thesis["invalidation_conditions"])
        assert not any("EMA20" in c for c in thesis["invalidation_conditions"])


class TestTT7MissingTechnicalsDoesNotCrash:
    def test_missing_ema_fields_omit_those_lines_not_crash(self):
        thesis = build_trade_thesis(_setup("BUY"), {"rsi_14": 65.0})
        assert not any("EMA20" in c for c in thesis["invalidation_conditions"])
        assert not any("EMA50" in c for c in thesis["invalidation_conditions"])
        assert any("RSI drops below 45" in c for c in thesis["invalidation_conditions"])


class TestTT8GenerateTradeSetupTfIncludesThesis:
    def test_thesis_present_with_both_halves(self, monkeypatch):
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
        assert "thesis" in result
        assert result["thesis"]["direction"] == "LONG"
        assert len(result["thesis"]["thesis_because"]) > 0
        assert len(result["thesis"]["invalidation_conditions"]) > 0


class TestTT9DailyOnlyFunctionHasNoThesis:
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
        assert "thesis" not in result
