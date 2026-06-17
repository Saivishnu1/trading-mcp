"""
Unit and integration tests for src/strategy/builder.py.

Helper function tests are pure (no I/O).
_calc_payoff tests use known premium values for deterministic assertions.
build_option_strategy integration mocks _analyze_technicals + options service.
"""
import pytest

from src.strategy.builder import (
    _atm,
    _atm_ce,
    _atm_pe,
    _build_pmap,
    _calc_payoff,
    _interval,
    _nearest,
    _select_legs,
    _sorted_strikes,
    build_option_strategy,
)

EXPIRY = "26-Jun-2025"
SPOT = 24000.0

# ---------------------------------------------------------------------------
# Synthetic chain helpers (minimal, no NSE calls)
# ---------------------------------------------------------------------------

def _row(strike, ce_ltp, pe_ltp, expiry=EXPIRY):
    return {
        "strikePrice": strike,
        "expiryDate": expiry,
        "CE": {"openInterest": 10000, "lastPrice": ce_ltp},
        "PE": {"openInterest": 10000, "lastPrice": pe_ltp},
    }


def _chain(strikes_and_premiums, spot=SPOT, expiry=EXPIRY):
    rows = [_row(s, ce, pe, expiry) for s, ce, pe in strikes_and_premiums]
    return {
        "records": {
            "data": rows,
            "expiryDates": [expiry, "03-Jul-2025"],
            "underlyingValue": spot,
        }
    }


STRIKES_100 = list(range(23000, 25100, 100))

# Full chain: strikes 23000–25000 at 100-pt intervals
FULL_CHAIN = _chain(
    [(s, round(max(0.5, (25100 - s) * 0.12 + 3), 2),
       round(max(0.5, (s - 22900) * 0.12 + 3), 2))
     for s in STRIKES_100]
)


# ---------------------------------------------------------------------------
# Strike helpers — pure functions
# ---------------------------------------------------------------------------

class TestSortedStrikes:

    def test_returns_sorted_list(self, chain_data):
        strikes = _sorted_strikes(chain_data, EXPIRY)
        assert strikes == sorted(strikes)

    def test_returns_floats(self, chain_data):
        strikes = _sorted_strikes(chain_data, EXPIRY)
        assert all(isinstance(s, float) for s in strikes)

    def test_filters_by_expiry(self, chain_data):
        strikes = _sorted_strikes(chain_data, "31-Dec-9999")
        assert strikes == []

    def test_range_correct(self, chain_data):
        strikes = _sorted_strikes(chain_data, EXPIRY)
        assert min(strikes) == 23000.0
        assert max(strikes) == 25000.0


class TestInterval:

    def test_100pt_interval(self):
        strikes = [float(s) for s in STRIKES_100]
        assert _interval(strikes) == 100.0

    def test_50pt_interval(self):
        strikes = [23000.0, 23050.0, 23100.0, 23150.0]
        assert _interval(strikes) == 50.0

    def test_single_strike_returns_default(self):
        assert _interval([24000.0]) == 50.0

    def test_empty_returns_default(self):
        assert _interval([]) == 50.0


class TestNearest:

    def test_exact_match(self):
        strikes = [23000.0, 24000.0, 25000.0]
        assert _nearest(strikes, 24000.0) == 24000.0

    def test_rounds_down(self):
        strikes = [23000.0, 24000.0, 25000.0]
        assert _nearest(strikes, 23400.0) == 23000.0

    def test_rounds_up(self):
        strikes = [23000.0, 24000.0, 25000.0]
        assert _nearest(strikes, 24600.0) == 25000.0


class TestAtmCe:

    def test_atm_ce_is_at_or_above_spot(self):
        strikes = [float(s) for s in STRIKES_100]
        result = _atm_ce(strikes, SPOT)
        assert result >= SPOT

    def test_atm_ce_at_exact_strike(self):
        strikes = [23000.0, 24000.0, 25000.0]
        assert _atm_ce(strikes, 24000.0) == 24000.0

    def test_atm_ce_rounds_up(self):
        strikes = [23000.0, 24000.0, 25000.0]
        assert _atm_ce(strikes, 23500.0) == 24000.0


