"""Tests for Phase 22 recommendation logger — src/recommendation_log/service.py."""
from __future__ import annotations

import json
import sqlite3

import pytest

import src.journal.db as journal_db
from src.recommendation_log.service import (
    log_recommendation,
    update_recommendation_outcome,
    get_recommendation_stats,
    get_recommendation_by_id,
    BOOTSTRAP_PERIOD_RECORDS,
    BASELINE_RECORDS_REQUIRED,
    MIN_CLEAN_RECORDS_FOR_ANALYSIS,
)
from src.recommendation_log.capture import detect_recommendation


# ---------------------------------------------------------------------------
# Fixture — in-memory DB shared with journal layer
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fresh_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    journal_db._init_schema(conn)
    journal_db.reset_connection(conn)
    yield conn
    journal_db.reset_connection(None)
    conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(**kwargs):
    defaults = dict(
        symbol="INFY",
        user_question="Should I enter INFY?",
        market_snapshot={"price": 1540, "regime": "BULL_TREND"},
        mcp_facts={"rsi": 62, "adx": 28},
        claude_reasoning_summary="RSI not overbought, ADX trending. Bullish setup.",
        recommendation_type="ENTER",
        uncertainty_level="MEDIUM",
    )
    defaults.update(kwargs)
    return log_recommendation(**defaults)


# ---------------------------------------------------------------------------
# log_recommendation
# ---------------------------------------------------------------------------

class TestLogRecommendation:
    def test_creates_record_with_id(self):
        result = _log()
        assert "id" in result
        assert result["id"].startswith("REC-")
        assert len(result["id"]) == 12  # REC- + 8 hex chars

    def test_id_format(self):
        result = _log()
        assert result["id"][:4] == "REC-"

    def test_bootstrap_period_defaults_true(self):
        result = _log()
        assert result["bootstrap_period"] is True

    def test_bias_contaminated_defaults_true(self):
        result = _log()
        assert result["bias_contaminated"] is True

    def test_baseline_no_mcp_default_false(self):
        result = _log()
        assert result["baseline_no_mcp"] is False

    def test_baseline_no_mcp_flag(self):
        result = _log(baseline_no_mcp=True)
        assert result["baseline_no_mcp"] is True
        assert result["capture_mode"] == "baseline"

    def test_symbol_uppercased(self):
        result = _log(symbol="infy")
        assert result["symbol"] == "INFY"

    def test_market_snapshot_stored_as_dict(self):
        snap = {"price": 1540, "vix": 14.5}
        result = _log(market_snapshot=snap)
        assert isinstance(result["market_snapshot"], dict)
        assert result["market_snapshot"]["price"] == 1540

    def test_mcp_facts_stored_as_dict(self):
        facts = {"rsi": 62, "ema20": 1530}
        result = _log(mcp_facts=facts)
        assert isinstance(result["mcp_facts"], dict)

    def test_outcome_fields_null_at_creation(self):
        result = _log()
        assert result.get("outcome_1d") is None
        assert result.get("outcome_5d") is None
        assert result.get("outcome_20d") is None
        assert result.get("user_action") is None

    def test_invalid_recommendation_type(self):
        result = _log(recommendation_type="INVALID_TYPE")
        assert "error" in result

    def test_invalid_uncertainty_level(self):
        result = _log(uncertainty_level="VERY_HIGH")
        assert "error" in result

    def test_all_valid_recommendation_types(self):
        valid = ["ENTER", "EXIT", "HOLD", "AVOID", "OBSERVE",
                 "STAY_CASH", "SIZE_REDUCE", "TAKE_PROFIT", "TIGHTEN_STOP", "NONE"]
        for rtype in valid:
            result = _log(recommendation_type=rtype)
            assert "id" in result, f"Failed for type {rtype}"

    def test_symbol_none_allowed(self):
        result = _log(symbol=None)
        assert "id" in result
        assert result.get("symbol") is None


# ---------------------------------------------------------------------------
# update_recommendation_outcome
# ---------------------------------------------------------------------------

