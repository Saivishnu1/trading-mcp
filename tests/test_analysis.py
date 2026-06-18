"""
Unit tests for src/analysis/regime.py.

calculate_risk_reward and calculate_position_size are pure math — no mocking.
detect_market_regime and generate_trade_setup mock _analyze_technicals.
recommend_strategy mocks detect_market_regime + generate_trade_setup directly
to test every strategy-selection branch in isolation.
"""
import pytest

from src.analysis.regime import (
    _is_invalid,
    calculate_position_size,
    calculate_risk_reward,
    detect_market_regime,
    generate_trade_setup,
    recommend_strategy,
)

# ---------------------------------------------------------------------------
# Local tech snapshots (regime-specific indicator dicts)
# ---------------------------------------------------------------------------

def _tech(symbol, rsi, ema20, ema50, adx, price, atr=2.0,
          macd_val=0.5, macd_sig=0.3):
    return {
        "symbol": symbol.upper(),
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


BULL  = _tech("NIFTY", rsi=65.0, ema20=100.0, ema50=90.0,  adx=30.0, price=101.0)
BEAR  = _tech("NIFTY", rsi=35.0, ema20=90.0,  ema50=100.0, adx=28.0, price=89.0,
              macd_val=-0.5, macd_sig=-0.3)
RANGE = _tech("NIFTY", rsi=50.0, ema20=100.0, ema50=98.0,  adx=15.0, price=100.5,
              macd_val=0.1, macd_sig=0.0)
BKOUT = _tech("NIFTY", rsi=60.0, ema20=100.0, ema50=98.0,  adx=22.0, price=101.0)
# Fallback NEUTRAL_BULLISH: adx in [20,25], rsi not >55, price >= ema20
NB    = _tech("NIFTY", rsi=50.0, ema20=100.0, ema50=99.0,  adx=22.0, price=101.0,
              macd_val=0.1, macd_sig=0.0)
# Fallback NEUTRAL_BEARISH: adx in [20,25], rsi not <45, price < ema20
NR    = _tech("NIFTY", rsi=50.0, ema20=102.0, ema50=100.0, adx=22.0, price=99.0,
              macd_val=-0.1, macd_sig=0.0)
# Perfectly balanced → NEUTRAL signal
NEUT  = _tech("NIFTY", rsi=50.0, ema20=100.0, ema50=100.0, adx=15.0, price=100.0,
              macd_val=0.1, macd_sig=0.1)
# RANGE_BOUND regime + BUY signal (historical conflict bug)
RNG_BUY  = _tech("NIFTY", rsi=65.0, ema20=100.0, ema50=99.0, adx=15.0, price=101.0)
# RANGE_BOUND + moderate bearish (3/4 conditions) → NEUTRAL_BEARISH, not SELL
# bearish=50 (rsi<45+price<ema20+price<ema50), bullish=0, bearish<60 → NEUTRAL_BEARISH
RNG_SELL = _tech("NIFTY", rsi=35.0, ema20=102.0, ema50=100.0, adx=15.0, price=99.0,
                 macd_val=-0.1, macd_sig=-0.3)
# RSI overbought (>70): all else bullish — tests Fix 4 overbought tier
OVERBOUGHT = _tech("NIFTY", rsi=74.0, ema20=100.0, ema50=90.0, adx=30.0, price=101.0)
# RSI oversold (<30): all else bearish — tests Fix 4 oversold tier
OVERSOLD_BEAR = _tech("NIFTY", rsi=25.0, ema20=90.0, ema50=100.0, adx=28.0, price=89.0,
                      macd_val=-0.5, macd_sig=-0.3)


# ---------------------------------------------------------------------------
# calculate_risk_reward — pure math
# ---------------------------------------------------------------------------

class TestCalculateRiskReward:

    def test_basic(self):
        r = calculate_risk_reward(entry=100, stoploss=95, target=110)
        assert r["risk"] == pytest.approx(5.0, rel=1e-4)
        assert r["reward"] == pytest.approx(10.0, rel=1e-4)
        assert r["rr"] == pytest.approx(2.0, rel=1e-4)

    def test_rr_less_than_one(self):
        r = calculate_risk_reward(entry=100, stoploss=90, target=105)
        assert r["rr"] == pytest.approx(0.5, rel=1e-4)

    def test_returns_all_fields(self):
        r = calculate_risk_reward(100, 95, 110)
        for key in ("entry", "stoploss", "target", "risk", "reward", "rr"):
            assert key in r

    def test_entry_equals_stoploss_rr_none(self):
        r = calculate_risk_reward(entry=100, stoploss=100, target=110)
        assert r["rr"] is None

    def test_invalid_entry_returns_error(self):
        r = calculate_risk_reward(entry=0, stoploss=95, target=110)
        assert "error" in r

    def test_invalid_target_returns_error(self):
        r = calculate_risk_reward(entry=100, stoploss=95, target=0)
        assert "error" in r

    def test_non_numeric_returns_error(self):
        r = calculate_risk_reward(entry="abc", stoploss=95, target=110)
        assert "error" in r

    def test_sell_side_works(self):
        # SELL: entry below stoploss, target below entry
        r = calculate_risk_reward(entry=95, stoploss=100, target=85)
        assert r["risk"] == pytest.approx(5.0, rel=1e-4)
        assert r["reward"] == pytest.approx(10.0, rel=1e-4)
        assert r["rr"] == pytest.approx(2.0, rel=1e-4)


# ---------------------------------------------------------------------------
# calculate_position_size — pure math
# ---------------------------------------------------------------------------

class TestCalculatePositionSize:

    def test_basic(self):
        r = calculate_position_size(capital=100_000, risk_percent=1.0,
                                    entry=100, stoploss=95)
        # risk_amount = 100_000 * 0.01 = 1000
        # stop_distance = 5
        # position_size = 1000/5 = 200
        assert r["position_size"] == pytest.approx(200.0, rel=1e-4)
        assert r["risk_amount"] == pytest.approx(1000.0, rel=1e-4)

    def test_returns_all_fields(self):
        r = calculate_position_size(100_000, 2.0, 200, 190)
        for key in ("capital", "risk_percent", "risk_amount", "position_size"):
            assert key in r

    def test_entry_equals_stoploss_size_none(self):
        r = calculate_position_size(100_000, 1.0, 100, 100)
        assert r["position_size"] is None

    def test_invalid_capital_returns_error(self):
        r = calculate_position_size(capital=0, risk_percent=1.0, entry=100, stoploss=95)
        assert "error" in r

    def test_invalid_risk_percent_returns_error(self):
        r = calculate_position_size(100_000, risk_percent=0, entry=100, stoploss=95)
        assert "error" in r

    def test_larger_stop_means_smaller_size(self):
        r_tight = calculate_position_size(100_000, 1.0, 100, 98)   # 2-pt stop
        r_wide  = calculate_position_size(100_000, 1.0, 100, 90)   # 10-pt stop
        assert r_tight["position_size"] > r_wide["position_size"]


# ---------------------------------------------------------------------------
# _is_invalid — unit tests for the NaN/None guard helper (Fix 2a)
# ---------------------------------------------------------------------------

class TestIsInvalid:

    def test_none_is_invalid(self):
        assert _is_invalid(None) is True

    def test_nan_float_is_invalid(self):
        assert _is_invalid(float("nan")) is True

    def test_regular_float_is_valid(self):
        assert _is_invalid(65.5) is False

    def test_zero_is_valid(self):
        # zero is a legitimate indicator value (e.g. ADX can be 0)
        assert _is_invalid(0.0) is False


# ---------------------------------------------------------------------------
# detect_market_regime — mocks _analyze_technicals
# ---------------------------------------------------------------------------

class TestDetectMarketRegime:

    def test_bull_trend(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: BULL)
        r = detect_market_regime("NIFTY")
        assert r["regime"] == "BULL_TREND"
        assert r["confidence"] >= 70

    def test_bear_trend(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: BEAR)
        r = detect_market_regime("NIFTY")
        assert r["regime"] == "BEAR_TREND"

    def test_range_bound(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: RANGE)
        r = detect_market_regime("NIFTY")
        assert r["regime"] == "RANGE_BOUND"

    def test_breakout_potential(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: BKOUT)
        r = detect_market_regime("NIFTY")
        assert r["regime"] == "BREAKOUT_POTENTIAL"

    def test_neutral_bullish_fallback(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: NB)
        r = detect_market_regime("NIFTY")
        assert r["regime"] == "NEUTRAL_BULLISH"

    def test_neutral_bearish_fallback(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: NR)
        r = detect_market_regime("NIFTY")
        assert r["regime"] == "NEUTRAL_BEARISH"

    def test_returns_required_fields(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: BULL)
        r = detect_market_regime("NIFTY")
        for key in ("symbol", "regime", "confidence", "price",
                    "rsi", "ema20", "ema50", "adx", "atr"):
            assert key in r

    def test_bad_symbol_returns_error(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: {"error": "no data"})
        r = detect_market_regime("BADINPUT")
        assert "error" in r

    def test_symbol_uppercased_in_output(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: BULL)
        r = detect_market_regime("nifty")
        assert r["symbol"] == "NIFTY"

    def test_regime_returns_error_for_nan_rsi(self, monkeypatch):
        nan_tech = {**BULL, "rsi_14": float("nan")}
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: nan_tech)
        r = detect_market_regime("NIFTY")
        assert "error" in r, (
            "NaN rsi_14 must cause detect_market_regime to return an error dict"
        )


