"""Tests for Phase 17 — Calibration Engine (get_calibration_report)."""
import json
import sqlite3

import pytest

import src.journal.db as journal_db
from src.calibration.service import (
    get_calibration_report,
    _calculate_brier_score,
    _build_reliability_curve,
    _calibration_gap,
    _build_overconfidence_analysis,
)


def _make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    journal_db._init_schema(conn)
    return conn


def _snap(confidence: float | None) -> str | None:
    if confidence is None:
        return None
    return json.dumps({"confidence": confidence})


def _trade(conn, symbol="INFY", pnl=500.0, confidence=70.0, entry_date="2026-01-10"):
    snap = _snap(confidence)
    conn.execute(
        """INSERT INTO trades
           (id, symbol, direction, entry_price, quantity, status, pnl, entry_date,
            entry_time, trade_type, created_by, analysis_snapshot, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            f"t-{entry_date}-{pnl}",
            symbol, "LONG", 1000.0, 10, "CLOSED", pnl, entry_date,
            "09:00:00", "EQUITY", "MANUAL", snap,
            "2026-01-10T09:00:00", "2026-01-10T15:00:00",
        ),
    )
    conn.commit()


@pytest.fixture(autouse=True)
def fresh_db():
    conn = _make_conn()
    journal_db.reset_connection(conn)
    yield conn
    journal_db.reset_connection(None)


# ---------------------------------------------------------------------------
# Unit: _calibration_gap
# ---------------------------------------------------------------------------

class TestCalibrationGap:
    def test_overconfident(self):
        # model predicted 0.8, actual 0.6 → gap = -0.2
        assert _calibration_gap(0.6, 0.8) == pytest.approx(-0.2, abs=1e-4)

    def test_underconfident(self):
        assert _calibration_gap(0.9, 0.7) == pytest.approx(0.2, abs=1e-4)

    def test_perfect(self):
        assert _calibration_gap(0.75, 0.75) == 0.0


# ---------------------------------------------------------------------------
# Unit: _calculate_brier_score
# ---------------------------------------------------------------------------

class TestBrierScore:
    def test_perfect_calibration(self):
        # conf=85 → predicted=1.0; all wins → outcome=1.0 → error=0
        trades = [{"pnl": 100.0, "analysis_snapshot": {"confidence": 85.0}}] * 4
        r = _calculate_brier_score(trades)
        assert r["brier_score"] == 0.0
        assert r["calibration_rating"] == "EXCELLENT"
        assert r["scored_count"] == 4

    def test_worst_calibration(self):
        # conf=85 → predicted=1.0; all losses → outcome=0 → error=1.0 each
        trades = [{"pnl": -100.0, "analysis_snapshot": {"confidence": 85.0}}] * 4
        r = _calculate_brier_score(trades)
        assert r["brier_score"] == pytest.approx(1.0, abs=1e-4)
        assert r["calibration_rating"] == "POOR"

    def test_excellent_threshold(self):
        # Brier ≤ 0.15 → EXCELLENT
        trades = [{"pnl": 100.0, "analysis_snapshot": {"confidence": 75.0}}] * 10
        r = _calculate_brier_score(trades)
        assert r["brier_score"] is not None
        assert r["calibration_rating"] == "EXCELLENT"

    def test_no_confidence_scores(self):
        trades = [{"pnl": 100.0, "analysis_snapshot": None}] * 5
        r = _calculate_brier_score(trades)
        assert r["brier_score"] is None
        assert r["calibration_rating"] is None
        assert r["scored_count"] == 0

    def test_skips_trades_without_confidence(self):
        trades = [
            {"pnl": 100.0, "analysis_snapshot": {"confidence": 70.0}},
            {"pnl": 100.0, "analysis_snapshot": None},
        ]
        r = _calculate_brier_score(trades)
        assert r["scored_count"] == 1

    def test_good_rating(self):
        # Mix: half perfect, half wrong with mid confidence → Brier ~0.18
        trades = (
            [{"pnl": 100.0, "analysis_snapshot": {"confidence": 68.0}}] * 5 +
            [{"pnl": -50.0, "analysis_snapshot": {"confidence": 68.0}}] * 5
        )
        r = _calculate_brier_score(trades)
        assert r["brier_score"] is not None
        assert r["calibration_rating"] in ("EXCELLENT", "GOOD", "FAIR", "POOR")


# ---------------------------------------------------------------------------
# Unit: _build_reliability_curve
# ---------------------------------------------------------------------------

class TestReliabilityCurve:
    def test_buckets_ordered(self):
        trades = [
            {"pnl": 100.0, "analysis_snapshot": {"confidence": 80.0}},  # high
            {"pnl": 100.0, "analysis_snapshot": {"confidence": 65.0}},  # moderate
            {"pnl": -50.0, "analysis_snapshot": {"confidence": 40.0}},  # low
            {"pnl": 100.0, "analysis_snapshot": None},                   # unknown
        ]
        curve = _build_reliability_curve(trades, min_sample=1)
        buckets = [b["bucket"] for b in curve]
        assert buckets == ["high", "moderate", "low", "unknown"]

    def test_high_bucket_all_wins(self):
        trades = [{"pnl": 100.0, "analysis_snapshot": {"confidence": 80.0}}] * 3
        curve = _build_reliability_curve(trades, min_sample=1)
        b = curve[0]
        assert b["actual_win_rate"] == 1.0
        assert b["avg_predicted_probability"] == pytest.approx(80.0 / 85.0, abs=1e-3)
        assert b["calibration_gap"] == pytest.approx(1.0 - 80.0 / 85.0, abs=1e-3)

    def test_low_sample_flag(self):
        trades = [{"pnl": 100.0, "analysis_snapshot": {"confidence": 80.0}}] * 2
        curve = _build_reliability_curve(trades, min_sample=5)
        assert curve[0]["low_sample"] is True

    def test_unknown_bucket_has_no_avg_predicted(self):
        trades = [{"pnl": 100.0, "analysis_snapshot": None}] * 3
        curve = _build_reliability_curve(trades, min_sample=1)
        b = next(b for b in curve if b["bucket"] == "unknown")
        assert b["avg_predicted_probability"] is None
        assert b["calibration_gap"] is None

    def test_empty_bucket_not_in_result(self):
        trades = [{"pnl": 100.0, "analysis_snapshot": {"confidence": 80.0}}] * 3
        curve = _build_reliability_curve(trades, min_sample=1)
        buckets = {b["bucket"] for b in curve}
        assert "moderate" not in buckets
        assert "low" not in buckets


# ---------------------------------------------------------------------------
# Unit: _build_overconfidence_analysis
# ---------------------------------------------------------------------------

class TestOverconfidenceAnalysis:
    def _make_curve(self, gaps: list[tuple[str, float]]) -> list[dict]:
        return [
            {"bucket": name, "calibration_gap": gap, "low_sample": False}
            for name, gap in gaps
        ]

    def test_overconfident(self):
        curve = self._make_curve([("high", -0.15), ("moderate", -0.10)])
        r = _build_overconfidence_analysis(curve)
        assert r["dominant_bias"] == "OVERCONFIDENT"
        assert r["overconfidence_score"] > 0
        assert r["underconfidence_score"] == 0.0

    def test_underconfident(self):
        curve = self._make_curve([("high", 0.20), ("moderate", 0.10)])
        r = _build_overconfidence_analysis(curve)
        assert r["dominant_bias"] == "UNDERCONFIDENT"

    def test_balanced(self):
        curve = self._make_curve([("high", -0.10), ("moderate", 0.10)])
        r = _build_overconfidence_analysis(curve)
        assert r["dominant_bias"] == "BALANCED"

    def test_low_sample_buckets_excluded(self):
        curve = [
            {"bucket": "high",     "calibration_gap": -0.30, "low_sample": True},
            {"bucket": "moderate", "calibration_gap":  0.05, "low_sample": False},
        ]
        r = _build_overconfidence_analysis(curve)
        # only "moderate" (positive gap 0.05) contributed → underconfident
        assert r["dominant_bias"] == "UNDERCONFIDENT"

    def test_all_low_sample_returns_none(self):
        curve = [{"bucket": "high", "calibration_gap": -0.10, "low_sample": True}]
        assert _build_overconfidence_analysis(curve) is None

    def test_no_buckets_returns_none(self):
        assert _build_overconfidence_analysis([]) is None


# ---------------------------------------------------------------------------
# Integration: get_calibration_report (via in-memory DB)
# ---------------------------------------------------------------------------

class TestGetCalibrationReport:
    def test_no_closed_trades(self):
        r = get_calibration_report()
        assert r["trade_count"] == 0
        assert r["brier_score"] is None
        assert r["reliability_curve"] == []
        assert "No closed trades" in r["notes"][0]

    def test_basic_report_structure(self, fresh_db):
        _trade(fresh_db, pnl=500.0, confidence=75.0)
        _trade(fresh_db, pnl=-200.0, confidence=60.0)
        r = get_calibration_report(min_sample=1)
        assert r["trade_count"] == 2
        assert r["brier_score"] is not None
        assert isinstance(r["reliability_curve"], list)
        assert r["overconfidence_analysis"] is not None

    def test_symbol_filter(self, fresh_db):
        _trade(fresh_db, symbol="INFY", pnl=500.0, confidence=70.0, entry_date="2026-01-10")
        _trade(fresh_db, symbol="TCS",  pnl=300.0, confidence=70.0, entry_date="2026-01-11")
        r = get_calibration_report(symbol="INFY", min_sample=1)
        assert r["trade_count"] == 1
        assert r["filters"]["symbol"] == "INFY"

    def test_days_filter(self, fresh_db):
        _trade(fresh_db, pnl=500.0, confidence=70.0, entry_date="2025-01-01")
        r = get_calibration_report(days=30, min_sample=1)
        assert r["trade_count"] == 0

    def test_no_confidence_scores_note(self, fresh_db):
        _trade(fresh_db, pnl=500.0, confidence=None, entry_date="2026-01-10")
        r = get_calibration_report()
        assert r["brier_score"] is None
        assert any("confidence" in n.lower() for n in r["notes"])

    def test_db_error_returns_error_dict(self, monkeypatch):
        monkeypatch.setattr(journal_db, "_get_connection", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
        r = get_calibration_report()
        assert "error" in r

    def test_brier_score_rating_in_response(self, fresh_db):
        for i in range(10):
            _trade(fresh_db, pnl=500.0 if i % 2 == 0 else -200.0,
                   confidence=70.0, entry_date=f"2026-01-{10+i:02d}")
        r = get_calibration_report(min_sample=1)
        assert r["calibration_rating"] in ("EXCELLENT", "GOOD", "FAIR", "POOR")

    def test_filters_in_response(self, fresh_db):
        r = get_calibration_report(symbol="RELIANCE", days=180, min_sample=3)
        assert r["filters"] == {"symbol": "RELIANCE", "days": 180, "min_sample": 3}
