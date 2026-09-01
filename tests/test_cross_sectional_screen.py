"""Tests for scripts/cross_sectional_screen.py — pure signal/outcome functions.

The highest-value guard here is no-lookahead: a signal at index i must use only
data at or before i, and the forward-excess outcome must use only data after i.
A crude screen that leaks the future would manufacture false alpha.
"""
from __future__ import annotations

import math

import pytest

import scripts.cross_sectional_screen as screen

# ---------------------------------------------------------------------------
# trailing_return
# ---------------------------------------------------------------------------

class TestTrailingReturn:
    def test_simple_6m_return(self):
        closes = [100.0] * 200
        closes[180] = 110.0
        # close[180] / close[180-126] - 1 = 110/100 - 1 = 0.10
        assert screen.trailing_return(closes, 180, 126, 0) == pytest.approx(0.10)

    def test_skip_month_uses_lagged_endpoint(self):
        closes = [100.0] * 300
        # RS_12m1 at i=290: close[290-21] / close[290-21-252] - 1
        # set close[269] = 120 -> 120/100 - 1 = 0.20, independent of close[290]
        closes[269] = 120.0
        closes[290] = 999.0  # most-recent-month value must NOT enter the signal
        assert screen.trailing_return(closes, 290, 252, 21) == pytest.approx(0.20)

    def test_none_when_insufficient_history(self):
        closes = [100.0] * 50
        assert screen.trailing_return(closes, 10, 126, 0) is None

    def test_none_on_nonpositive_base(self):
        closes = [0.0] + [100.0] * 200
        assert screen.trailing_return(closes, 126, 126, 0) is None


# ---------------------------------------------------------------------------
# realized_vol
# ---------------------------------------------------------------------------

class TestRealizedVol:
    def test_zero_vol_on_flat_series(self):
        closes = [100.0] * 100
        assert screen.realized_vol(closes, 80, 63) == 0.0

    def test_none_when_insufficient_history(self):
        closes = [100.0] * 30
        assert screen.realized_vol(closes, 10, 63) is None

    def test_matches_manual_stdev(self):
        # 5 closes -> 4 log returns; window=4 ending at i=4
        closes = [100.0, 101.0, 103.0, 102.0, 105.0]
        rets = [math.log(closes[k] / closes[k - 1]) for k in range(1, 5)]
        import statistics
        assert screen.realized_vol(closes, 4, 4) == statistics.stdev(rets)


# ---------------------------------------------------------------------------
# forward_excess
# ---------------------------------------------------------------------------

class TestForwardExcess:
    def test_excess_subtracts_benchmark(self):
        closes = [100.0, 0, 0, 0, 0, 110.0]            # stock +10% over 5 steps
        dates  = ["d0", "d1", "d2", "d3", "d4", "d5"]
        bench  = {"d0": 200.0, "d5": 208.0}             # bench +4% over same dates
        # excess = 0.10 - 0.04 = 0.06
        assert screen.forward_excess(closes, dates, bench, 0, 5) == pytest.approx(0.06)

    def test_none_when_benchmark_date_missing(self):
        closes = [100.0, 110.0]
        dates  = ["d0", "d1"]
        bench  = {"d0": 200.0}                           # d1 missing
        assert screen.forward_excess(closes, dates, bench, 0, 1) is None

    def test_none_when_forward_index_out_of_range(self):
        closes = [100.0, 110.0]
        dates  = ["d0", "d1"]
        bench  = {"d0": 200.0, "d1": 210.0}
        assert screen.forward_excess(closes, dates, bench, 1, 5) is None


# ---------------------------------------------------------------------------
# No-lookahead — the centerpiece guard
# ---------------------------------------------------------------------------

class TestNoLookahead:
    def test_signal_ignores_future_spike(self):
        # Flat history up to i; a spike AFTER i must not affect the signal at i.
        closes = [100.0] * 400
        i = 300
        closes[310] = 500.0  # future spike, 10 days ahead
        assert screen.trailing_return(closes, i, 126, 0) == 0.0
        assert screen.trailing_return(closes, i, 252, 21) == 0.0
        assert screen.realized_vol(closes, i, 63) == 0.0

    def test_forward_outcome_reflects_future(self):
        # The forward leg MUST see the future spike (sanity mirror of the above).
        closes = [100.0] * 400
        dates  = [f"d{k}" for k in range(400)]
        closes[310] = 200.0
        bench  = dict.fromkeys(dates, 100.0)  # flat benchmark
        # stock +100% at +10, bench flat -> excess = 1.0
        assert screen.forward_excess(closes, dates, bench, 300, 10) == 1.0


# ---------------------------------------------------------------------------
# quintile_index
# ---------------------------------------------------------------------------

class TestQuintileIndex:
    def test_boundaries_n50(self):
        assert screen.quintile_index(0, 50) == 0
        assert screen.quintile_index(9, 50) == 0
        assert screen.quintile_index(10, 50) == 1
        assert screen.quintile_index(49, 50) == 4

    def test_top_rank_clamped_to_four(self):
        assert screen.quintile_index(19, 20) == 4
        assert screen.quintile_index(99, 100) == 4