class TestAtmPe:

    def test_atm_pe_is_at_or_below_spot(self):
        strikes = [float(s) for s in STRIKES_100]
        result = _atm_pe(strikes, SPOT)
        assert result <= SPOT

    def test_atm_pe_at_exact_strike(self):
        strikes = [23000.0, 24000.0, 25000.0]
        assert _atm_pe(strikes, 24000.0) == 24000.0

    def test_atm_pe_rounds_down(self):
        strikes = [23000.0, 24000.0, 25000.0]
        assert _atm_pe(strikes, 24500.0) == 24000.0


# ---------------------------------------------------------------------------
# _build_pmap — pure function
# ---------------------------------------------------------------------------

class TestBuildPmap:

    def test_maps_strike_and_type_to_premium(self):
        chain = _chain([(24000, 150.0, 100.0)])
        pmap = _build_pmap(chain, EXPIRY)
        assert pmap.get((24000.0, "CE")) == pytest.approx(150.0)
        assert pmap.get((24000.0, "PE")) == pytest.approx(100.0)

    def test_ignores_zero_premiums(self):
        chain = _chain([(24000, 0.0, 100.0)])
        pmap = _build_pmap(chain, EXPIRY)
        assert (24000.0, "CE") not in pmap
        assert (24000.0, "PE") in pmap

    def test_ignores_wrong_expiry(self):
        chain = _chain([(24000, 150.0, 100.0)])
        pmap = _build_pmap(chain, "31-Dec-9999")
        assert len(pmap) == 0


# ---------------------------------------------------------------------------
# _calc_payoff — pure function, known premium values
# ---------------------------------------------------------------------------

class TestCalcPayoff:

    def test_bull_call_spread(self):
        legs = [
            {"action": "BUY",  "strike": 24000.0, "option_type": "CE"},
            {"action": "SELL", "strike": 24400.0, "option_type": "CE"},
        ]
        pmap = {(24000.0, "CE"): 100.0, (24400.0, "CE"): 50.0}
        r = _calc_payoff("Bull Call Spread", legs, pmap)
        assert r["is_estimate"] is False
        assert r["net_debit"] == pytest.approx(50.0)
        assert r["max_loss"] == pytest.approx(50.0)
        assert r["max_profit"] == pytest.approx(350.0)   # spread 400 - debit 50
        assert r["upper_breakeven"] == pytest.approx(24050.0)  # buy_strike + debit

    def test_bear_put_spread(self):
        legs = [
            {"action": "BUY",  "strike": 24000.0, "option_type": "PE"},
            {"action": "SELL", "strike": 23600.0, "option_type": "PE"},
        ]
        pmap = {(24000.0, "PE"): 100.0, (23600.0, "PE"): 50.0}
        r = _calc_payoff("Bear Put Spread", legs, pmap)
        assert r["is_estimate"] is False
        assert r["net_debit"] == pytest.approx(50.0)
        assert r["max_profit"] == pytest.approx(350.0)
        assert r["upper_breakeven"] == pytest.approx(23950.0)  # 24000 - 50

    def test_long_call(self):
        legs = [{"action": "BUY", "strike": 24000.0, "option_type": "CE"}]
        pmap = {(24000.0, "CE"): 80.0}
        r = _calc_payoff("Long Call", legs, pmap)
        assert r["is_estimate"] is False
        assert r["max_loss"] == pytest.approx(80.0)
        assert r["max_profit"] == "unlimited"
        assert r["upper_breakeven"] == pytest.approx(24080.0)

    def test_long_put(self):
        legs = [{"action": "BUY", "strike": 24000.0, "option_type": "PE"}]
        pmap = {(24000.0, "PE"): 80.0}
        r = _calc_payoff("Long Put", legs, pmap)
        assert r["is_estimate"] is False
        assert r["max_loss"] == pytest.approx(80.0)
        assert r["max_profit"] == pytest.approx(23920.0)   # strike - premium
        assert r["upper_breakeven"] == pytest.approx(23920.0)

    def test_long_straddle(self):
        legs = [
            {"action": "BUY", "strike": 24000.0, "option_type": "CE"},
            {"action": "BUY", "strike": 24000.0, "option_type": "PE"},
        ]
        pmap = {(24000.0, "CE"): 60.0, (24000.0, "PE"): 40.0}
        r = _calc_payoff("Long Straddle", legs, pmap)
        assert r["is_estimate"] is False
        assert r["max_loss"] == pytest.approx(100.0)
        assert r["upper_breakeven"] == pytest.approx(24100.0)
        assert r["lower_breakeven"] == pytest.approx(23900.0)

    def test_long_strangle(self):
        legs = [
            {"action": "BUY", "strike": 24200.0, "option_type": "CE"},
            {"action": "BUY", "strike": 23800.0, "option_type": "PE"},
        ]
        pmap = {(24200.0, "CE"): 30.0, (23800.0, "PE"): 30.0}
        r = _calc_payoff("Long Strangle", legs, pmap)
        assert r["is_estimate"] is False
        assert r["max_loss"] == pytest.approx(60.0)
        assert r["upper_breakeven"] == pytest.approx(24260.0)   # ce_strike + total
        assert r["lower_breakeven"] == pytest.approx(23740.0)   # pe_strike - total

    def test_iron_condor(self):
        # SELL CE 24500, BUY CE 24900, SELL PE 23500, BUY PE 23100
        legs = [
            {"action": "SELL", "strike": 24500.0, "option_type": "CE"},
            {"action": "BUY",  "strike": 24900.0, "option_type": "CE"},
            {"action": "SELL", "strike": 23500.0, "option_type": "PE"},
            {"action": "BUY",  "strike": 23100.0, "option_type": "PE"},
        ]
        pmap = {
            (24500.0, "CE"): 80.0, (24900.0, "CE"): 30.0,
            (23500.0, "PE"): 60.0, (23100.0, "PE"): 20.0,
        }
        r = _calc_payoff("Iron Condor", legs, pmap)
        assert r["is_estimate"] is False
        # net_credit = (80-30) + (60-20) = 90
        assert r["net_credit"] == pytest.approx(90.0)
        assert r["max_profit"] == pytest.approx(90.0)
        # max_risk = max(400, 400) = 400 → max_loss = 400-90 = 310
        assert r["max_loss"] == pytest.approx(310.0)
        assert r["upper_breakeven"] == pytest.approx(24590.0)  # 24500 + 90
        assert r["lower_breakeven"] == pytest.approx(23410.0)  # 23500 - 90

    def test_missing_premium_returns_estimate(self):
        legs = [{"action": "BUY", "strike": 24000.0, "option_type": "CE"}]
        pmap = {}   # no premiums
        r = _calc_payoff("Long Call", legs, pmap)
        assert r["is_estimate"] is True

    def test_unknown_strategy_returns_estimate(self):
        r = _calc_payoff("Unknown Strategy", [], {})
        assert r["is_estimate"] is True