# ---------------------------------------------------------------------------
# generate_trade_setup — mocks _analyze_technicals
# ---------------------------------------------------------------------------

class TestGenerateTradeSetup:

    def _setup(self, monkeypatch, tech):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: tech)
        return generate_trade_setup("NIFTY")

    def test_bull_signal(self, monkeypatch):
        r = self._setup(monkeypatch, BULL)
        assert r["signal"] == "BUY"

    def test_bear_signal(self, monkeypatch):
        r = self._setup(monkeypatch, BEAR)
        assert r["signal"] == "SELL"

    def test_neutral_signal(self, monkeypatch):
        r = self._setup(monkeypatch, NEUT)
        assert r["signal"] == "NEUTRAL"

    def test_neutral_bullish_signal(self, monkeypatch):
        r = self._setup(monkeypatch, RANGE)
        # RANGE: price>ema20(+15)+price>ema50(+15)+macd>sig(+20)=50 → NEUTRAL_BULLISH
        assert r["signal"] == "NEUTRAL_BULLISH"

    def test_neutral_bearish_signal(self, monkeypatch):
        r = self._setup(monkeypatch, RNG_SELL)
        assert r["signal"] == "NEUTRAL_BEARISH"

    def test_legacy_schema_always_present(self, monkeypatch):
        """Regression: entry/stoploss/target must be present in all signal paths."""
        for tech in (BULL, BEAR, RANGE, NEUT):
            r = self._setup(monkeypatch, tech)
            assert "entry" in r, f"missing 'entry' for signal {r.get('signal')}"
            assert "stoploss" in r
            assert "target" in r

    def test_zone_schema_always_present(self, monkeypatch):
        """Regression: zone fields must be present alongside legacy fields."""
        for tech in (BULL, BEAR, RANGE, NEUT):
            r = self._setup(monkeypatch, tech)
            for field in ("entry_above", "entry_below", "bull_target", "bear_target"):
                assert field in r, f"missing '{field}' for signal {r.get('signal')}"

    def test_reasoning_is_list(self, monkeypatch):
        r = self._setup(monkeypatch, BULL)
        assert isinstance(r["reasoning"], list)
        assert len(r["reasoning"]) > 0

    def test_confidence_between_0_and_85(self, monkeypatch):
        for tech in (BULL, BEAR, RANGE, NEUT):
            r = self._setup(monkeypatch, tech)
            assert 0 <= r["confidence"] <= 85

    def test_buy_entry_above_spot(self, monkeypatch):
        r = self._setup(monkeypatch, BULL)
        assert r["signal"] == "BUY"
        assert r["entry"] == pytest.approx(r["entry_above"], rel=1e-4)

    def test_sell_entry_below_spot(self, monkeypatch):
        r = self._setup(monkeypatch, BEAR)
        assert r["signal"] == "SELL"
        assert r["entry"] == pytest.approx(r["entry_below"], rel=1e-4)

    def test_error_propagation(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: {"error": "no data"})
        r = generate_trade_setup("NIFTY")
        assert "error" in r

    def test_rsi_overbought_adds_bearish_not_bullish(self, monkeypatch):
        r = self._setup(monkeypatch, OVERBOUGHT)
        reasoning_text = " ".join(r.get("reasoning", []))
        assert "overbought" in reasoning_text.lower(), (
            "RSI > 70 must include overbought warning in reasoning"
        )
        assert r["confidence"] <= 85
        assert r["signal"] == "BUY", (
            "Other bullish indicators must dominate RSI overbought penalty: "
            f"signal was {r['signal']}"
        )

    def test_rsi_near_70_adds_boundary_caution(self, monkeypatch):
        import src.analysis.regime as regime
        near = _tech("NIFTY", rsi=71.0, ema20=100.0, ema50=90.0, adx=30.0, price=101.0)
        monkeypatch.setattr(regime, "_analyze_technicals",
                            lambda s, lookback_days=150: near)
        r = generate_trade_setup("NIFTY")
        assert any("boundary" in line.lower() for line in r["reasoning"])

    def test_rsi_mid_range_no_boundary_caution(self, monkeypatch):
        import src.analysis.regime as regime
        mid = _tech("NIFTY", rsi=60.0, ema20=100.0, ema50=90.0, adx=30.0, price=101.0)
        monkeypatch.setattr(regime, "_analyze_technicals",
                            lambda s, lookback_days=150: mid)
        r = generate_trade_setup("NIFTY")
        assert not any("boundary" in line.lower() for line in r["reasoning"])

    def test_rsi_oversold_adds_bullish_not_bearish(self, monkeypatch):
        r = self._setup(monkeypatch, OVERSOLD_BEAR)
        reasoning_text = " ".join(r.get("reasoning", []))
        assert "oversold" in reasoning_text.lower(), (
            "RSI < 30 must include oversold note in reasoning"
        )
        assert r["confidence"] <= 85
        assert r["signal"] == "SELL", (
            "Other bearish indicators must dominate RSI oversold bounce: "
            f"signal was {r['signal']}"
        )


