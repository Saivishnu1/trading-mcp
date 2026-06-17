"""
Unit and integration tests for src/review/reviewer.py.

_evaluate and _invalidation_conditions are pure functions — no mocking.
review_trade integration mocks _analyze_technicals + options service.
"""
import pytest

from src.review.reviewer import (
    _evaluate,
    _invalidation_conditions,
    review_trade,
)

# ---------------------------------------------------------------------------
# Tech snapshots for integration tests
# ---------------------------------------------------------------------------

def _tech(rsi=65.0, ema20=100.0, ema50=90.0, adx=30.0, price=101.0,
          atr=2.0, macd_val=0.5, macd_sig=0.3):
    return {
        "symbol": "NIFTY", "last_close": price, "candles_used": 150,
        "rsi_14": rsi, "ema_20": ema20, "ema_50": ema50,
        "macd": {"macd": macd_val, "signal": macd_sig,
                 "histogram": round(macd_val - macd_sig, 4)},
        "adx_14": {"adx": adx, "plus_di": 28.0, "minus_di": 12.0},
        "atr_14": atr,
    }


BULL_TECH = _tech()
BEAR_TECH = _tech(rsi=35.0, ema20=90.0, ema50=100.0, adx=28.0, price=89.0,
                  macd_val=-0.5, macd_sig=-0.3)
NEUTRAL_TECH = _tech(rsi=50.0, ema20=100.0, ema50=100.0, adx=15.0, price=100.0,
                     macd_val=0.1, macd_sig=0.1)


def _silence_options(monkeypatch):
    monkeypatch.setattr("src.planner.trade_plan.get_options_service",
                        lambda: _raise_svc())


class _raise_svc:
    def get_option_chain(self, *a, **kw):
        raise RuntimeError("NSE unavailable in tests")


# ---------------------------------------------------------------------------
# _evaluate — pure function, deterministic mapping
# ---------------------------------------------------------------------------

class TestEvaluate:

    # LONG direction
    def test_long_buy_valid_hold(self):
        thesis, action = _evaluate("LONG", "BUY")
        assert thesis == "VALID"
        assert action == "HOLD"

    def test_long_neutral_bullish_weakening_hold(self):
        thesis, action = _evaluate("LONG", "NEUTRAL_BULLISH")
        assert thesis == "WEAKENING"
        assert action == "HOLD"

    def test_long_neutral_weakening_reduce(self):
        thesis, action = _evaluate("LONG", "NEUTRAL")
        assert thesis == "WEAKENING"
        assert action == "REDUCE"

    def test_long_neutral_bearish_invalidated_exit(self):
        thesis, action = _evaluate("LONG", "NEUTRAL_BEARISH")
        assert thesis == "INVALIDATED"
        assert action == "EXIT"

    def test_long_sell_invalidated_exit(self):
        thesis, action = _evaluate("LONG", "SELL")
        assert thesis == "INVALIDATED"
        assert action == "EXIT"

    # SHORT direction
    def test_short_sell_valid_hold(self):
        thesis, action = _evaluate("SHORT", "SELL")
        assert thesis == "VALID"
        assert action == "HOLD"

    def test_short_neutral_bearish_weakening_hold(self):
        thesis, action = _evaluate("SHORT", "NEUTRAL_BEARISH")
        assert thesis == "WEAKENING"
        assert action == "HOLD"

    def test_short_neutral_weakening_reduce(self):
        thesis, action = _evaluate("SHORT", "NEUTRAL")
        assert thesis == "WEAKENING"
        assert action == "REDUCE"

    def test_short_neutral_bullish_invalidated_exit(self):
        thesis, action = _evaluate("SHORT", "NEUTRAL_BULLISH")
        assert thesis == "INVALIDATED"
        assert action == "EXIT"

    def test_short_buy_invalidated_exit(self):
        thesis, action = _evaluate("SHORT", "BUY")
        assert thesis == "INVALIDATED"
        assert action == "EXIT"


# ---------------------------------------------------------------------------
# _invalidation_conditions — pure function
# ---------------------------------------------------------------------------

class TestInvalidationConditions:

    def test_long_conditions_mention_ema20(self):
        conds = _invalidation_conditions("LONG", ema20=24000.0, ema50=23000.0, rsi=60.0)
        combined = " ".join(conds)
        assert "24000" in combined  # EMA20 value referenced

    def test_long_conditions_mention_ema50(self):
        conds = _invalidation_conditions("LONG", ema20=24000.0, ema50=23000.0, rsi=60.0)
        combined = " ".join(conds)
        assert "23000" in combined

    def test_long_conditions_has_rsi_trigger(self):
        conds = _invalidation_conditions("LONG", 24000.0, 23000.0, 60.0)
        assert any("45" in c for c in conds)

    def test_long_conditions_mention_sell_signal(self):
        conds = _invalidation_conditions("LONG", 24000.0, 23000.0, 60.0)
        assert any("SELL" in c for c in conds)

    def test_short_conditions_mention_above_ema(self):
        conds = _invalidation_conditions("SHORT", ema20=24000.0, ema50=23000.0, rsi=40.0)
        combined = " ".join(conds)
        assert "above" in combined.lower()

    def test_short_conditions_has_rsi_trigger(self):
        conds = _invalidation_conditions("SHORT", 24000.0, 23000.0, 40.0)
        assert any("55" in c for c in conds)

    def test_short_conditions_mention_buy_signal(self):
        conds = _invalidation_conditions("SHORT", 24000.0, 23000.0, 40.0)
        assert any("BUY" in c for c in conds)

    def test_returns_list_of_strings(self):
        conds = _invalidation_conditions("LONG", 24000.0, 23000.0, 60.0)
        assert isinstance(conds, list)
        assert all(isinstance(c, str) for c in conds)
        assert len(conds) >= 2