class TestUpdateRecommendationOutcome:
    def test_update_user_action(self):
        rec = _log()
        updated = update_recommendation_outcome(
            id=rec["id"],
            user_action="Entered INFY LONG at 1540",
        )
        assert updated["user_action"] == "Entered INFY LONG at 1540"

    def test_update_mcp_changed_decision(self):
        rec = _log()
        updated = update_recommendation_outcome(
            id=rec["id"],
            mcp_changed_decision=True,
        )
        assert updated["mcp_changed_decision"] is True

    def test_update_outcomes(self):
        rec = _log()
        updated = update_recommendation_outcome(
            id=rec["id"],
            outcome_1d=2.3,
            outcome_5d=5.1,
            outcome_20d=-1.2,
        )
        assert updated["outcome_1d"] == pytest.approx(2.3)
        assert updated["outcome_5d"] == pytest.approx(5.1)
        assert updated["outcome_20d"] == pytest.approx(-1.2)

    def test_update_postmortem(self):
        rec = _log()
        updated = update_recommendation_outcome(
            id=rec["id"],
            postmortem_helpful=True,
            postmortem_why="Changed my mind about position size.",
            postmortem_review_questions={
                "facts_accurate": True,
                "uncertainty_communicated": True,
                "risk_defined": False,
                "disciplined_behavior_encouraged": True,
                "changed_decision": True,
                "market_outcome": "Price rose 2.3% next day",
            },
        )
        assert updated["postmortem_helpful"] is True
        assert updated["postmortem_why"] == "Changed my mind about position size."
        assert isinstance(updated["postmortem_review_questions"], dict)
        assert updated["postmortem_review_questions"]["facts_accurate"] is True

    def test_update_decision_quality(self):
        rec = _log()
        dq = {
            "process_followed": True,
            "risk_defined": True,
            "position_sized_correctly": False,
            "exit_plan_defined": True,
        }
        updated = update_recommendation_outcome(id=rec["id"], decision_quality=dq)
        assert isinstance(updated["decision_quality"], dict)
        assert updated["decision_quality"]["process_followed"] is True

    def test_update_nonexistent_id(self):
        result = update_recommendation_outcome(id="REC-00000000")
        assert "error" in result

    def test_update_no_fields_raises_error(self):
        rec = _log()
        result = update_recommendation_outcome(id=rec["id"])
        assert "error" in result

    def test_partial_update_preserves_other_fields(self):
        rec = _log()
        update_recommendation_outcome(id=rec["id"], outcome_1d=2.0)
        update_recommendation_outcome(id=rec["id"], postmortem_helpful=True)
        final = get_recommendation_by_id(rec["id"])
        assert final["outcome_1d"] == pytest.approx(2.0)
        assert final["postmortem_helpful"] is True


# ---------------------------------------------------------------------------
# get_recommendation_stats
# ---------------------------------------------------------------------------

class TestGetRecommendationStats:
    def test_empty_db_returns_zeros(self):
        stats = get_recommendation_stats()
        assert stats["total_records"] == 0
        assert stats["clean_records"] == 0
        assert stats["bootstrap_records"] == 0
        assert stats["baseline_records"] == 0
        assert stats["analysis_ready"] is False
        assert stats["stats"] is None

    def test_bootstrap_record_counted(self):
        _log()
        stats = get_recommendation_stats()
        assert stats["total_records"] == 1
        assert stats["bootstrap_records"] == 1
        assert stats["clean_records"] == 0

    def test_baseline_record_counted(self):
        _log(baseline_no_mcp=True)
        stats = get_recommendation_stats()
        assert stats["baseline_records"] == 1

    def test_not_analysis_ready_below_threshold(self):
        for _ in range(10):
            _log()
        stats = get_recommendation_stats()
        assert stats["analysis_ready"] is False

    def test_records_until_analysis_decrements(self):
        stats_before = get_recommendation_stats()
        _log()
        stats_after = get_recommendation_stats()
        assert stats_after["total_records"] == stats_before["total_records"] + 1

    def test_thresholds_present(self):
        stats = get_recommendation_stats()
        t = stats["thresholds"]
        assert t["bootstrap_period_records"] == BOOTSTRAP_PERIOD_RECORDS
        assert t["baseline_records_required"] == BASELINE_RECORDS_REQUIRED
        assert t["min_clean_records_for_analysis"] == MIN_CLEAN_RECORDS_FOR_ANALYSIS


# ---------------------------------------------------------------------------
# detect_recommendation (capture module)
# ---------------------------------------------------------------------------

class TestDetectRecommendation:
    def test_entry_trigger_detected(self):
        result = detect_recommendation("I think you should enter INFY long here.")
        assert result["detected"] is True
        assert result["requires_logging"] is True

    def test_exit_trigger_detected(self):
        result = detect_recommendation("You should exit your position now.")
        assert result["detected"] is True

    def test_hold_trigger_detected(self):
        result = detect_recommendation("Best to hold and stay in the trade.")
        assert result["detected"] is True

    def test_avoid_trigger_detected(self):
        result = detect_recommendation("I would avoid trading today.")
        assert result["detected"] is True

    def test_no_trigger_not_detected(self):
        result = detect_recommendation("The RSI is 65 and the EMA is above the 50.")
        assert result["detected"] is False
        assert result["requires_logging"] is False

    def test_empty_text(self):
        result = detect_recommendation("")
        assert result["detected"] is False

    def test_dominant_type_set_when_detected(self):
        result = detect_recommendation("You should enter and buy at this level.")
        assert result["dominant_type"] is not None

    def test_capture_mode_is_auto(self):
        result = detect_recommendation("enter this trade")
        assert result["capture_mode"] == "auto"

    def test_triggers_found_list(self):
        result = detect_recommendation("buy INFY now and exit at 1640")
        assert len(result["triggers_found"]) >= 2

    def test_buy_trigger(self):
        result = detect_recommendation("I recommend you buy RELIANCE.")
        assert result["detected"] is True

    def test_sell_trigger(self):
        result = detect_recommendation("You should sell and close the position.")
        assert result["detected"] is True

    def test_wait_trigger(self):
        result = detect_recommendation("Too risky right now, wait for a better setup.")
        assert result["detected"] is True

    def test_case_insensitive(self):
        result = detect_recommendation("ENTER INFY LONG")
        assert result["detected"] is True