# ---------------------------------------------------------------------------
# build_symbol_panel — boundaries
# ---------------------------------------------------------------------------

def _candles(n: int, start_year: int = 2020) -> list[dict]:
    """Deterministic ascending daily candles (weekday-agnostic date strings)."""
    out = []
    for k in range(n):
        # Manufacture sortable ISO-ish date strings spanning years.
        year = start_year + k // 250
        doy  = k % 250
        date = f"{year}-{(doy // 30) + 1:02d}-{(doy % 30) + 1:02d}"
        price = 100.0 + k * 0.1
        out.append({"date": date, "open": price, "high": price,
                    "low": price, "close": price, "volume": 1000})
    return out


class TestBuildSymbolPanel:
    def test_no_row_before_screen_from(self):
        candles = _candles(900)
        bench = {c["date"][:10]: c["close"] for c in candles}
        rows = screen.build_symbol_panel("X.NS", candles, bench)
        assert all(r["date"] >= screen.SCREEN_FROM for r in rows)

    def test_tail_exclusion_leaves_forward_window(self):
        candles = _candles(900)
        bench = {c["date"][:10]: c["close"] for c in candles}
        rows = screen.build_symbol_panel("X.NS", candles, bench)
        # Every emitted row must have all three forward excess returns computable.
        assert rows, "expected some panel rows"
        assert all(r["exc_20"] is not None for r in rows)


# ---------------------------------------------------------------------------
# aggregate / monotonicity / verdict
# ---------------------------------------------------------------------------

class TestAggregateAndVerdict:
    def test_is_monotone(self):
        assert screen.is_monotone([-0.3, -0.1, 0.05, 0.2, 0.55]) is True
        assert screen.is_monotone([0.5, -0.1, 0.05, 0.2, 0.55]) is False

    def test_dead_signal_verdict(self):
        spreads = {"rs_6m": 0.05, "rs_12m1": 0.10, "vol_63": 0.0}
        monos   = {"rs_6m": False, "rs_12m1": False, "vol_63": False}
        assert "DEAD" in screen.momentum_verdict(spreads, monos)

    def test_large_effect_verdict(self):
        spreads = {"rs_6m": 1.1, "rs_12m1": 0.9, "vol_63": 0.0}
        monos   = {"rs_6m": True, "rs_12m1": True, "vol_63": False}
        assert "LARGE EFFECT" in screen.momentum_verdict(spreads, monos)

    def test_suspiciously_large_flagged(self):
        spreads = {"rs_6m": 2.5, "rs_12m1": 0.4, "vol_63": 0.0}
        monos   = {"rs_6m": True, "rs_12m1": True, "vol_63": False}
        assert "SUSPICIOUSLY LARGE" in screen.momentum_verdict(spreads, monos)

    def test_marginal_effect_justifies_v2(self):
        spreads = {"rs_6m": 0.5, "rs_12m1": 0.2, "vol_63": 0.0}
        monos   = {"rs_6m": True, "rs_12m1": False, "vol_63": False}
        assert "Audit V2" in screen.momentum_verdict(spreads, monos)

    def test_aggregate_buckets_balanced(self):
        # 25 symbols on one date with distinct signals -> 5 per quintile.
        panel = []
        for k in range(25):
            panel.append({
                "date": "2022-06-01", "symbol": f"S{k}",
                "rs_6m": float(k), "rs_12m1": float(k), "vol_63": float(k),
                "exc_5": 0.01, "exc_10": 0.01, "exc_20": 0.01,
            })
        result = screen.aggregate(panel, min_names=20)
        counts = [len(result["buckets"]["rs_6m"][10][q]) for q in range(5)]
        assert counts == [5, 5, 5, 5, 5]

    def test_quintile_orientation_high_signal_lands_in_q5(self):
        # The one bug that would invert the entire finding: if a high signal
        # value did NOT map to Q5, a real +spread would read as a -spread.
        # Construct a signal that PERFECTLY predicts the outcome (high signal ->
        # high forward excess). Q5 must then exceed Q1 and the buckets must be
        # monotone increasing. A descending-sort / inverted-bucket bug fails here.
        panel = []
        for k in range(25):
            panel.append({
                "date": "2022-06-01", "symbol": f"S{k}",
                "rs_6m": float(k), "rs_12m1": float(k), "vol_63": float(k),
                "exc_5": 0.001 * k, "exc_10": 0.001 * k, "exc_20": 0.001 * k,
            })
        result = screen.aggregate(panel, min_names=20)
        means = screen.bucket_means(result["buckets"]["rs_6m"][10])
        assert means[4] > means[0], "Q5 (highest signal) must outrank Q1 when signal predicts"
        assert screen.is_monotone(means), "perfectly predictive signal must yield monotone buckets"