# ---------------------------------------------------------------------------
# review_trade — integration tests
# ---------------------------------------------------------------------------

class TestReviewTrade:

    def _patch(self, monkeypatch, tech):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: tech)
        _silence_options(monkeypatch)

    def test_long_buy_signal_valid_hold(self, monkeypatch):
        self._patch(monkeypatch, BULL_TECH)
        r = review_trade("NIFTY", "LONG")
        assert r["thesis_status"] == "VALID"
        assert r["action"] == "HOLD"

    def test_short_sell_signal_valid_hold(self, monkeypatch):
        self._patch(monkeypatch, BEAR_TECH)
        r = review_trade("NIFTY", "SHORT")
        assert r["thesis_status"] == "VALID"
        assert r["action"] == "HOLD"

    def test_long_sell_signal_invalidated_exit(self, monkeypatch):
        self._patch(monkeypatch, BEAR_TECH)
        r = review_trade("NIFTY", "LONG")
        assert r["thesis_status"] == "INVALIDATED"
        assert r["action"] == "EXIT"

    def test_short_buy_signal_invalidated_exit(self, monkeypatch):
        self._patch(monkeypatch, BULL_TECH)
        r = review_trade("NIFTY", "SHORT")
        assert r["thesis_status"] == "INVALIDATED"
        assert r["action"] == "EXIT"

    def test_returns_required_fields(self, monkeypatch):
        self._patch(monkeypatch, BULL_TECH)
        r = review_trade("NIFTY", "LONG")
        for key in ("symbol", "direction", "current_price", "current_signal",
                    "current_regime", "thesis_status", "confidence", "action",
                    "invalidation_conditions", "reasoning", "summary"):
            assert key in r

    def test_with_entry_price_adds_pnl(self, monkeypatch):
        self._patch(monkeypatch, BULL_TECH)
        r = review_trade("NIFTY", "LONG", entry_price=95.0)
        assert "current_pnl_percent" in r
        assert "entry_price" in r

    def test_long_pnl_positive_when_price_above_entry(self, monkeypatch):
        self._patch(monkeypatch, BULL_TECH)
        # BULL_TECH price=101, entry=95 → LONG profit
        r = review_trade("NIFTY", "LONG", entry_price=95.0)
        assert r["current_pnl_percent"] > 0

    def test_short_pnl_positive_when_price_below_entry(self, monkeypatch):
        self._patch(monkeypatch, BULL_TECH)
        # price=101, entry=110 → SHORT profit (entry > current price)
        r = review_trade("NIFTY", "SHORT", entry_price=110.0)
        assert r["current_pnl_percent"] > 0

    def test_holding_days_returned_when_provided(self, monkeypatch):
        self._patch(monkeypatch, BULL_TECH)
        r = review_trade("NIFTY", "LONG", holding_days=5)
        assert r.get("holding_days") == 5

    def test_holding_days_absent_when_not_provided(self, monkeypatch):
        self._patch(monkeypatch, BULL_TECH)
        r = review_trade("NIFTY", "LONG")
        assert "holding_days" not in r

    def test_invalid_direction_returns_error(self, monkeypatch):
        self._patch(monkeypatch, BULL_TECH)
        r = review_trade("NIFTY", "SIDEWAYS")
        assert "error" in r

    def test_direction_uppercased(self, monkeypatch):
        self._patch(monkeypatch, BULL_TECH)
        r = review_trade("NIFTY", "long")
        assert r.get("direction") == "LONG"

    def test_symbol_uppercased(self, monkeypatch):
        self._patch(monkeypatch, BULL_TECH)
        r = review_trade("nifty", "LONG")
        assert r["symbol"] == "NIFTY"

    def test_reasoning_is_non_empty_list(self, monkeypatch):
        self._patch(monkeypatch, BULL_TECH)
        r = review_trade("NIFTY", "LONG")
        assert isinstance(r["reasoning"], list)
        assert len(r["reasoning"]) > 0

    def test_invalidation_conditions_is_list(self, monkeypatch):
        self._patch(monkeypatch, BULL_TECH)
        r = review_trade("NIFTY", "LONG")
        assert isinstance(r["invalidation_conditions"], list)

    def test_bad_data_returns_error(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: {"error": "no price data"})
        _silence_options(monkeypatch)
        r = review_trade("NIFTY", "LONG")
        assert "error" in r