# ---------------------------------------------------------------------------
# recommend_strategy — mocks detect_market_regime + generate_trade_setup
# ---------------------------------------------------------------------------

def _mock_regime(regime, rsi, adx):
    return {
        "symbol": "NIFTY", "regime": regime, "rsi": rsi, "adx": adx,
        "confidence": 70, "price": 100.0, "ema20": 100.0, "ema50": 98.0, "atr": 2.0,
    }


def _mock_setup(signal, confidence=70):
    return {
        "symbol": "NIFTY", "signal": signal, "confidence": confidence,
        "entry": 101.0, "stoploss": 98.0, "target": 106.0,
        "entry_above": 101.0, "entry_below": 99.5,
        "bull_target": 106.0, "bear_target": 95.0, "reasoning": [],
    }


class TestRecommendStrategy:

    def _apply(self, monkeypatch, regime_name, rsi, adx, signal):
        monkeypatch.setattr("src.analysis.regime.detect_market_regime",
                            lambda s: _mock_regime(regime_name, rsi, adx))
        monkeypatch.setattr("src.analysis.regime.generate_trade_setup",
                            lambda s: _mock_setup(signal))
        return recommend_strategy("NIFTY")

    def test_bull_trend_high_rsi_long_call(self, monkeypatch):
        r = self._apply(monkeypatch, "BULL_TREND", rsi=65.0, adx=30.0, signal="BUY")
        assert r["recommended"] == "Long Call"

    def test_bull_trend_low_rsi_bull_spread(self, monkeypatch):
        r = self._apply(monkeypatch, "BULL_TREND", rsi=55.0, adx=30.0, signal="BUY")
        assert r["recommended"] == "Bull Call Spread"

    def test_bear_trend_low_rsi_long_put(self, monkeypatch):
        r = self._apply(monkeypatch, "BEAR_TREND", rsi=35.0, adx=28.0, signal="SELL")
        assert r["recommended"] == "Long Put"

    def test_bear_trend_high_rsi_bear_spread(self, monkeypatch):
        r = self._apply(monkeypatch, "BEAR_TREND", rsi=50.0, adx=28.0, signal="SELL")
        assert r["recommended"] == "Bear Put Spread"

    def test_range_bound_neutral_iron_condor(self, monkeypatch):
        r = self._apply(monkeypatch, "RANGE_BOUND", rsi=50.0, adx=15.0, signal="NEUTRAL")
        assert r["recommended"] == "Iron Condor"

    def test_neutral_bullish_signal_bull_spread(self, monkeypatch):
        r = self._apply(monkeypatch, "RANGE_BOUND", rsi=50.0, adx=15.0,
                        signal="NEUTRAL_BULLISH")
        assert r["recommended"] == "Bull Call Spread"

    def test_neutral_bearish_signal_bear_spread(self, monkeypatch):
        r = self._apply(monkeypatch, "RANGE_BOUND", rsi=50.0, adx=15.0,
                        signal="NEUTRAL_BEARISH")
        assert r["recommended"] == "Bear Put Spread"

    def test_breakout_high_adx_long_straddle(self, monkeypatch):
        r = self._apply(monkeypatch, "BREAKOUT_POTENTIAL", rsi=60.0, adx=23.0,
                        signal="NEUTRAL")
        assert r["recommended"] == "Long Straddle"

    def test_breakout_low_adx_long_strangle(self, monkeypatch):
        r = self._apply(monkeypatch, "BREAKOUT_POTENTIAL", rsi=60.0, adx=22.0,
                        signal="NEUTRAL")
        assert r["recommended"] == "Long Strangle"

    def test_returns_strategy_key_for_compat(self, monkeypatch):
        """Dashboard reads strat_result.get('strategy') — both keys must exist."""
        r = self._apply(monkeypatch, "BULL_TREND", rsi=65.0, adx=30.0, signal="BUY")
        assert "strategy" in r
        assert "recommended" in r
        assert r["strategy"] == r["recommended"]

    def test_returns_signal_and_regime(self, monkeypatch):
        r = self._apply(monkeypatch, "BULL_TREND", rsi=65.0, adx=30.0, signal="BUY")
        assert r["signal"] == "BUY"
        assert r["regime"] == "BULL_TREND"

    # --- Phase 4.1 conflict-resolution regression ---

    def test_buy_range_bound_gives_bull_spread_not_iron_condor(self, monkeypatch):
        r = self._apply(monkeypatch, "RANGE_BOUND", rsi=65.0, adx=15.0, signal="BUY")
        assert r["recommended"] == "Bull Call Spread"
        assert r["recommended"] != "Iron Condor"
        assert r.get("secondary") == "Iron Condor"  # Iron Condor demoted to secondary

    def test_sell_range_bound_gives_bear_spread_not_iron_condor(self, monkeypatch):
        r = self._apply(monkeypatch, "RANGE_BOUND", rsi=35.0, adx=15.0, signal="SELL")
        assert r["recommended"] == "Bear Put Spread"
        assert r["recommended"] != "Iron Condor"
        assert r.get("secondary") == "Iron Condor"