# ---------------------------------------------------------------------------
# _select_legs — pure function
# ---------------------------------------------------------------------------

class TestSelectLegs:

    def _strikes(self):
        return [float(s) for s in STRIKES_100]

    def test_long_call_one_leg(self):
        legs = _select_legs("Long Call", SPOT, self._strikes(), 100.0, FULL_CHAIN, EXPIRY)
        assert len(legs) == 1
        assert legs[0]["action"] == "BUY"
        assert legs[0]["option_type"] == "CE"

    def test_long_put_one_leg(self):
        legs = _select_legs("Long Put", SPOT, self._strikes(), 100.0, FULL_CHAIN, EXPIRY)
        assert len(legs) == 1
        assert legs[0]["action"] == "BUY"
        assert legs[0]["option_type"] == "PE"

    def test_bull_call_spread_two_legs(self):
        legs = _select_legs("Bull Call Spread", SPOT, self._strikes(), 100.0, FULL_CHAIN, EXPIRY)
        assert len(legs) == 2
        assert legs[0]["option_type"] == "CE"
        assert legs[1]["option_type"] == "CE"
        assert legs[0]["action"] == "BUY"
        assert legs[1]["action"] == "SELL"
        assert legs[1]["strike"] > legs[0]["strike"]  # short strike above long

    def test_bear_put_spread_two_legs(self):
        legs = _select_legs("Bear Put Spread", SPOT, self._strikes(), 100.0, FULL_CHAIN, EXPIRY)
        assert len(legs) == 2
        assert legs[0]["option_type"] == "PE"
        assert legs[1]["option_type"] == "PE"
        assert legs[0]["action"] == "BUY"
        assert legs[1]["action"] == "SELL"
        assert legs[0]["strike"] > legs[1]["strike"]  # long strike above short

    def test_long_straddle_two_legs_same_strike(self):
        legs = _select_legs("Long Straddle", SPOT, self._strikes(), 100.0, FULL_CHAIN, EXPIRY)
        assert len(legs) == 2
        assert legs[0]["strike"] == legs[1]["strike"]

    def test_long_strangle_two_legs_different_strikes(self):
        legs = _select_legs("Long Strangle", SPOT, self._strikes(), 100.0, FULL_CHAIN, EXPIRY)
        assert len(legs) == 2
        assert legs[0]["strike"] != legs[1]["strike"]

    def test_iron_condor_four_legs(self):
        legs = _select_legs("Iron Condor", SPOT, self._strikes(), 100.0, FULL_CHAIN, EXPIRY)
        assert len(legs) == 4

    def test_unknown_strategy_no_legs(self):
        legs = _select_legs("Unknown", SPOT, self._strikes(), 100.0, FULL_CHAIN, EXPIRY)
        assert legs == []


