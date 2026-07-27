"""Regression tests for Audit-H4 — strategy builder must flag wide bid-ask
spreads / thin open interest instead of silently trusting lastPrice.

Finding: _build_pmap only read lastPrice/ltp; the chain payload already
carries bidprice/askPrice/openInterest (used elsewhere, e.g. tools/options.py)
but _select_legs/_calc_payoff never consulted them, so is_estimate=False could
be returned for a strike whose lastPrice is a stale, unrepresentative print
far from what a real order would fill at.

LQ-1  a leg with a wide bid-ask spread produces a liquidity_warning
LQ-2  a leg with thin OI produces a liquidity_warning
LQ-3  a leg with neither wide spread nor thin OI produces no warning
LQ-4  missing bid/ask/OI data never fabricates a warning
LQ-5  build_option_strategy surfaces liquidity_warning and downgrades is_estimate
       to True when any leg is illiquid, even though real premiums were found
LQ-6  a fully liquid chain keeps is_estimate=False (no regression)
"""
from __future__ import annotations

from src.strategy.builder import (
    _build_liquidity_map,
    _leg_liquidity_warning,
    build_option_strategy,
)

EXPIRY = "26-Jun-2025"
SPOT = 24000.0


def _row(strike, ce_ltp, pe_ltp, *, ce_bid=None, ce_ask=None, ce_oi=10000,
         pe_bid=None, pe_ask=None, pe_oi=10000, expiry=EXPIRY):
    ce = {"openInterest": ce_oi, "lastPrice": ce_ltp}
    if ce_bid is not None:
        ce["bidprice"] = ce_bid
    if ce_ask is not None:
        ce["askPrice"] = ce_ask
    pe = {"openInterest": pe_oi, "lastPrice": pe_ltp}
    if pe_bid is not None:
        pe["bidprice"] = pe_bid
    if pe_ask is not None:
        pe["askPrice"] = pe_ask
    return {"strikePrice": strike, "expiryDate": expiry, "CE": ce, "PE": pe}


def _chain(rows, spot=SPOT, expiry=EXPIRY):
    return {
        "records": {
            "data": rows,
            "expiryDates": [expiry, "03-Jul-2025"],
            "underlyingValue": spot,
        }
    }


class TestLQ1WideSpread:
    def test_wide_spread_produces_warning(self):
        rows = [_row(24000, 100.0, 100.0, ce_bid=80.0, ce_ask=120.0)]  # 40% spread of mid=100
        liq = _build_liquidity_map(_chain(rows), EXPIRY)
        warning = _leg_liquidity_warning(24000, "CE", liq)
        assert warning is not None
        assert "spread" in warning

    def test_narrow_spread_no_warning_from_spread(self):
        rows = [_row(24000, 100.0, 100.0, ce_bid=99.0, ce_ask=101.0)]  # 2% spread
        liq = _build_liquidity_map(_chain(rows), EXPIRY)
        warning = _leg_liquidity_warning(24000, "CE", liq)
        assert warning is None


class TestLQ2ThinOi:
    def test_thin_oi_produces_warning(self):
        rows = [_row(24000, 100.0, 100.0, ce_oi=50)]
        liq = _build_liquidity_map(_chain(rows), EXPIRY)
        warning = _leg_liquidity_warning(24000, "CE", liq)
        assert warning is not None
        assert "OI" in warning

    def test_healthy_oi_no_warning(self):
        rows = [_row(24000, 100.0, 100.0, ce_oi=50000)]
        liq = _build_liquidity_map(_chain(rows), EXPIRY)
        warning = _leg_liquidity_warning(24000, "CE", liq)
        assert warning is None


class TestLQ3NoWarningWhenLiquid:
    def test_liquid_leg_no_warning(self):
        rows = [_row(24000, 100.0, 100.0, ce_bid=99.5, ce_ask=100.5, ce_oi=20000)]
        liq = _build_liquidity_map(_chain(rows), EXPIRY)
        assert _leg_liquidity_warning(24000, "CE", liq) is None


class TestLQ4MissingDataNoFabrication:
    def test_no_bid_ask_data_no_warning(self):
        # openInterest present and healthy, but bid/ask absent entirely —
        # must not fabricate a spread warning from missing fields.
        rows = [_row(24000, 100.0, 100.0, ce_oi=20000)]
        liq = _build_liquidity_map(_chain(rows), EXPIRY)
        assert _leg_liquidity_warning(24000, "CE", liq) is None

    def test_unknown_strike_no_warning(self):
        rows = [_row(24000, 100.0, 100.0)]
        liq = _build_liquidity_map(_chain(rows), EXPIRY)
        assert _leg_liquidity_warning(99999, "CE", liq) is None


class TestLQ5And6IntegrationViaBuildOptionStrategy:
    def _tech_bull(self):
        return {
            "symbol": "NIFTY", "last_close": 100.0, "candles_used": 150,
            "rsi_14": 65.0, "ema_20": 100.0, "ema_50": 90.0,
            "macd": {"macd": 0.5, "signal": 0.3, "histogram": 0.2},
            "adx_14": {"adx": 30.0, "plus_di": 28.0, "minus_di": 12.0},
            "atr_14": 2.0,
        }

    def _patch(self, monkeypatch, chain_data):
        from unittest.mock import MagicMock
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: self._tech_bull())
        svc = MagicMock()
        svc.get_option_chain.return_value = chain_data
        monkeypatch.setattr("src.strategy.builder.get_options_service", lambda: svc)

        class _svc_that_raises:
            def get_option_chain(self, *a, **kw):
                raise RuntimeError("no chain needed for this test")
        monkeypatch.setattr("src.planner.trade_plan.get_options_service",
                            lambda: _svc_that_raises())

    def test_illiquid_leg_downgrades_is_estimate_and_sets_warning(self, monkeypatch):
        strikes = list(range(23000, 25100, 100))
        rows = [
            _row(
                s,
                round(max(0.5, (25100 - s) * 0.12 + 3), 2),
                round(max(0.5, (s - 22900) * 0.12 + 3), 2),
                ce_bid=1.0, ce_ask=5.0,  # wide spread on every CE leg
                ce_oi=10000, pe_oi=10000,
            )
            for s in strikes
        ]
        self._patch(monkeypatch, _chain(rows))
        r = build_option_strategy("NIFTY")
        if r["premium_data_available"] and any(l["option_type"] == "CE" for l in r["legs"]):
            assert r["is_estimate"] is True
            assert r["liquidity_warning"] is not None
            assert "Liquidity caution" in r["summary"]

    def test_liquid_chain_keeps_is_estimate_false(self, monkeypatch):
        strikes = list(range(23000, 25100, 100))
        rows = [
            _row(
                s,
                round(max(0.5, (25100 - s) * 0.12 + 3), 2),
                round(max(0.5, (s - 22900) * 0.12 + 3), 2),
                ce_bid=None, ce_ask=None,  # no liquidity data at all — must not fabricate a warning
                ce_oi=20000, pe_oi=20000,
            )
            for s in strikes
        ]
        self._patch(monkeypatch, _chain(rows))
        r = build_option_strategy("NIFTY")
        if r["premium_data_available"]:
            assert r["liquidity_warning"] is None
            assert r["is_estimate"] is False
