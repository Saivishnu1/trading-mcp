"""
Unit and integration tests for src/planner/trade_plan.py.

Pure logic (_trade_quality, _build_summary) is tested without mocking.
create_trade_plan mocks _analyze_technicals + options service.
"""
import pytest

from src.planner.trade_plan import (
    _build_summary,
    _quality_clause,
    _trade_quality,
    create_trade_plan,
)

# ---------------------------------------------------------------------------
# Shared tech and strategy mock helpers
# ---------------------------------------------------------------------------

def _tech(rsi=65.0, ema20=100.0, ema50=90.0, adx=30.0, price=101.0,
          atr=2.0, macd_val=0.5, macd_sig=0.3):
    return {
        "symbol": "NIFTY",
        "last_close": price,
        "candles_used": 150,
        "rsi_14": rsi,
        "ema_20": ema20,
        "ema_50": ema50,
        "macd": {"macd": macd_val, "signal": macd_sig,
                 "histogram": round(macd_val - macd_sig, 4)},
        "adx_14": {"adx": adx, "plus_di": 28.0, "minus_di": 12.0},
        "atr_14": atr,
    }


BULL_TECH = _tech()   # EMA20>EMA50, ADX>25, RSI>55 → BULL_TREND, BUY
BEAR_TECH = _tech(rsi=35.0, ema20=90.0, ema50=100.0, adx=28.0, price=89.0,
                  macd_val=-0.5, macd_sig=-0.3)
NEUTRAL_TECH = _tech(rsi=50.0, ema20=100.0, ema50=100.0, adx=15.0, price=100.0,
                     macd_val=0.1, macd_sig=0.1)


# ---------------------------------------------------------------------------
# _trade_quality — pure function
# ---------------------------------------------------------------------------

class TestTradeQuality:

    def test_below_one_low_quality(self):
        assert _trade_quality(0.5) == "LOW_QUALITY"
        assert _trade_quality(0.99) == "LOW_QUALITY"

    def test_exactly_one_moderate(self):
        assert _trade_quality(1.0) == "MODERATE"

    def test_moderate_range(self):
        assert _trade_quality(1.2) == "MODERATE"
        assert _trade_quality(1.49) == "MODERATE"

    def test_good_range(self):
        assert _trade_quality(1.5) == "GOOD"
        assert _trade_quality(1.99) == "GOOD"

    def test_high_quality(self):
        assert _trade_quality(2.0) == "HIGH_QUALITY"
        assert _trade_quality(3.0) == "HIGH_QUALITY"

    def test_none_rr_is_low_quality(self):
        assert _trade_quality(None) == "LOW_QUALITY"


# ---------------------------------------------------------------------------
# _quality_clause — pure function
# ---------------------------------------------------------------------------

class TestQualityClause:

    def test_low_quality_mentions_rr(self):
        clause = _quality_clause("LOW_QUALITY", 0.7)
        assert "0.70" in clause

    def test_high_quality_mentions_rr(self):
        clause = _quality_clause("HIGH_QUALITY", 2.5)
        assert "2.50" in clause

    def test_none_rr_shows_na(self):
        clause = _quality_clause("LOW_QUALITY", None)
        assert "N/A" in clause


# ---------------------------------------------------------------------------
# _build_summary — pure function
# ---------------------------------------------------------------------------

class TestBuildSummary:

    def test_buy_good_quality_has_entry(self):
        s = _build_summary("BUY", 101.0, 98.0, 106.0, 2.0, "Long Call", "GOOD")
        assert "101" in s
        assert "Long Call" in s

    def test_buy_low_quality_no_trade(self):
        s = _build_summary("BUY", 101.0, 98.0, 106.0, 0.5, "Long Call", "LOW_QUALITY")
        assert "Bullish" in s or "bullish" in s

    def test_sell_good_quality(self):
        s = _build_summary("SELL", 99.0, 102.0, 94.0, 2.0, "Long Put", "HIGH_QUALITY")
        assert "99" in s or "94" in s

    def test_neutral_no_trade(self):
        s = _build_summary("NEUTRAL", 100.0, 100.0, 100.0, None, "Iron Condor", "LOW_QUALITY")
        assert "No trade" in s or "no trade" in s.lower()

    def test_neutral_bullish_mentions_cautious(self):
        s = _build_summary("NEUTRAL_BULLISH", 101.0, 98.0, 106.0, 1.6, "Bull Call Spread", "GOOD")
        assert "Cautious" in s or "cautious" in s.lower()

    def test_neutral_bearish_low_quality(self):
        s = _build_summary("NEUTRAL_BEARISH", 99.0, 102.0, 94.0, 0.8, "Bear Put Spread", "LOW_QUALITY")
        assert "bearish" in s.lower()


