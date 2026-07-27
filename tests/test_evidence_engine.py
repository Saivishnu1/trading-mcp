"""Priority 4 — Recommendation Evidence Engine regression tests.

EV-1  build_evidence splits bullish-polarity lines into evidence_for for a BUY signal
EV-2  build_evidence splits bullish-polarity lines into evidence_against for a SELL signal
EV-3  neutral-polarity lines go to ignored regardless of signal
EV-4  build_context_summary produces context lines from a successful CONTEXT fetch
EV-5  build_context_summary produces rejected from a failed/refused CONTEXT fetch
EV-6  build_context_summary surfaces a CONTEXT staleness_caution as rejected
EV-7  generate_trade_setup_tf's output has evidence_for/evidence_against/ignored/context/rejected
EV-8  generate_trade_setup (daily-only, unchanged) has no evidence_for/context/rejected keys —
       Priority 4 is additive to the new _tf path only
EV-9  evidence_for is non-empty and evidence_against is empty for a strongly bullish setup
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.analysis.regime import generate_trade_setup, generate_trade_setup_tf
from src.timeframe.evidence import build_context_summary, build_evidence


def _fresh_daily_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


_SAMPLE_EVIDENCE = [
    {"indicator": "rsi", "polarity": "bullish", "points": 20, "text": "RSI bullish"},
    {"indicator": "ema_20", "polarity": "bearish", "points": 15, "text": "Below EMA20"},
    {"indicator": "adx", "polarity": "neutral", "points": 0, "text": "ADX inconclusive"},
]


class TestEV1BullishForBuySignal:
    def test_bullish_line_goes_to_evidence_for(self):
        split = build_evidence(_SAMPLE_EVIDENCE, "BUY")
        for_texts = [e["text"] for e in split["evidence_for"]]
        assert "RSI bullish" in for_texts

    def test_bearish_line_goes_to_evidence_against(self):
        split = build_evidence(_SAMPLE_EVIDENCE, "BUY")
        against_texts = [e["text"] for e in split["evidence_against"]]
        assert "Below EMA20" in against_texts


class TestEV2BullishAgainstForSellSignal:
    def test_bullish_line_goes_to_evidence_against(self):
        split = build_evidence(_SAMPLE_EVIDENCE, "SELL")
        against_texts = [e["text"] for e in split["evidence_against"]]
        assert "RSI bullish" in against_texts

    def test_bearish_line_goes_to_evidence_for(self):
        split = build_evidence(_SAMPLE_EVIDENCE, "SELL")
        for_texts = [e["text"] for e in split["evidence_for"]]
        assert "Below EMA20" in for_texts


class TestEV3NeutralAlwaysIgnored:
    def test_neutral_line_in_ignored_for_buy(self):
        split = build_evidence(_SAMPLE_EVIDENCE, "BUY")
        ignored_texts = [e["text"] for e in split["ignored"]]
        assert "ADX inconclusive" in ignored_texts

    def test_neutral_line_in_ignored_for_sell(self):
        split = build_evidence(_SAMPLE_EVIDENCE, "SELL")
        ignored_texts = [e["text"] for e in split["ignored"]]
        assert "ADX inconclusive" in ignored_texts

    def test_neutral_signal_puts_everything_in_ignored(self):
        split = build_evidence(_SAMPLE_EVIDENCE, "NEUTRAL")
        assert split["evidence_for"] == []
        assert split["evidence_against"] == []
        assert len(split["ignored"]) == 3


class TestEV4ContextSummarySuccessfulFetch:
    def test_context_lines_from_valid_technicals(self):
        tech = {"interval": "week", "rsi_14": 60.0, "ema_20": 95.0, "last_close": 100.0}
        result = build_context_summary(tech, None)
        assert len(result["context"]) >= 1
        assert any("week" in line for line in result["context"])
        assert result["rejected"] == []


class TestEV5ContextSummaryFailedFetch:
    def test_rejected_when_fetch_errored(self):
        result = build_context_summary(None, "stale data refused: interval='week' ...")
        assert result["context"] == []
        assert len(result["rejected"]) == 1
        assert "stale" in result["rejected"][0].lower()


class TestEV6ContextStalenessCautionSurfacesAsRejected:
    def test_staleness_caution_becomes_rejected_entry(self):
        tech = {
            "interval": "week", "rsi_14": 60.0, "ema_20": 95.0, "last_close": 100.0,
            "staleness_caution": "CONTEXT-role data is 999999s old — still usable as context, but...",
        }
        result = build_context_summary(tech, None)
        assert len(result["context"]) >= 1  # data still surfaced
        assert len(result["rejected"]) == 1
        assert "999999" in result["rejected"][0]


class TestEV7GenerateTradeSetupTfHasFullEvidenceStructure:
    def _fake_tech(self):
        return {
            "symbol": "NIFTY", "last_close": 100.0, "candles_used": 150,
            "data_source": "yfinance_eod_adjusted", "last_candle_date": _fresh_daily_date(),
            "rsi_14": 65.0, "ema_20": 95.0, "ema_50": 90.0,
            "macd": {"macd": 0.5, "signal": 0.3, "histogram": 0.2},
            "adx_14": {"adx": 30.0, "plus_di": 28.0, "minus_di": 12.0},
            "atr_14": 2.0,
        }

    def test_all_evidence_keys_present(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": self._fake_tech())
        result = generate_trade_setup_tf("NIFTY", "SWING", "day")
        assert "error" not in result
        for key in ("evidence_for", "evidence_against", "ignored", "context", "rejected"):
            assert key in result

    def test_evidence_items_have_indicator_and_text(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": self._fake_tech())
        result = generate_trade_setup_tf("NIFTY", "SWING", "day")
        all_items = result["evidence_for"] + result["evidence_against"] + result["ignored"]
        assert len(all_items) > 0
        for item in all_items:
            assert "indicator" in item
            assert "text" in item


class TestEV8DailyOnlyFunctionHasNoEvidenceKeys:
    def test_generate_trade_setup_output_unaffected(self, monkeypatch):
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
        for key in ("evidence_for", "evidence_against", "ignored", "context", "rejected", "_evidence"):
            assert key not in result
        # reasoning must still be a flat list[str], not the tagged dict structure
        assert all(isinstance(line, str) for line in result["reasoning"])


class TestEV9StrongBullishSetupHasEvidenceForOnly:
    def test_strongly_bullish_technicals(self, monkeypatch):
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
        assert result["signal"] == "BUY"
        assert len(result["evidence_for"]) > 0
        assert len(result["evidence_against"]) == 0
