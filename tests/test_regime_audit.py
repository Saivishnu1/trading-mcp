"""
Regression guards for the Regime Predictiveness Audit (Phase 20A).

These four test classes enforce the hard constraints of the walk-forward audit:

  Guard 1 — detect_market_regime() is never called inside run_symbol_audit().
  Guard 2 — No live data fetch occurs inside run_symbol_audit().
  Guard 3 — No classifications are generated before CLASSIFY_FROM (warmup boundary).
  Guard 4 — No classifications are generated within the final TAIL_EXCLUSION trading days.

Each guard is designed to catch a specific implementation shortcut.  If someone
introduces any of these regressions, the relevant test class fails immediately
with a message that names the exact constraint that was violated.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from scripts.regime_audit import (
    CLASSIFY_FROM,
    LOOKBACK,
    TAIL_EXCLUSION,
    ClassificationRow,
    compute_metrics,
    monotonicity_check,
    run_start_vs_continuation,
    run_symbol_audit,
)

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

def _make_candles(n: int, start: str = "2021-01-04") -> list[dict]:
    """Generate n synthetic OHLCV candle dicts (Mon–Fri, no NaN values).

    Uses a deterministic sine-wave price pattern so tests are reproducible.
    Amplitude is large enough to produce varied ADX/RSI readings across the series.
    """
    candles: list[dict] = []
    d = date.fromisoformat(start)
    price = 1000.0
    for i in range(n):
        while d.weekday() >= 5:          # skip weekends
            d += timedelta(days=1)
        price = max(400.0, price + math.sin(i * 0.12) * 12)
        candles.append({
            "date":   d.isoformat(),
            "open":   round(price - 3.0, 4),
            "high":   round(price + 8.0, 4),
            "low":    round(price - 8.0, 4),
            "close":  round(price, 4),
            "volume": 1_000_000,
        })
        d += timedelta(days=1)
    return candles


# ---------------------------------------------------------------------------
# Guard 1 — detect_market_regime() must never be called inside the audit loop
# ---------------------------------------------------------------------------

class TestDetectMarketRegimeNeverCalled:
    """detect_market_regime() fetches live data.  The audit must never call it."""

    def test_audit_survives_when_detect_market_regime_raises(self, monkeypatch):
        """Patch detect_market_regime to raise.  If the audit calls it, the test fails."""
        import src.analysis.regime as regime_mod

        def _forbidden(*args, **kwargs):
            raise AssertionError(
                "REGRESSION (Guard 1): detect_market_regime() was called inside "
                "run_symbol_audit().  The audit must use _classify_regime() directly."
            )

        monkeypatch.setattr(regime_mod, "detect_market_regime", _forbidden)

        candles = _make_candles(400)
        rows = run_symbol_audit("TEST", "TEST.NS", candles)
        assert isinstance(rows, list)

    def test_detect_market_regime_not_in_audit_module_namespace(self):
        """detect_market_regime must not be imported into scripts.regime_audit.

        If it appears in the module namespace, it is available for accidental use.
        """
        import scripts.regime_audit as audit_mod
        assert not hasattr(audit_mod, "detect_market_regime"), (
            "REGRESSION (Guard 1): detect_market_regime is importable from "
            "scripts.regime_audit.  Remove the import — only _classify_regime is allowed."
        )


# ---------------------------------------------------------------------------
# Guard 2 — no live data fetch inside run_symbol_audit()
# ---------------------------------------------------------------------------

class TestNoLiveCallsInLoop:
    """All OHLCV data must be pre-downloaded.  run_symbol_audit() receives the array."""

    def test_get_market_not_called_inside_run_symbol_audit(self, monkeypatch):
        """Patch get_market to raise.  If run_symbol_audit calls it, the test fails."""
        import scripts.regime_audit as audit_mod

        def _forbidden(*args, **kwargs):
            raise RuntimeError(
                "REGRESSION (Guard 2): get_market() was called inside run_symbol_audit(). "
                "All OHLCV data must be downloaded before the audit loop."
            )

        monkeypatch.setattr(audit_mod, "get_market", _forbidden)

        candles = _make_candles(400)
        rows = run_symbol_audit("TEST", "TEST.NS", candles)
        assert isinstance(rows, list)

    def test_analyze_technicals_not_called_inside_run_symbol_audit(self, monkeypatch):
        """Patch _analyze_technicals to raise.

        _analyze_technicals is the production live-data path; the audit replaces it
        with the pure _build_technicals().  If the audit accidentally calls the live
        version, this test catches it.
        """
        import src.analysis.regime as regime_mod

        def _forbidden(*args, **kwargs):
            raise RuntimeError(
                "REGRESSION (Guard 2): _analyze_technicals() was called inside "
                "run_symbol_audit().  Use _build_technicals() — no live-data path."
            )

        monkeypatch.setattr(regime_mod, "_analyze_technicals", _forbidden)

        candles = _make_candles(400)
        rows = run_symbol_audit("TEST", "TEST.NS", candles)
        assert isinstance(rows, list)

    def test_load_candles_not_called_inside_run_symbol_audit(self, monkeypatch):
        """Patch _load_candles (yfinance call site) to raise as a belt-and-suspenders guard."""
        import src.tools.technicals as tech_mod

        def _forbidden(*args, **kwargs):
            raise RuntimeError(
                "REGRESSION (Guard 2): _load_candles() was called inside "
                "run_symbol_audit().  The audit must use the pre-downloaded array only."
            )

        monkeypatch.setattr(tech_mod, "_load_candles", _forbidden)

        candles = _make_candles(400)
        rows = run_symbol_audit("TEST", "TEST.NS", candles)
        assert isinstance(rows, list)


# ---------------------------------------------------------------------------
# Guard 3 — no classifications before the warmup boundary
# ---------------------------------------------------------------------------

class TestWarmupBoundary:
    """2021 data is warmup only.  No classification must have date < CLASSIFY_FROM."""

    def test_no_classification_before_classify_from(self):
        """600 candles from 2021-01-04 spans warmup + classification period."""
        candles = _make_candles(600)
        rows    = run_symbol_audit("TEST", "TEST.NS", candles)

        assert len(rows) > 0, (
            "No classifications produced — check candle count or warmup logic."
        )
        too_early = [r for r in rows if r.date < CLASSIFY_FROM]
        assert not too_early, (
            f"REGRESSION (Guard 3): {len(too_early)} classification(s) generated "
            f"before warmup boundary {CLASSIFY_FROM}.  Earliest: {too_early[0].date}"
        )

    def test_no_classification_when_lookback_window_not_full(self):
        """Even if date >= CLASSIFY_FROM, classification must not start before index LOOKBACK-1."""
        # Candles start in 2022 — no 2021 warmup data at all.
        candles = _make_candles(300, "2022-01-03")
        rows    = run_symbol_audit("TEST", "TEST.NS", candles)

        if rows:
            # First valid classification index is LOOKBACK-1; its date is the boundary.
            first_valid_date = candles[LOOKBACK - 1]["date"]
            assert rows[0].date >= first_valid_date, (
                f"REGRESSION (Guard 3): First classification at {rows[0].date} precedes "
                f"minimum lookback boundary {first_valid_date} (index {LOOKBACK - 1})."
            )

    def test_first_classification_date_is_on_or_after_classify_from(self):
        """Explicit check that the very first row never predates CLASSIFY_FROM."""
        candles = _make_candles(600)
        rows    = run_symbol_audit("TEST", "TEST.NS", candles)
        assert rows, "No classifications produced."
        assert rows[0].date >= CLASSIFY_FROM, (
            f"REGRESSION (Guard 3): First classification date {rows[0].date} "
            f"is before CLASSIFY_FROM={CLASSIFY_FROM}."
        )


# ---------------------------------------------------------------------------
# Guard 4 — no classifications within the final TAIL_EXCLUSION trading days
# ---------------------------------------------------------------------------

class TestTailExclusion:
    """Final TAIL_EXCLUSION trading days are excluded so forward windows are complete."""

    def test_no_classification_in_final_tail_exclusion_days(self):
        """No ClassificationRow.date may exceed the tail exclusion boundary."""
        candles = _make_candles(400)
        rows    = run_symbol_audit("TEST", "TEST.NS", candles)

        assert len(rows) > 0, "No classifications produced."

        boundary_idx  = len(candles) - 1 - TAIL_EXCLUSION
        boundary_date = candles[boundary_idx]["date"]

        too_late = [r for r in rows if r.date > boundary_date]
        assert not too_late, (
            f"REGRESSION (Guard 4): {len(too_late)} classification(s) fall within "
            f"the final {TAIL_EXCLUSION} trading days (boundary: {boundary_date}). "
            f"Latest found: {too_late[-1].date}"
        )

    def test_last_classification_has_all_three_forward_windows_populated(self):
        """The last row must have non-None 5d, 10d, and 20d forward returns.

        If classifications reach too close to the end of the array, _fwd() returns
        None for one or more windows.  This test catches that boundary error.
        """
        candles = _make_candles(400)
        rows    = run_symbol_audit("TEST", "TEST.NS", candles)

        assert rows, "No classifications produced."
        last = rows[-1]
        assert last.ret_5d  is not None, (
            f"REGRESSION (Guard 4): Last row ({last.date}) has ret_5d=None — "
            "classification occurred too close to the end of the candle array."
        )
        assert last.ret_10d is not None, (
            f"REGRESSION (Guard 4): Last row ({last.date}) has ret_10d=None."
        )
        assert last.ret_20d is not None, (
            f"REGRESSION (Guard 4): Last row ({last.date}) has ret_20d=None."
        )

    def test_no_row_has_none_forward_return_within_valid_window(self):
        """Every row inside the classification window must have complete forward returns."""
        candles    = _make_candles(400)
        rows       = run_symbol_audit("TEST", "TEST.NS", candles)
        incomplete = [r for r in rows if None in (r.ret_5d, r.ret_10d, r.ret_20d)]
        assert not incomplete, (
            f"REGRESSION (Guard 4): {len(incomplete)} row(s) have None forward returns "
            "inside the classification window — TAIL_EXCLUSION is not being enforced correctly."
        )


# ---------------------------------------------------------------------------
# Metrics sanity checks (not regression guards — validate compute_metrics output)
# ---------------------------------------------------------------------------

class TestMetricsSanity:

    def test_pct_time_sums_to_100(self):
        candles = _make_candles(400)
        rows    = run_symbol_audit("TEST", "TEST.NS", candles)
        metrics = compute_metrics(rows)
        total   = sum(
            m.get("pct_time", 0.0)
            for m in metrics["regimes"].values()
            if m.get("n", 0) > 0
        )
        assert abs(total - 100.0) < 0.5, (
            f"pct_time values sum to {total:.2f}%, expected 100.0%."
        )

    def test_compute_metrics_returns_required_top_level_keys(self):
        rows    = run_symbol_audit("TEST", "TEST.NS", _make_candles(400))
        metrics = compute_metrics(rows)
        for key in ("total_classifications", "baseline_positive_10d_pct",
                    "baseline_avg_ret_10d_pct", "regimes"):
            assert key in metrics, f"Missing key '{key}' in compute_metrics output."

    def test_monotonicity_check_returns_required_keys(self):
        rows    = run_symbol_audit("TEST", "TEST.NS", _make_candles(400))
        metrics = compute_metrics(rows)
        mono    = monotonicity_check(metrics)
        for key in ("monotonicity_holds", "bull_above_bear",
                    "bear_trend_return_negative", "return_by_regime"):
            assert key in mono, f"Missing key '{key}' in monotonicity_check output."

    def test_each_regime_metric_has_required_fields(self):
        rows    = run_symbol_audit("TEST", "TEST.NS", _make_candles(400))
        metrics = compute_metrics(rows)
        for regime, m in metrics["regimes"].items():
            if m.get("n", 0) == 0:
                continue
            for field in ("n", "runs", "avg_run_length", "avg_confidence",
                          "pct_time", "avg_ret_5d_pct", "avg_ret_10d_pct", "avg_ret_20d_pct"):
                assert field in m, (
                    f"Regime '{regime}' missing field '{field}' in metrics dict."
                )

    def test_compute_metrics_empty_input_does_not_raise(self):
        metrics = compute_metrics([])
        assert metrics["total_classifications"] == 0


# ---------------------------------------------------------------------------
# run_start_vs_continuation diagnostic
# ---------------------------------------------------------------------------

class TestRunStartVsContinuation:
    """Unit tests for the run-start vs continuation diagnostic function."""

    def _rows(self, regimes: list[str], ret_10d: list[float]) -> list[ClassificationRow]:
        """Build minimal ClassificationRow fixtures from regime + return lists."""
        assert len(regimes) == len(ret_10d)
        return [
            ClassificationRow(
                date=f"2022-01-{i+1:02d}",
                regime=r,
                confidence=70,
                ret_5d=0.0,
                ret_10d=v,
                ret_20d=0.0,
            )
            for i, (r, v) in enumerate(zip(regimes, ret_10d))
        ]

    def test_single_run_first_element_is_start(self):
        rows = self._rows(
            ["BULL_TREND", "BULL_TREND", "BULL_TREND"],
            [0.02, -0.01, -0.03],
        )
        d = run_start_vs_continuation(rows, "BULL_TREND")
        assert d["n_starts"] == 1
        assert d["n_continuations"] == 2
        assert d["avg_10d_starts"] == pytest.approx(2.0, abs=0.01)     # 0.02 × 100
        assert d["avg_10d_continuations"] == pytest.approx(-2.0, abs=0.01)  # avg(-0.01, -0.03) × 100

    def test_two_separate_runs_counted_as_two_starts(self):
        rows = self._rows(
            ["BULL_TREND", "RANGE_BOUND", "BULL_TREND", "BULL_TREND"],
            [0.01, 0.00, 0.02, -0.01],
        )
        d = run_start_vs_continuation(rows, "BULL_TREND")
        assert d["n_starts"] == 2
        assert d["n_continuations"] == 1

    def test_mature_trend_interpretation(self):
        """Positive start, negative continuation → MATURE_TREND_EFFECT."""
        rows = self._rows(
            ["BULL_TREND"] * 10,
            [0.02] + [-0.02] * 9,
        )
        d = run_start_vs_continuation(rows, "BULL_TREND")
        assert d["interpretation"] == "MATURE_TREND_EFFECT"

    def test_inception_failure_interpretation(self):
        """Negative start and continuation → INCEPTION_FAILURE."""
        rows = self._rows(
            ["BULL_TREND"] * 5,
            [-0.02, -0.03, -0.01, -0.04, -0.02],
        )
        d = run_start_vs_continuation(rows, "BULL_TREND")
        assert d["interpretation"] == "INCEPTION_FAILURE"

    def test_no_entry_edge_interpretation(self):
        """Near-zero start, negative continuation → NO_ENTRY_EDGE."""
        rows = self._rows(
            ["BULL_TREND"] * 5,
            [0.0005, -0.02, -0.03, -0.01, -0.04],
        )
        d = run_start_vs_continuation(rows, "BULL_TREND")
        assert d["interpretation"] == "NO_ENTRY_EDGE"

    def test_window_bias_interpretation(self):
        """Both positive → WINDOW_BIAS."""
        rows = self._rows(
            ["BULL_TREND"] * 4,
            [0.03, 0.02, 0.015, 0.025],
        )
        d = run_start_vs_continuation(rows, "BULL_TREND")
        assert d["interpretation"] == "WINDOW_BIAS"

    def test_empty_input_returns_insufficient_data(self):
        d = run_start_vs_continuation([], "BULL_TREND")
        assert d["interpretation"] == "INSUFFICIENT_DATA"
        assert d["n_starts"] == 0
        assert d["n_continuations"] == 0

    def test_regime_not_present_returns_insufficient_data(self):
        rows = self._rows(["RANGE_BOUND", "RANGE_BOUND"], [0.01, -0.01])
        d = run_start_vs_continuation(rows, "BULL_TREND")
        assert d["interpretation"] == "INSUFFICIENT_DATA"

    def test_single_day_run_has_start_no_continuation(self):
        rows = self._rows(["BULL_TREND"], [0.05])
        d = run_start_vs_continuation(rows, "BULL_TREND")
        assert d["n_starts"] == 1
        assert d["n_continuations"] == 0
        assert d["avg_10d_continuations"] is None

    def test_bear_trend_split_works_identically(self):
        rows = self._rows(
            ["BEAR_TREND", "BEAR_TREND", "BULL_TREND", "BEAR_TREND"],
            [-0.03, 0.02, 0.01, -0.02],
        )
        d = run_start_vs_continuation(rows, "BEAR_TREND")
        assert d["n_starts"] == 2
        assert d["n_continuations"] == 1

    def test_required_keys_present(self):
        rows = self._rows(["BULL_TREND", "BULL_TREND"], [0.01, -0.01])
        d = run_start_vs_continuation(rows, "BULL_TREND")
        for key in ("regime", "n_starts", "n_continuations",
                    "avg_10d_starts", "avg_10d_continuations", "interpretation"):
            assert key in d, f"Missing key '{key}'"