# ---------------------------------------------------------------------------
# TestConfidenceScale — B1 (Phase 14.6): one 0–85 scale, rescaled not clamped
# ---------------------------------------------------------------------------

class TestConfidenceScale:
    def test_scale_helper_maps_band(self):
        from src.analysis.regime import _scale_confidence, MAX_CONFIDENCE
        assert _scale_confidence(100) == MAX_CONFIDENCE == 85
        assert _scale_confidence(0) == 0
        # No flat top below the ceiling: distinct internal scores stay distinct.
        assert _scale_confidence(80) < _scale_confidence(100)
        assert _scale_confidence(60) < _scale_confidence(80)

    def test_regime_confidence_within_band(self, monkeypatch):
        import src.analysis.regime as regime
        monkeypatch.setattr(regime, "_analyze_technicals",
                            lambda s, lookback_days=150: BULL)
        r = detect_market_regime("NIFTY")
        assert 0 <= r["confidence"] <= 85

    def test_setup_confidence_within_band(self, monkeypatch):
        import src.analysis.regime as regime
        monkeypatch.setattr(regime, "_analyze_technicals",
                            lambda s, lookback_days=150: BULL)
        r = generate_trade_setup("NIFTY")
        assert 0 <= r["confidence"] <= 85

    def test_regime_and_setup_share_ceiling(self, monkeypatch):
        import src.analysis.regime as regime
        strong = _tech("NIFTY", rsi=68.0, ema20=100.0, ema50=90.0, adx=40.0, price=101.0)
        monkeypatch.setattr(regime, "_analyze_technicals",
                            lambda s, lookback_days=150: strong)
        assert detect_market_regime("NIFTY")["confidence"] <= 85
        assert generate_trade_setup("NIFTY")["confidence"] <= 85


