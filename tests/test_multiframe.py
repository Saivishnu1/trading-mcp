"""Tests for Phase 19 — Multi-timeframe Regime Confirmation."""
import pytest

from src.analysis.regime import (
    _classify_regime,
    _regime_direction,
    _alignment_level,
    _alignment_summary,
    get_regime_alignment,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tech(rsi=60.0, ema20=100.0, ema50=90.0, adx=30.0, price=102.0, atr=5.0,
          macd_val=0.5, macd_sig=0.3):
    """Build a minimal technicals dict accepted by _classify_regime."""
    return {
        "last_close": price,
        "rsi_14": rsi,
        "ema_20": ema20,
        "ema_50": ema50,
        "macd": {"macd": macd_val, "signal": macd_sig, "histogram": round(macd_val - macd_sig, 4)},
        "adx_14": {"adx": adx, "plus_di": 28.0, "minus_di": 12.0},
        "atr_14": atr,
    }


def _mock_analyze(monkeypatch, daily_tech, weekly_tech=None, monthly_tech=None):
    """Patch _analyze_technicals to return different snapshots per interval."""
    import src.analysis.regime as reg

    _weekly = weekly_tech or daily_tech
    _monthly = monthly_tech or daily_tech

    def _fake(symbol, lookback_days=150, interval="daily"):
        if interval == "weekly":
            return _weekly
        if interval == "monthly":
            return _monthly
        return daily_tech

    monkeypatch.setattr(reg, "_analyze_technicals", _fake)


# ---------------------------------------------------------------------------
# _classify_regime
# ---------------------------------------------------------------------------

class TestClassifyRegime:
    def test_bull_trend_ema_adx(self):
        r = _classify_regime("INFY", _tech(ema20=100, ema50=90, adx=30, rsi=65))
        assert r["regime"] == "BULL_TREND"

    def test_bear_trend_ema_adx(self):
        r = _classify_regime("INFY", _tech(ema20=90, ema50=100, adx=30, rsi=38, macd_val=-0.5, macd_sig=-0.3))
        assert r["regime"] == "BEAR_TREND"

    def test_range_bound_low_adx(self):
        r = _classify_regime("INFY", _tech(adx=15))
        assert r["regime"] == "RANGE_BOUND"

    def test_breakout_potential(self):
        r = _classify_regime("INFY", _tech(ema20=100, ema50=98, adx=22, rsi=60, price=101))
        assert r["regime"] == "BREAKOUT_POTENTIAL"

    def test_neutral_bullish_fallback(self):
        # price >= ema20 but doesn't match BULL/BEAR/RANGE/BREAKOUT conditions
        r = _classify_regime("INFY", _tech(ema20=100, ema50=99, adx=22, rsi=50, price=101))
        assert r["regime"] == "NEUTRAL_BULLISH"

    def test_neutral_bearish_fallback(self):
        r = _classify_regime("INFY", _tech(ema20=102, ema50=100, adx=22, rsi=50, price=99))
        assert r["regime"] == "NEUTRAL_BEARISH"

    def test_error_dict_passthrough(self):
        r = _classify_regime("INFY", {"error": "no data", "symbol": "INFY"})
        assert "error" in r

    def test_none_rsi_returns_error(self):
        t = _tech()
        t["rsi_14"] = None
        r = _classify_regime("INFY", t)
        assert "error" in r

    def test_nan_adx_returns_error(self):
        import math
        t = _tech()
        t["adx_14"] = {"adx": float("nan")}
        r = _classify_regime("INFY", t)
        assert "error" in r

    def test_confidence_within_0_85(self):
        r = _classify_regime("INFY", _tech(ema20=100, ema50=90, adx=40, rsi=70))
        assert 0 <= r["confidence"] <= 85

    def test_returns_symbol_uppercase(self):
        r = _classify_regime("infy", _tech())
        assert r["symbol"] == "INFY"


# ---------------------------------------------------------------------------
# _regime_direction
# ---------------------------------------------------------------------------

class TestRegimeDirection:
    def test_bull_trend(self):
        assert _regime_direction("BULL_TREND") == "bullish"

    def test_neutral_bullish(self):
        assert _regime_direction("NEUTRAL_BULLISH") == "bullish"

    def test_breakout_potential(self):
        assert _regime_direction("BREAKOUT_POTENTIAL") == "bullish"

    def test_bear_trend(self):
        assert _regime_direction("BEAR_TREND") == "bearish"

    def test_neutral_bearish(self):
        assert _regime_direction("NEUTRAL_BEARISH") == "bearish"

    def test_range_bound(self):
        assert _regime_direction("RANGE_BOUND") == "neutral"

    def test_none(self):
        assert _regime_direction(None) == "neutral"

    def test_unknown_string(self):
        assert _regime_direction("UNKNOWN") == "neutral"


# ---------------------------------------------------------------------------
# _alignment_level
# ---------------------------------------------------------------------------

class TestAlignmentLevel:
    def test_all_bullish_strong(self):
        assert _alignment_level("bullish", "bullish", "bullish") == "STRONG"

    def test_all_bearish_strong(self):
        assert _alignment_level("bearish", "bearish", "bearish") == "STRONG"

    def test_all_neutral_strong(self):
        assert _alignment_level("neutral", "neutral", "neutral") == "STRONG"

    def test_daily_bull_weekly_bear_conflict(self):
        assert _alignment_level("bullish", "bearish", "neutral") == "CONFLICT"

    def test_daily_bear_weekly_bull_conflict(self):
        assert _alignment_level("bearish", "bullish", "bullish") == "CONFLICT"

    def test_daily_bull_weekly_neutral_not_conflict(self):
        # weekly is neutral — not a hard conflict
        result = _alignment_level("bullish", "neutral", "bearish")
        assert result != "CONFLICT"

    def test_two_bullish_one_neutral_partial(self):
        assert _alignment_level("bullish", "bullish", "neutral") == "PARTIAL"

    def test_two_bullish_one_bearish_conflict(self):
        # daily=bull, weekly=bear → CONFLICT regardless of monthly
        assert _alignment_level("bullish", "bearish", "bullish") == "CONFLICT"

    def test_two_neutral_one_bullish_partial(self):
        assert _alignment_level("neutral", "neutral", "bullish") == "PARTIAL"

    def test_all_different_mixed(self):
        # daily=bullish, weekly=neutral, monthly=bearish — no majority
        result = _alignment_level("bullish", "neutral", "bearish")
        assert result in ("MIXED", "PARTIAL")  # implementation may vary; not STRONG/CONFLICT


# ---------------------------------------------------------------------------
# _alignment_summary
# ---------------------------------------------------------------------------

class TestAlignmentSummary:
    def _tf(self, regime):
        return {"regime": regime, "confidence": 65}

    def test_strong_summary_mentions_alignment(self):
        s = _alignment_summary(self._tf("BULL_TREND"), self._tf("BULL_TREND"), self._tf("BULL_TREND"), "STRONG")
        assert "strong" in s.lower()
        assert "bullish" in s.lower()

    def test_conflict_summary_mentions_conflict(self):
        s = _alignment_summary(self._tf("BULL_TREND"), self._tf("BEAR_TREND"), self._tf("BULL_TREND"), "CONFLICT")
        assert "conflict" in s.lower() or "counter-trend" in s.lower()

    def test_partial_summary_lists_regimes(self):
        s = _alignment_summary(self._tf("BULL_TREND"), self._tf("BULL_TREND"), self._tf("RANGE_BOUND"), "PARTIAL")
        assert "BULL_TREND" in s

    def test_mixed_summary_lists_regimes(self):
        s = _alignment_summary(self._tf("BULL_TREND"), self._tf("RANGE_BOUND"), self._tf("BEAR_TREND"), "MIXED")
        assert "BULL_TREND" in s


# ---------------------------------------------------------------------------
# get_regime_alignment (integration — mocked _analyze_technicals)
# ---------------------------------------------------------------------------

class TestGetRegimeAlignment:
    def test_returns_all_three_timeframes(self, monkeypatch):
        _mock_analyze(monkeypatch, _tech(ema20=100, ema50=90, adx=30, rsi=65))
        r = get_regime_alignment("INFY")
        assert "daily" in r and "weekly" in r and "monthly" in r

    def test_strong_when_all_same_regime(self, monkeypatch):
        _mock_analyze(monkeypatch, _tech(ema20=100, ema50=90, adx=30, rsi=65))
        r = get_regime_alignment("INFY")
        assert r["alignment"] == "STRONG"

    def test_conflict_when_daily_bull_weekly_bear(self, monkeypatch):
        bull = _tech(ema20=100, ema50=90, adx=30, rsi=65)
        bear = _tech(ema20=90, ema50=100, adx=30, rsi=38, macd_val=-0.5, macd_sig=-0.3)
        _mock_analyze(monkeypatch, daily_tech=bull, weekly_tech=bear, monthly_tech=bull)
        r = get_regime_alignment("INFY")
        assert r["alignment"] == "CONFLICT"

    def test_regime_key_in_each_timeframe(self, monkeypatch):
        _mock_analyze(monkeypatch, _tech())
        r = get_regime_alignment("INFY")
        for tf in ("daily", "weekly", "monthly"):
            assert "regime" in r[tf]

    def test_summary_is_non_empty_string(self, monkeypatch):
        _mock_analyze(monkeypatch, _tech())
        r = get_regime_alignment("INFY")
        assert isinstance(r["summary"], str) and len(r["summary"]) > 5

    def test_symbol_uppercased(self, monkeypatch):
        _mock_analyze(monkeypatch, _tech())
        r = get_regime_alignment("infy")
        assert r["symbol"] == "INFY"

    def test_error_in_weekly_propagated(self, monkeypatch):
        import src.analysis.regime as reg
        daily_data = _tech()
        err_data = {"error": "no data", "symbol": "INFY"}

        def _fake(symbol, lookback_days=150, interval="daily"):
            if interval == "weekly":
                return err_data
            return daily_data

        monkeypatch.setattr(reg, "_analyze_technicals", _fake)
        r = get_regime_alignment("INFY")
        # Error propagates to the weekly entry; alignment still returns a result
        assert "alignment" in r
        assert r["weekly"].get("regime") is None


# ---------------------------------------------------------------------------
# recommend_trade — timeframe conflict integration
# ---------------------------------------------------------------------------

class TestRecommendTradeTimeframeConflict:
    """Override the conftest autouse mock to inject specific alignment scenarios."""

    def _base_plan(self, signal="BUY"):
        return {
            "signal": signal, "trade_allowed": True, "confidence": 70,
            "raw_confidence": 70.0, "calibrated_confidence": 70.0,
            "confidence_adjustment": 0, "calibration_applied": False,
            "entry": 1000.0, "stoploss": 950.0, "target": 1100.0,
            "trade_quality": "GOOD", "data_basis": None,
            "position": {"position_size": 10, "capital": 100000, "risk_percent": 1.0, "risk_amount": 1000},
            "risk_reward": {"rr": 2.0, "risk": 50.0, "reward": 100.0},
            "strategy": {"recommended": "Bull Call Spread", "secondary": None, "reason": ""},
            "market_context": {"regime": "BULL_TREND"},
            "risk_score": None,
            "summary": "",
        }

    def _setup_deps(self, monkeypatch, plan, weekly_regime, alignment):
        import src.recommendations.engine as eng
        monkeypatch.setattr(eng, "_create_trade_plan", lambda *a, **kw: plan)
        monkeypatch.setattr(eng, "_get_open_trades", lambda *a, **kw: {"trades": []})
        monkeypatch.setattr(eng, "_get_event_risk", lambda s: {
            "event_risk_score": 20, "event_risk_rating": "LOW", "confidence": 0.9,
        })
        monkeypatch.setattr(eng, "_get_india_vix", lambda: {"vix": 13.0, "caution_level": "LOW"})
        monkeypatch.setattr(eng, "_get_regime_alignment", lambda s: {
            "daily":   {"regime": plan["market_context"]["regime"], "confidence": 70},
            "weekly":  {"regime": weekly_regime, "confidence": 60},
            "monthly": {"regime": weekly_regime, "confidence": 62},
            "alignment": alignment,
            "summary": f"daily vs weekly: {alignment}",
        })

    def test_no_conflict_caution_when_weekly_agrees(self, monkeypatch):
        plan = self._base_plan("BUY")
        self._setup_deps(monkeypatch, plan, "BULL_TREND", "STRONG")
        from src.recommendations.engine import recommend_trade
        r = recommend_trade("INFY")
        conflict_cautions = [c for c in r["cautions"] if "Higher timeframe conflict" in c]
        assert len(conflict_cautions) == 0

    def test_conflict_caution_when_buy_vs_weekly_bear_trend(self, monkeypatch):
        plan = self._base_plan("BUY")
        self._setup_deps(monkeypatch, plan, "BEAR_TREND", "CONFLICT")
        from src.recommendations.engine import recommend_trade
        r = recommend_trade("INFY")
        conflict_cautions = [c for c in r["cautions"] if "Higher timeframe conflict" in c]
        assert len(conflict_cautions) == 1

    def test_conflict_causes_wait_not_enter(self, monkeypatch):
        plan = self._base_plan("BUY")
        self._setup_deps(monkeypatch, plan, "BEAR_TREND", "CONFLICT")
        from src.recommendations.engine import recommend_trade
        r = recommend_trade("INFY")
        assert r["recommendation"] == "WAIT"

    def test_sell_vs_weekly_bull_is_conflict(self, monkeypatch):
        plan = self._base_plan("SELL")
        plan["market_context"]["regime"] = "BEAR_TREND"
        self._setup_deps(monkeypatch, plan, "BULL_TREND", "CONFLICT")
        from src.recommendations.engine import recommend_trade
        r = recommend_trade("INFY")
        conflict_cautions = [c for c in r["cautions"] if "Higher timeframe conflict" in c]
        assert len(conflict_cautions) == 1

    def test_buy_vs_weekly_neutral_bearish_is_conflict(self, monkeypatch):
        plan = self._base_plan("BUY")
        self._setup_deps(monkeypatch, plan, "NEUTRAL_BEARISH", "CONFLICT")
        from src.recommendations.engine import recommend_trade
        r = recommend_trade("INFY")
        conflict_cautions = [c for c in r["cautions"] if "Higher timeframe conflict" in c]
        assert len(conflict_cautions) == 1

    def test_sell_vs_weekly_neutral_bullish_is_conflict(self, monkeypatch):
        plan = self._base_plan("SELL")
        plan["market_context"]["regime"] = "BEAR_TREND"
        self._setup_deps(monkeypatch, plan, "NEUTRAL_BULLISH", "CONFLICT")
        from src.recommendations.engine import recommend_trade
        r = recommend_trade("INFY")
        conflict_cautions = [c for c in r["cautions"] if "Higher timeframe conflict" in c]
        assert len(conflict_cautions) == 1

    def test_weekly_regime_in_response(self, monkeypatch):
        plan = self._base_plan("BUY")
        self._setup_deps(monkeypatch, plan, "NEUTRAL_BULLISH", "PARTIAL")
        from src.recommendations.engine import recommend_trade
        r = recommend_trade("INFY")
        assert "weekly_regime" in r
        assert r["weekly_regime"] == "NEUTRAL_BULLISH"
        assert "timeframe_alignment" in r
        assert r["timeframe_alignment"] == "PARTIAL"

    def test_timeframe_failure_does_not_break_recommend(self, monkeypatch):
        plan = self._base_plan("BUY")
        import src.recommendations.engine as eng
        monkeypatch.setattr(eng, "_create_trade_plan", lambda *a, **kw: plan)
        monkeypatch.setattr(eng, "_get_open_trades", lambda *a, **kw: {"trades": []})
        monkeypatch.setattr(eng, "_get_event_risk", lambda s: {
            "event_risk_score": 20, "event_risk_rating": "LOW", "confidence": 0.9,
        })
        monkeypatch.setattr(eng, "_get_india_vix", lambda: {"vix": 13.0, "caution_level": "LOW"})

        def _raise(s):
            raise RuntimeError("network timeout")

        monkeypatch.setattr(eng, "_get_regime_alignment", _raise)
        from src.recommendations.engine import recommend_trade
        r = recommend_trade("INFY")
        assert "error" not in r
        assert r["recommendation"] in ("ENTER", "WAIT", "AVOID")
        assert r["weekly_regime"] is None

    def test_gating_data_timeframe_key_present(self, monkeypatch):
        plan = self._base_plan("BUY")
        self._setup_deps(monkeypatch, plan, "BULL_TREND", "STRONG")
        from src.recommendations.engine import recommend_trade
        r = recommend_trade("INFY")
        assert "timeframe" in r["gating_data_available"]
        assert r["gating_data_available"]["timeframe"] is True

    def test_strong_alignment_adds_reason(self, monkeypatch):
        plan = self._base_plan("BUY")
        self._setup_deps(monkeypatch, plan, "BULL_TREND", "STRONG")
        from src.recommendations.engine import recommend_trade
        r = recommend_trade("INFY")
        alignment_reasons = [reason for reason in r["reasons"] if "timeframe alignment" in reason.lower()]
        assert len(alignment_reasons) == 1
