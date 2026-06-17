"""Tests for src/journal/service.py — CRUD and business logic."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

import pytest

import src.journal.db as journal_db
from src.journal.service import (
    log_trade,
    close_trade,
    get_open_trades,
    get_trade_history,
    _calculate_pnl,
    _auto_risk_reward,
    _build_summary,
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
# Helpers
# ---------------------------------------------------------------------------

def _log(symbol="INFY", direction="LONG", entry_price=1540.0, **kwargs):
    return log_trade(symbol=symbol, direction=direction, entry_price=entry_price, **kwargs)


def _close(trade_id, exit_price=1600.0, exit_reason="MANUAL", **kwargs):
    return close_trade(trade_id=trade_id, exit_price=exit_price, exit_reason=exit_reason, **kwargs)


# ---------------------------------------------------------------------------
# TestCalculatePnl
# ---------------------------------------------------------------------------

class TestCalculatePnl:
    def test_long_profit(self):
        pnl, pct = _calculate_pnl("LONG", 1000.0, 1100.0, 10)
        assert pnl == 1000.0
        assert pct == pytest.approx(10.0, rel=1e-6)

    def test_long_loss(self):
        pnl, pct = _calculate_pnl("LONG", 1000.0, 900.0, 10)
        assert pnl == -1000.0
        assert pct == pytest.approx(-10.0, rel=1e-6)

    def test_short_profit(self):
        pnl, pct = _calculate_pnl("SHORT", 1000.0, 900.0, 10)
        assert pnl == 1000.0

    def test_short_loss(self):
        pnl, pct = _calculate_pnl("SHORT", 1000.0, 1100.0, 10)
        assert pnl == -1000.0

    def test_quantity_none_defaults_to_1(self):
        pnl, _ = _calculate_pnl("LONG", 100.0, 110.0, None)
        assert pnl == 10.0

    def test_break_even(self):
        pnl, pct = _calculate_pnl("LONG", 1000.0, 1000.0, 5)
        assert pnl == 0.0
        assert pct == 0.0


# ---------------------------------------------------------------------------
# TestAutoRiskReward
# ---------------------------------------------------------------------------

class TestAutoRiskReward:
    def test_long_standard(self):
        rr = _auto_risk_reward("LONG", 100.0, 90.0, 120.0)
        assert rr == 2.0

    def test_short_standard(self):
        rr = _auto_risk_reward("SHORT", 100.0, 110.0, 80.0)
        assert rr == 2.0

    def test_zero_risk_returns_none(self):
        rr = _auto_risk_reward("LONG", 100.0, 100.0, 120.0)
        assert rr is None

    def test_negative_risk_returns_none(self):
        rr = _auto_risk_reward("LONG", 100.0, 110.0, 120.0)
        assert rr is None


# ---------------------------------------------------------------------------
# TestLogTrade
# ---------------------------------------------------------------------------

class TestLogTrade:
    def test_valid_long_returns_trade_id(self):
        result = _log()
        assert "trade_id" in result
        assert result["trade_id"].startswith("TRD-")
        assert len(result["trade_id"]) == 12  # TRD- + 8 chars

    def test_valid_short(self):
        result = _log(direction="SHORT")
        assert result["direction"] == "SHORT"
        assert result["status"] == "OPEN"

    def test_direction_case_insensitive(self):
        result = _log(direction="long")
        assert result["direction"] == "LONG"

    def test_symbol_uppercased(self):
        result = _log(symbol="infy")
        assert result["symbol"] == "INFY"

    def test_invalid_direction_returns_error(self):
        result = _log(direction="BUY")
        assert "error" in result
        assert "LONG or SHORT" in result["error"]

    def test_zero_entry_price_returns_error(self):
        result = _log(entry_price=0)
        assert "error" in result

    def test_negative_entry_price_returns_error(self):
        result = _log(entry_price=-100)
        assert "error" in result

    def test_risk_score_out_of_range_returns_error(self):
        result = _log(risk_score=101)
        assert "error" in result

    def test_optional_fields_null_by_default(self):
        result = _log()
        assert result["strategy"] is None
        assert result["rationale"] is None
        assert result["stoploss"] is None
        assert result["target"] is None
        assert result["regime"] is None
        assert result["notes"] is None
        assert result["analysis_snapshot"] is None

    def test_risk_reward_auto_calculated(self):
        result = _log(stoploss=1490.0, target=1640.0)
        assert result["risk_reward"] == pytest.approx(2.0, rel=1e-3)

    def test_risk_reward_explicit_overrides_auto(self):
        result = _log(stoploss=1490.0, target=1640.0, risk_reward=3.5)
        assert result["risk_reward"] == 3.5

    def test_tags_stored_and_returned_as_list(self):
        result = _log(tags=["momentum", "event-play"])
        assert result["tags"] == ["momentum", "event-play"]

    def test_empty_tags_stored_as_empty_list(self):
        result = _log(tags=[])
        assert result["tags"] == []

    def test_no_tags_returned_as_empty_list(self):
        result = _log()
        assert result["tags"] == []

    def test_analysis_snapshot_stored_and_returned(self):
        snap = {"vix": 14.2, "event_risk": 42, "notes": "pre-budget"}
        result = _log(analysis_snapshot=snap)
        assert result["analysis_snapshot"] == snap

    def test_trade_type_stored(self):
        result = _log(trade_type="OPTIONS")
        assert result["trade_type"] == "OPTIONS"

    def test_trade_type_default_equity(self):
        result = _log()
        assert result["trade_type"] == "EQUITY"

    def test_created_by_stored(self):
        result = _log(created_by="CLAUDE")
        assert result["created_by"] == "CLAUDE"

    def test_created_by_default_manual(self):
        result = _log()
        assert result["created_by"] == "MANUAL"

    def test_two_trades_have_distinct_ids(self):
        r1 = _log()
        r2 = _log()
        assert r1["trade_id"] != r2["trade_id"]

    def test_status_is_open(self):
        result = _log()
        assert result["status"] == "OPEN"

    def test_entry_date_is_today(self):
        result = _log()
        assert result["entry_date"] == date.today().isoformat()

    def test_all_expected_keys_present(self):
        result = _log(stoploss=1490.0, target=1640.0)
        for key in (
            "trade_id", "symbol", "trade_type", "direction", "strategy",
            "entry_price", "quantity", "entry_date", "entry_time",
            "rationale", "stoploss", "target", "risk_reward",
            "regime", "signal", "risk_score", "analysis_snapshot",
            "created_by", "status", "exit_price", "exit_date", "exit_time",
            "exit_reason", "pnl", "pnl_percent", "holding_days",
            "tags", "notes", "created_at", "updated_at",
        ):
            assert key in result, f"missing key: {key}"


# ---------------------------------------------------------------------------
# TestCloseTrade
# ---------------------------------------------------------------------------

class TestCloseTrade:
    def test_valid_close_long(self):
        trade_id = _log(entry_price=1000.0, quantity=10)["trade_id"]
        result = _close(trade_id, exit_price=1100.0, exit_reason="TARGET_HIT")
        assert result["status"] == "CLOSED"
        assert result["pnl"] == 1000.0
        assert result["exit_reason"] == "TARGET_HIT"

    def test_valid_close_short(self):
        trade_id = _log(direction="SHORT", entry_price=1000.0, quantity=10)["trade_id"]
        result = _close(trade_id, exit_price=900.0, exit_reason="TARGET_HIT")
        assert result["pnl"] == 1000.0

    def test_pnl_percent_computed(self):
        trade_id = _log(entry_price=1000.0, quantity=1)["trade_id"]
        result = _close(trade_id, exit_price=1100.0)
        assert result["pnl_percent"] == pytest.approx(10.0, rel=1e-6)

    def test_holding_days_same_day(self):
        trade_id = _log()["trade_id"]
        result = _close(trade_id)
        assert result["holding_days"] == 0

    def test_trade_not_found_returns_error(self):
        result = _close("TRD-nonexistent")
        assert "error" in result
        assert "trade not found" in result["error"]

    def test_already_closed_returns_error(self):
        trade_id = _log()["trade_id"]
        _close(trade_id)
        result = _close(trade_id)
        assert "error" in result
        assert "already closed" in result["error"]

    def test_invalid_exit_reason_returns_error(self):
        trade_id = _log()["trade_id"]
        result = _close(trade_id, exit_reason="PROFIT_BOOKED")
        assert "error" in result
        assert "exit_reason" in result["error"]

    def test_exit_reason_case_insensitive(self):
        trade_id = _log()["trade_id"]
        result = _close(trade_id, exit_reason="target_hit")
        assert result["exit_reason"] == "TARGET_HIT"

    def test_notes_appended_to_existing(self):
        trade_id = _log(notes="initial note")["trade_id"]
        result = _close(trade_id, notes="close note")
        assert "initial note" in result["notes"]
        assert "close note" in result["notes"]

    def test_notes_none_preserves_existing(self):
        trade_id = _log(notes="initial note")["trade_id"]
        result = _close(trade_id, notes=None)
        assert result["notes"] == "initial note"

    def test_no_initial_notes_sets_close_note(self):
        trade_id = _log()["trade_id"]
        result = _close(trade_id, notes="stop hit")
        assert result["notes"] == "stop hit"

    def test_break_even_close(self):
        trade_id = _log(entry_price=1000.0, quantity=5)["trade_id"]
        result = _close(trade_id, exit_price=1000.0)
        assert result["pnl"] == 0.0
        assert result["pnl_percent"] == 0.0

    def test_cancelled_exit_reason_status_is_closed(self):
        trade_id = _log()["trade_id"]
        result = _close(trade_id, exit_reason="CANCELLED")
        assert result["status"] == "CLOSED"
        assert result["exit_reason"] == "CANCELLED"

    def test_exit_date_is_today(self):
        trade_id = _log()["trade_id"]
        result = _close(trade_id)
        assert result["exit_date"] == date.today().isoformat()


# ---------------------------------------------------------------------------
# TestGetOpenTrades
# ---------------------------------------------------------------------------

class TestGetOpenTrades:
    def test_no_open_trades(self):
        result = get_open_trades()
        assert result["count"] == 0
        assert result["trades"] == []

    def test_one_open_trade(self):
        _log()
        result = get_open_trades()
        assert result["count"] == 1

    def test_filter_by_symbol_found(self):
        _log(symbol="INFY")
        _log(symbol="TCS")
        result = get_open_trades(symbol="INFY")
        assert result["count"] == 1
        assert result["trades"][0]["symbol"] == "INFY"

    def test_filter_by_symbol_case_insensitive(self):
        _log(symbol="INFY")
        result = get_open_trades(symbol="infy")
        assert result["count"] == 1

    def test_filter_unknown_symbol_returns_zero(self):
        _log(symbol="INFY")
        result = get_open_trades(symbol="WIPRO")
        assert result["count"] == 0

    def test_closed_trades_excluded(self):
        trade_id = _log()["trade_id"]
        _close(trade_id)
        result = get_open_trades()
        assert result["count"] == 0

    def test_mixed_open_and_closed(self):
        t1 = _log(symbol="INFY")["trade_id"]
        _log(symbol="TCS")
        _close(t1)
        result = get_open_trades()
        assert result["count"] == 1
        assert result["trades"][0]["symbol"] == "TCS"

    def test_response_has_required_keys(self):
        result = get_open_trades()
        assert "count" in result
        assert "trades" in result


# ---------------------------------------------------------------------------
# TestGetTradeHistory
# ---------------------------------------------------------------------------

class TestGetTradeHistory:
    def test_no_trades_returns_valid_response(self):
        result = get_trade_history()
        assert result["count"] == 0
        assert result["trades"] == []
        assert "summary" in result
        assert "filters" in result

    def test_empty_summary_zeroed(self):
        result = get_trade_history()
        s = result["summary"]
        assert s["total_trades"] == 0
        assert s["win_count"] == 0
        assert s["total_pnl"] == 0.0
        assert s["best_trade"] is None
        assert s["worst_trade"] is None

    def test_days_filter_excludes_old_trades(self, fresh_db):
        # Insert a trade with entry_date 60 days ago
        old_date = (date.today() - timedelta(days=60)).isoformat()
        fresh_db.execute(
            "INSERT INTO trades (id, symbol, trade_type, direction, entry_price, "
            "entry_date, entry_time, created_by, status, created_at, updated_at) "
            "VALUES (?, 'OLD', 'EQUITY', 'LONG', 100.0, ?, '2026-01-01T00:00:00', "
            "'MANUAL', 'OPEN', '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
            ("TRD-oldtrade", old_date),
        )
        fresh_db.commit()
        result = get_trade_history(days=30)
        symbols = [t["symbol"] for t in result["trades"]]
        assert "OLD" not in symbols

    def test_days_0_returns_only_today(self):
        _log()
        result = get_trade_history(days=0)
        # entry_date >= today — today's trades included
        assert result["count"] == 1

    def test_status_filter_closed(self):
        t1 = _log(symbol="INFY")["trade_id"]
        _log(symbol="TCS")
        _close(t1)
        result = get_trade_history(status="CLOSED")
        assert all(t["status"] == "CLOSED" for t in result["trades"])

    def test_status_filter_open(self):
        t1 = _log(symbol="INFY")["trade_id"]
        _log(symbol="TCS")
        _close(t1)
        result = get_trade_history(status="OPEN")
        assert all(t["status"] == "OPEN" for t in result["trades"])

    def test_symbol_filter(self):
        _log(symbol="INFY")
        _log(symbol="TCS")
        result = get_trade_history(symbol="TCS")
        assert all(t["symbol"] == "TCS" for t in result["trades"])

    def test_limit_respected(self):
        for _ in range(5):
            _log()
        result = get_trade_history(limit=3)
        assert len(result["trades"]) == 3

    def test_win_rate_computed(self):
        # 3 wins, 1 loss → 75%
        for price in [1600.0, 1700.0, 1550.0]:
            t = _log(entry_price=1500.0, quantity=1)["trade_id"]
            _close(t, exit_price=price)
        t_loss = _log(entry_price=1500.0, quantity=1)["trade_id"]
        _close(t_loss, exit_price=1400.0)
        result = get_trade_history()
        assert result["summary"]["win_count"] == 3
        assert result["summary"]["loss_count"] == 1
        assert result["summary"]["win_rate_pct"] == 75.0

    def test_total_pnl_over_closed_only(self):
        t1 = _log(entry_price=1000.0, quantity=1)["trade_id"]
        _close(t1, exit_price=1100.0)  # pnl = 100
        _log(entry_price=1000.0)  # open, not included in pnl
        result = get_trade_history()
        assert result["summary"]["total_pnl"] == 100.0

    def test_best_and_worst_trade(self):
        t1 = _log(symbol="INFY", entry_price=1000.0, quantity=1)["trade_id"]
        _close(t1, exit_price=1200.0)  # pnl = 200
        t2 = _log(symbol="TCS", entry_price=1000.0, quantity=1)["trade_id"]
        _close(t2, exit_price=800.0)  # pnl = -200
        result = get_trade_history()
        assert result["summary"]["best_trade"]["symbol"] == "INFY"
        assert result["summary"]["worst_trade"]["symbol"] == "TCS"

    def test_avg_holding_days_computed(self):
        t1 = _log(entry_price=1000.0)["trade_id"]
        _close(t1)  # 0 days
        result = get_trade_history()
        assert result["summary"]["avg_holding_days"] == 0.0

    def test_filters_returned_in_response(self):
        result = get_trade_history(symbol="INFY", days=14, status="OPEN", limit=10)
        f = result["filters"]
        assert f["symbol"] == "INFY"
        assert f["days"] == 14
        assert f["status"] == "OPEN"
        assert f["limit"] == 10

    def test_combined_filters(self):
        _log(symbol="INFY")
        t2 = _log(symbol="TCS")["trade_id"]
        _close(t2)
        result = get_trade_history(symbol="INFY", status="OPEN")
        assert result["count"] == 1
        assert result["trades"][0]["symbol"] == "INFY"

    def test_analysis_snapshot_round_trips(self):
        snap = {"regime": "BULL_TREND", "risk_score": 30}
        _log(analysis_snapshot=snap)
        result = get_trade_history()
        assert result["trades"][0]["analysis_snapshot"] == snap


# ---------------------------------------------------------------------------
# TestBuildSummary
# ---------------------------------------------------------------------------

class TestBuildSummary:
    def _make_closed(self, pnl: float, symbol: str = "X") -> dict:
        return {
            "trade_id": f"TRD-{symbol.lower()}",
            "symbol": symbol,
            "status": "CLOSED",
            "pnl": pnl,
            "holding_days": 3,
        }

    def _make_open(self) -> dict:
        return {"trade_id": "TRD-open", "symbol": "Y", "status": "OPEN", "pnl": None, "holding_days": None}

    def test_empty_list(self):
        s = _build_summary([])
        assert s["total_trades"] == 0
        assert s["win_rate_pct"] == 0.0
        assert s["best_trade"] is None

    def test_all_wins(self):
        trades = [self._make_closed(100.0, "A"), self._make_closed(200.0, "B")]
        s = _build_summary(trades)
        assert s["win_count"] == 2
        assert s["loss_count"] == 0
        assert s["win_rate_pct"] == 100.0

    def test_best_worst_correct(self):
        trades = [
            self._make_closed(500.0, "WIN"),
            self._make_closed(-300.0, "LOSS"),
        ]
        s = _build_summary(trades)
        assert s["best_trade"]["symbol"] == "WIN"
        assert s["worst_trade"]["symbol"] == "LOSS"

    def test_open_trades_excluded_from_pnl(self):
        trades = [self._make_closed(100.0), self._make_open()]
        s = _build_summary(trades)
        assert s["total_pnl"] == 100.0
        assert s["open_trades"] == 1
        assert s["closed_trades"] == 1