# ---------------------------------------------------------------------------
# TestDataBasis — B4 (Phase 14.6): provenance surfaced from real candles
# ---------------------------------------------------------------------------

class TestDataBasis:
    def _candles(self, n=160, last_date="2026-06-15"):
        # Rising series so all indicators are valid; last candle dated for staleness.
        candles = [
            {"date": f"2026-01-{(i % 28) + 1:02d}T00:00:00",
             "open": 100.0 + i, "high": 102.0 + i, "low": 99.0 + i,
             "close": 100.5 + i, "volume": 1000}
            for i in range(n)
        ]
        candles[-1]["date"] = f"{last_date}T00:00:00"
        return candles

    def test_setup_includes_data_basis(self, monkeypatch):
        import src.analysis.regime as regime
        monkeypatch.setattr(regime, "_load_candles", lambda s, l: self._candles())
        r = generate_trade_setup("NIFTY")
        assert "data_basis" in r
        assert r["data_basis"]["source"] == "yfinance_eod_adjusted"
        assert r["data_basis"]["last_candle_date"].startswith("2026-06-15")
        assert isinstance(r["data_basis"]["staleness_days"], int)

    def test_staleness_helper(self):
        from src.analysis.regime import _staleness_days
        from datetime import date, timedelta
        five_ago = (date.today() - timedelta(days=5)).isoformat()
        assert _staleness_days(five_ago) == 5
        assert _staleness_days(None) is None
        assert _staleness_days("not-a-date") is None


