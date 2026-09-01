"""Tests for Priorities B4/B5 (2026-07-11) — re-entry pattern detection and
the strike-level attempt tally, both observational-only per the task's
explicit "no auto-reject" scope. Uses the same fresh in-memory SQLite fixture
as test_journal_service.py."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta, timezone

import pytest

import src.journal.db as journal_db
from src.journal.service import (
    _parse_option_symbol,
    close_trade,
    detect_reentry_pattern,
    get_strike_attempts,
    log_trade,
)


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


def _iso_minutes_ago(minutes: float) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S")


class TestParseOptionSymbol:
    def test_parses_zerodha_monthly_format(self):
        assert _parse_option_symbol("NIFTY26JUL24400CE") == ("NIFTY", 24400.0, "CE")

    def test_parses_loose_format_with_spaces(self):
        assert _parse_option_symbol("NIFTY 24200 CE") == ("NIFTY", 24200.0, "CE")

    def test_returns_none_for_unparseable_symbol(self):
        assert _parse_option_symbol("INFY") is None

    def test_different_strikes_are_distinct_keys(self):
        assert _parse_option_symbol("NIFTY 24200 CE") != _parse_option_symbol("NIFTY 24300 CE")


class TestDetectReentryPattern:
    def test_no_warning_on_first_entry(self):
        assert detect_reentry_pattern("NIFTY 24200 CE") is None

    def test_no_warning_for_unparseable_symbol(self):
        log_trade(symbol="INFY", direction="LONG", entry_price=1500.0)
        assert detect_reentry_pattern("INFY") is None

    def test_warns_on_third_entry_within_window(self):
        for _ in range(2):
            log_trade(symbol="NIFTY 24200 CE", direction="LONG", entry_price=100.0,
                      entry_time=_iso_minutes_ago(10))
        warning = detect_reentry_pattern("NIFTY 24200 CE")
        assert warning is not None
        assert "3rd" in warning or "3th" in warning
        assert "NIFTY 24200 CE" in warning

    def test_no_warning_when_only_two_prior_entries(self):
        log_trade(symbol="NIFTY 24200 CE", direction="LONG", entry_price=100.0,
                  entry_time=_iso_minutes_ago(10))
        assert detect_reentry_pattern("NIFTY 24200 CE") is None

    def test_prior_entries_outside_window_do_not_count(self):
        for _ in range(2):
            log_trade(symbol="NIFTY 24200 CE", direction="LONG", entry_price=100.0,
                      entry_time=_iso_minutes_ago(200))  # outside default 120min window
        assert detect_reentry_pattern("NIFTY 24200 CE") is None

    def test_warns_on_recent_loss_on_same_strike_regardless_of_count(self):
        result = log_trade(symbol="NIFTY 24200 CE", direction="LONG", entry_price=100.0,
                            entry_time=_iso_minutes_ago(15))
        close_trade(trade_id=result["trade_id"], exit_price=50.0, exit_reason="STOPLOSS_HIT")
        warning = detect_reentry_pattern("NIFTY 24200 CE")
        assert warning is not None
        assert "closed at -" in warning

    def test_no_loss_warning_when_prior_close_was_a_win(self):
        result = log_trade(symbol="NIFTY 24200 CE", direction="LONG", entry_price=100.0,
                            entry_time=_iso_minutes_ago(15))
        close_trade(trade_id=result["trade_id"], exit_price=150.0, exit_reason="TARGET_HIT")
        assert detect_reentry_pattern("NIFTY 24200 CE") is None

    def test_no_loss_warning_when_loss_was_over_30_minutes_ago(self, fresh_db):
        result = log_trade(symbol="NIFTY 24200 CE", direction="LONG", entry_price=100.0,
                            entry_time=_iso_minutes_ago(60))
        close_trade(trade_id=result["trade_id"], exit_price=50.0, exit_reason="STOPLOSS_HIT")
        # close_trade always stamps exit_time as "now" — backdate it directly
        # to actually exercise the >30-minute branch.
        fresh_db.execute(
            "UPDATE trades SET exit_time = ? WHERE id = ?",
            (_iso_minutes_ago(60), result["trade_id"]),
        )
        fresh_db.commit()
        assert detect_reentry_pattern("NIFTY 24200 CE") is None

    def test_different_strike_does_not_trigger_warning(self):
        for _ in range(2):
            log_trade(symbol="NIFTY 24200 CE", direction="LONG", entry_price=100.0,
                      entry_time=_iso_minutes_ago(10))
        assert detect_reentry_pattern("NIFTY 24300 CE") is None


class TestLogTradeReentryIntegration:
    def test_log_trade_surfaces_reentry_warning_additively(self):
        for _ in range(2):
            log_trade(symbol="NIFTY 24200 CE", direction="LONG", entry_price=100.0,
                      entry_time=_iso_minutes_ago(10))
        result = log_trade(symbol="NIFTY 24200 CE", direction="LONG", entry_price=105.0)
        assert "REENTRY_WARNING" in result
        assert "trade_id" in result  # normal fields still present

    def test_log_trade_never_blocks_even_with_warning(self):
        for _ in range(5):
            log_trade(symbol="NIFTY 24200 CE", direction="LONG", entry_price=100.0,
                      entry_time=_iso_minutes_ago(5))
        result = log_trade(symbol="NIFTY 24200 CE", direction="LONG", entry_price=110.0)
        assert "error" not in result
        assert result["status"] == "OPEN"

    def test_log_trade_no_warning_key_when_no_pattern(self):
        result = log_trade(symbol="NIFTY 24200 CE", direction="LONG", entry_price=100.0)
        assert "REENTRY_WARNING" not in result


class TestGetStrikeAttempts:
    def test_empty_when_no_trades_today(self):
        result = get_strike_attempts()
        assert result["strikes"] == []

    def test_tallies_attempts_wins_losses_and_net_pnl(self):
        t1 = log_trade(symbol="NIFTY 24200 CE", direction="LONG", entry_price=100.0)
        close_trade(trade_id=t1["trade_id"], exit_price=150.0, exit_reason="TARGET_HIT")
        t2 = log_trade(symbol="NIFTY 24200 CE", direction="LONG", entry_price=100.0)
        close_trade(trade_id=t2["trade_id"], exit_price=50.0, exit_reason="STOPLOSS_HIT")
        log_trade(symbol="NIFTY 24200 CE", direction="LONG", entry_price=100.0)  # still open

        result = get_strike_attempts("NIFTY")
        assert len(result["strikes"]) == 1
        entry = result["strikes"][0]
        assert entry["underlying"] == "NIFTY"
        assert entry["strike"] == 24200.0
        assert entry["option_type"] == "CE"
        assert entry["attempts"] == 3
        assert entry["wins"] == 1
        assert entry["losses"] == 1
        assert entry["net_pnl"] == pytest.approx(0.0, abs=0.01)
        assert "tested 3 times today" in entry["summary"]

    def test_groups_separately_by_strike_and_option_type(self):
        log_trade(symbol="NIFTY 24200 CE", direction="LONG", entry_price=100.0)
        log_trade(symbol="NIFTY 24200 PE", direction="LONG", entry_price=90.0)
        log_trade(symbol="NIFTY 24300 CE", direction="LONG", entry_price=80.0)

        result = get_strike_attempts("NIFTY")
        assert len(result["strikes"]) == 3

    def test_filters_by_underlying(self):
        log_trade(symbol="NIFTY 24200 CE", direction="LONG", entry_price=100.0)
        log_trade(symbol="INFY", direction="LONG", entry_price=1500.0)  # unparseable, excluded anyway

        result = get_strike_attempts("BANKNIFTY")
        assert result["strikes"] == []
        assert result["underlying"] == "BANKNIFTY"

    def test_sorted_by_attempts_descending(self):
        for _ in range(3):
            log_trade(symbol="NIFTY 24200 CE", direction="LONG", entry_price=100.0)
        log_trade(symbol="NIFTY 24300 CE", direction="LONG", entry_price=80.0)

        result = get_strike_attempts("NIFTY")
        assert result["strikes"][0]["attempts"] == 3
        assert result["strikes"][1]["attempts"] == 1


class TestGetStrikeAttemptsToolRegistration:
    def test_tool_wraps_data_and_meta(self):
        from mcp.server.fastmcp import FastMCP as _FastMCP

        from src.tools import journal as journal_tools

        log_trade(symbol="NIFTY 24200 CE", direction="LONG", entry_price=100.0)

        mcp = _FastMCP("test")
        journal_tools.register(mcp)
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}

        result = tools["get_strike_attempts"].fn(underlying="NIFTY")
        assert result["data"]["strikes"][0]["attempts"] == 1
        assert result["meta"]["source"] == "internal_journal"