# ---------------------------------------------------------------------------
# build_option_strategy — integration
# ---------------------------------------------------------------------------

def _tech_bull():
    return {
        "symbol": "NIFTY", "last_close": 100.0, "candles_used": 150,
        "rsi_14": 65.0, "ema_20": 100.0, "ema_50": 90.0,
        "macd": {"macd": 0.5, "signal": 0.3, "histogram": 0.2},
        "adx_14": {"adx": 30.0, "plus_di": 28.0, "minus_di": 12.0},
        "atr_14": 2.0,
    }


def _tech_neutral():
    return {
        "symbol": "NIFTY", "last_close": 100.0, "candles_used": 150,
        "rsi_14": 50.0, "ema_20": 100.0, "ema_50": 100.0,
        "macd": {"macd": 0.1, "signal": 0.1, "histogram": 0.0},
        "adx_14": {"adx": 15.0, "plus_di": 15.0, "minus_di": 15.0},
        "atr_14": 1.5,
    }


class TestBuildOptionStrategy:

    def _patch(self, monkeypatch, tech, chain_data):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: tech)
        from unittest.mock import MagicMock
        svc = MagicMock()
        svc.get_option_chain.return_value = chain_data
        monkeypatch.setattr("src.strategy.builder.get_options_service", lambda: svc)
        monkeypatch.setattr("src.planner.trade_plan.get_options_service",
                            lambda: _svc_that_raises())
        return svc

    def test_returns_required_keys(self, monkeypatch, chain_data):
        self._patch(monkeypatch, _tech_bull(), chain_data)
        r = build_option_strategy("NIFTY")
        for key in ("symbol", "strategy", "expiry", "spot_price", "signal",
                    "premium_data_available", "legs", "is_estimate", "summary"):
            assert key in r

    def test_bull_trend_premium_available(self, monkeypatch, chain_data):
        self._patch(monkeypatch, _tech_bull(), chain_data)
        r = build_option_strategy("NIFTY")
        assert r["premium_data_available"] is True
        assert len(r["legs"]) > 0

    def test_legs_have_premium(self, monkeypatch, chain_data):
        self._patch(monkeypatch, _tech_bull(), chain_data)
        r = build_option_strategy("NIFTY")
        # Every leg with a non-None ltp should be a positive number
        for leg in r["legs"]:
            if leg.get("ltp") is not None:
                assert leg["ltp"] > 0

    def test_no_chain_degrades_gracefully(self, monkeypatch, chain_data):
        """If options service raises, builder returns empty-legs response, not an exception."""
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: _tech_bull())
        monkeypatch.setattr("src.strategy.builder.get_options_service",
                            lambda: _svc_that_raises())
        monkeypatch.setattr("src.planner.trade_plan.get_options_service",
                            lambda: _svc_that_raises())
        r = build_option_strategy("NIFTY")
        assert r["premium_data_available"] is False
        assert r["legs"] == []
        assert "summary" in r

    def test_symbol_uppercased(self, monkeypatch, chain_data):
        self._patch(monkeypatch, _tech_bull(), chain_data)
        r = build_option_strategy("nifty")
        assert r["symbol"] == "NIFTY"

    def test_iron_condor_four_legs(self, monkeypatch, chain_data):
        self._patch(monkeypatch, _tech_neutral(), chain_data)
        r = build_option_strategy("NIFTY")
        if r["strategy"] == "Iron Condor" and r["premium_data_available"]:
            assert len(r["legs"]) == 4


class _svc_that_raises:
    def get_option_chain(self, *a, **kw):
        raise RuntimeError("NSE unavailable in tests")