# ---------------------------------------------------------------------------
# TestAnalysisCache — C1 (Phase 14.6): one fetch per (symbol, lookback) flow
# ---------------------------------------------------------------------------

class TestAnalysisCache:
    def _candles(self, n=160):
        return [
            {"date": f"2026-01-{(i % 28) + 1:02d}T00:00:00",
             "open": 100.0 + i, "high": 102.0 + i, "low": 99.0 + i,
             "close": 100.5 + i, "volume": 1000}
            for i in range(n)
        ]

    def test_repeated_calls_fetch_once(self, monkeypatch):
        import src.analysis.regime as regime
        calls = {"n": 0}

        def _counting_loader(symbol, lookback):
            calls["n"] += 1
            return self._candles()

        monkeypatch.setattr(regime, "_load_candles", _counting_loader)
        regime.clear_analysis_cache()

        # A single setup triggers setup + regime (+ strategy via recommend paths);
        # all share one cached fetch for the same (symbol, lookback).
        regime.generate_trade_setup("NIFTY")
        regime.detect_market_regime("NIFTY")
        assert calls["n"] == 1, "repeated analysis must reuse one cached fetch"

    def test_clear_cache_forces_refetch(self, monkeypatch):
        import src.analysis.regime as regime
        calls = {"n": 0}

        def _counting_loader(symbol, lookback):
            calls["n"] += 1
            return self._candles()

        monkeypatch.setattr(regime, "_load_candles", _counting_loader)
        regime.clear_analysis_cache()

        regime.detect_market_regime("NIFTY")
        regime.clear_analysis_cache()
        regime.detect_market_regime("NIFTY")
        assert calls["n"] == 2, "clearing the cache must force a fresh fetch"