# ---------------------------------------------------------------------------
# create_trade_plan — integration (mocks _analyze_technicals + options service)
# ---------------------------------------------------------------------------

class TestCreateTradePlan:

    def _patch(self, monkeypatch, tech, silence_options=True):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: tech)
        if silence_options:
            monkeypatch.setattr(
                "src.planner.trade_plan.get_options_service",
                lambda: _raise_runtime_error(),
            )

    def test_buy_plan_structure(self, monkeypatch):
        self._patch(monkeypatch, BULL_TECH)
        r = create_trade_plan("NIFTY")
        assert r["signal"] == "BUY"
        assert r["trade_allowed"] is True
        assert "entry" in r
        assert "stoploss" in r
        assert "target" in r
        assert "risk_reward" in r
        assert "position" in r
        assert "strategy" in r
        assert "market_context" in r
        assert "summary" in r

    def test_buy_has_trade_quality(self, monkeypatch):
        self._patch(monkeypatch, BULL_TECH)
        r = create_trade_plan("NIFTY")
        assert r.get("trade_quality") in ("LOW_QUALITY", "MODERATE", "GOOD", "HIGH_QUALITY")

    def test_neutral_signal_trade_not_allowed(self, monkeypatch):
        self._patch(monkeypatch, NEUTRAL_TECH)
        r = create_trade_plan("NIFTY")
        assert r["signal"] == "NEUTRAL"
        assert r["trade_allowed"] is False
        assert "reason" in r

    def test_sell_plan_structure(self, monkeypatch):
        self._patch(monkeypatch, BEAR_TECH)
        r = create_trade_plan("NIFTY")
        assert r["signal"] == "SELL"
        assert "entry" in r
        assert "stoploss" in r
        assert "target" in r

    def test_error_propagation(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: {"error": "no data"})
        monkeypatch.setattr(
            "src.planner.trade_plan.get_options_service",
            lambda: _raise_runtime_error(),
        )
        r = create_trade_plan("NIFTY")
        assert "error" in r

    def test_options_failure_does_not_break_plan(self, monkeypatch):
        """Options context failure must be silently swallowed."""
        self._patch(monkeypatch, BULL_TECH, silence_options=True)
        r = create_trade_plan("NIFTY")
        assert "error" not in r
        assert r["signal"] == "BUY"

    def test_risk_reward_keys_in_plan(self, monkeypatch):
        self._patch(monkeypatch, BULL_TECH)
        r = create_trade_plan("NIFTY")
        rr = r["risk_reward"]
        assert "risk" in rr
        assert "reward" in rr
        assert "rr" in rr

    def test_position_keys_in_plan(self, monkeypatch):
        self._patch(monkeypatch, BULL_TECH)
        r = create_trade_plan("NIFTY", capital=200_000, risk_percent=2.0)
        pos = r["position"]
        assert "capital" in pos
        assert "risk_percent" in pos
        assert "position_size" in pos

    def test_symbol_uppercased(self, monkeypatch):
        self._patch(monkeypatch, BULL_TECH)
        r = create_trade_plan("nifty")
        assert r["symbol"] == "NIFTY"

    def test_low_quality_trade_not_allowed(self, monkeypatch):
        """Regression: RR < 1 must set trade_allowed=False."""
        # Use a custom tech with very small ATR so entry~stoploss~target
        # Actually, just patch _trade_quality directly
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: BULL_TECH)
        monkeypatch.setattr(
            "src.planner.trade_plan.get_options_service",
            lambda: _raise_runtime_error(),
        )
        monkeypatch.setattr("src.planner.trade_plan._trade_quality",
                            lambda rr: "LOW_QUALITY")
        r = create_trade_plan("NIFTY")
        if r.get("signal") != "NEUTRAL":
            assert r["trade_allowed"] is False
            assert r["trade_quality"] == "LOW_QUALITY"


def _raise_runtime_error():
    raise RuntimeError("NSE unavailable in tests")
