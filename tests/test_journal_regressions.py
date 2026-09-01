"""JR-1 through JR-5 — Journal regression guards.

JR-1: log_trade with all optional fields omitted → valid trade_id, no crash
JR-2: close_trade with non-existent trade_id → {"error": "..."}, no exception
JR-3: DB failure → {"error": "..."} from every service function, no exception
JR-4: close_trade on already-closed trade → error dict, original record unchanged
JR-5: get_trade_history with days=0 → empty/valid list, no crash
"""
from __future__ import annotations

import sqlite3

import pytest

import src.journal.db as journal_db
from src.journal.service import (
    close_trade,
    get_open_trades,
    get_trade_history,
    log_trade,
)

# ---------------------------------------------------------------------------
# Fixture
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
# JR-1: log_trade minimal — no optional fields
# ---------------------------------------------------------------------------

class TestJR1LogTradeMinimal:
    def test_log_with_only_required_fields_succeeds(self):
        result = log_trade(symbol="INFY", direction="LONG", entry_price=1500.0)
        assert "error" not in result
        assert result["trade_id"].startswith("TRD-")

    def test_log_long_no_optional_status_open(self):
        result = log_trade(symbol="TCS", direction="LONG", entry_price=3400.0)
        assert result["status"] == "OPEN"

    def test_log_short_no_optional_succeeds(self):
        result = log_trade(symbol="NIFTY", direction="SHORT", entry_price=23000.0)
        assert "error" not in result
        assert result["direction"] == "SHORT"

    def test_all_optional_fields_are_null(self):
        result = log_trade(symbol="INFY", direction="LONG", entry_price=1500.0)
        for field in ("strategy", "rationale", "stoploss", "target", "risk_reward",
                      "regime", "signal", "risk_score", "analysis_snapshot", "notes"):
            assert result[field] is None, f"expected {field} to be None"


# ---------------------------------------------------------------------------
# JR-2: close_trade with non-existent trade_id
# ---------------------------------------------------------------------------

class TestJR2CloseNonExistent:
    def test_non_existent_trade_returns_error_dict(self):
        result = close_trade(trade_id="TRD-00000000", exit_price=1600.0)
        assert "error" in result
        assert "trade not found" in result["error"]

    def test_no_exception_raised(self):
        # Should never raise — all errors as return values
        result = close_trade(trade_id="TRD-doesnotexist", exit_price=999.0)
        assert isinstance(result, dict)
        assert "error" in result

    def test_trade_id_included_in_error(self):
        result = close_trade(trade_id="TRD-abcd1234", exit_price=100.0)
        assert "TRD-abcd1234" in result["error"]


# ---------------------------------------------------------------------------
# JR-3: DB failure → error dict from all service functions
# ---------------------------------------------------------------------------

class TestJR3DatabaseFailure:
    def test_log_trade_db_failure_returns_error(self, monkeypatch):
        def _fail():
            raise RuntimeError("db unavailable")
        monkeypatch.setattr(journal_db, "_get_connection", _fail)
        result = log_trade(symbol="INFY", direction="LONG", entry_price=1500.0)
        assert "error" in result
        assert "db unavailable" in result["error"]

    def test_close_trade_db_failure_returns_error(self, monkeypatch):
        def _fail():
            raise RuntimeError("db unavailable")
        monkeypatch.setattr(journal_db, "_get_connection", _fail)
        result = close_trade(trade_id="TRD-xxxxxxxx", exit_price=1600.0)
        assert "error" in result

    def test_get_open_trades_db_failure_returns_error(self, monkeypatch):
        def _fail():
            raise RuntimeError("db unavailable")
        monkeypatch.setattr(journal_db, "_get_connection", _fail)
        result = get_open_trades()
        assert "error" in result

    def test_get_trade_history_db_failure_returns_error(self, monkeypatch):
        def _fail():
            raise RuntimeError("db unavailable")
        monkeypatch.setattr(journal_db, "_get_connection", _fail)
        result = get_trade_history()
        assert "error" in result

    def test_no_exception_propagates_from_any_function(self, monkeypatch):
        def _fail():
            raise RuntimeError("db crash")
        monkeypatch.setattr(journal_db, "_get_connection", _fail)
        for fn, kwargs in [
            (log_trade, {"symbol": "X", "direction": "LONG", "entry_price": 100.0}),
            (close_trade, {"trade_id": "TRD-x", "exit_price": 110.0}),
            (get_open_trades, {}),
            (get_trade_history, {}),
        ]:
            result = fn(**kwargs)
            assert isinstance(result, dict)
            assert "error" in result


# ---------------------------------------------------------------------------
# JR-4: close_trade on already-closed trade
# ---------------------------------------------------------------------------

class TestJR4DoubleClose:
    def test_double_close_returns_error(self):
        trade_id = log_trade(symbol="INFY", direction="LONG", entry_price=1500.0)["trade_id"]
        close_trade(trade_id=trade_id, exit_price=1600.0)
        result = close_trade(trade_id=trade_id, exit_price=1700.0)
        assert "error" in result
        assert "already closed" in result["error"]

    def test_original_record_unchanged_after_double_close(self, fresh_db):
        trade_id = log_trade(symbol="INFY", direction="LONG", entry_price=1500.0)["trade_id"]
        close_trade(trade_id=trade_id, exit_price=1600.0)
        close_trade(trade_id=trade_id, exit_price=1700.0)  # second close — should be no-op
        row = fresh_db.execute(
            "SELECT exit_price FROM trades WHERE id = ?", (trade_id,)
        ).fetchone()
        assert row["exit_price"] == 1600.0  # original exit price preserved

    def test_double_close_does_not_raise(self):
        trade_id = log_trade(symbol="TCS", direction="LONG", entry_price=3000.0)["trade_id"]
        close_trade(trade_id=trade_id, exit_price=3100.0)
        result = close_trade(trade_id=trade_id, exit_price=3200.0)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# JR-5: get_trade_history with days=0
# ---------------------------------------------------------------------------

class TestJR5HistoryDaysZero:
    def test_days_zero_does_not_crash(self):
        result = get_trade_history(days=0)
        assert isinstance(result, dict)
        assert "error" not in result

    def test_days_zero_returns_valid_structure(self):
        result = get_trade_history(days=0)
        assert "count" in result
        assert "trades" in result
        assert "summary" in result
        assert "filters" in result

    def test_days_zero_includes_todays_trade(self):
        log_trade(symbol="INFY", direction="LONG", entry_price=1500.0)
        result = get_trade_history(days=0)
        assert result["count"] == 1

    def test_days_negative_clamped_to_zero(self):
        # max(days, 0) means negative days behaves like 0
        log_trade(symbol="INFY", direction="LONG", entry_price=1500.0)
        result = get_trade_history(days=-10)
        assert isinstance(result, dict)
        assert "error" not in result
