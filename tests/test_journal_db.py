"""Tests for src/journal/db.py — connection factory and schema initialisation."""
from __future__ import annotations

import sqlite3

import pytest

import src.journal.db as journal_db

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
# TestSchemaInit
# ---------------------------------------------------------------------------

class TestSchemaInit:
    def test_trades_table_exists(self, fresh_db):
        row = fresh_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='trades'"
        ).fetchone()
        assert row is not None

    def test_schema_version_table_exists(self, fresh_db):
        row = fresh_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone()
        assert row is not None

    def test_schema_version_is_current(self, fresh_db):
        version = journal_db._get_schema_version(fresh_db)
        assert version == journal_db._SCHEMA_VERSION

    def test_idempotent_double_init(self, fresh_db):
        journal_db._init_schema(fresh_db)
        journal_db._init_schema(fresh_db)
        rows = fresh_db.execute("SELECT version FROM schema_version").fetchall()
        assert len(rows) == 1

    def test_symbol_index_exists(self, fresh_db):
        row = fresh_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_trades_symbol'"
        ).fetchone()
        assert row is not None

    def test_status_index_exists(self, fresh_db):
        row = fresh_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_trades_status'"
        ).fetchone()
        assert row is not None

    def test_entry_date_index_exists(self, fresh_db):
        row = fresh_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_trades_entry_date'"
        ).fetchone()
        assert row is not None

    def test_trade_type_index_exists(self, fresh_db):
        row = fresh_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_trades_trade_type'"
        ).fetchone()
        assert row is not None

    def test_trades_table_has_analysis_snapshot_column(self, fresh_db):
        cols = [
            row[1]
            for row in fresh_db.execute("PRAGMA table_info(trades)").fetchall()
        ]
        assert "analysis_snapshot" in cols

    def test_trades_table_has_trade_type_column(self, fresh_db):
        cols = [
            row[1]
            for row in fresh_db.execute("PRAGMA table_info(trades)").fetchall()
        ]
        assert "trade_type" in cols

    def test_trades_table_has_created_by_column(self, fresh_db):
        cols = [
            row[1]
            for row in fresh_db.execute("PRAGMA table_info(trades)").fetchall()
        ]
        assert "created_by" in cols


# ---------------------------------------------------------------------------
# TestConnectionFactory
# ---------------------------------------------------------------------------

class TestConnectionFactory:
    def test_get_connection_returns_injected_conn(self, fresh_db):
        assert journal_db._get_connection() is fresh_db

    def test_reset_connection_clears_conn(self):
        journal_db.reset_connection(None)
        # After clearing, _conn is None — we don't call _get_connection() here
        # because it would try to open "journal.db" on disk
        assert journal_db._conn is None
        # Restore fixture state so autouse teardown doesn't fail
        journal_db.reset_connection(sqlite3.connect(":memory:"))

    def test_reset_connection_accepts_new_conn(self):
        new_conn = sqlite3.connect(":memory:")
        new_conn.row_factory = sqlite3.Row
        journal_db._init_schema(new_conn)
        journal_db.reset_connection(new_conn)
        assert journal_db._get_connection() is new_conn
        new_conn.close()


# ---------------------------------------------------------------------------
# TestSchemaVersion
# ---------------------------------------------------------------------------

class TestSchemaVersion:
    def test_get_schema_version_returns_current(self, fresh_db):
        assert journal_db._get_schema_version(fresh_db) == journal_db._SCHEMA_VERSION

    def test_get_schema_version_returns_none_for_empty_table(self, fresh_db):
        fresh_db.execute("DELETE FROM schema_version")
        fresh_db.commit()
        assert journal_db._get_schema_version(fresh_db) is None

    def test_schema_version_applied_field_is_iso_datetime(self, fresh_db):
        row = fresh_db.execute("SELECT applied FROM schema_version").fetchone()
        assert row is not None
        applied = row[0]
        assert "T" in applied
        assert len(applied) == 19


# ---------------------------------------------------------------------------
# TestLibsqlConnParamCoercion
# ---------------------------------------------------------------------------

class _RecordingConn:
    """Stub libsql connection that records the params type it was handed.

    libsql_experimental raises "'list' object cannot be converted to 'PyTuple'"
    when positional params arrive as a list. This stub lets us assert the
    _LibsqlConn wrapper coerces lists to tuples before forwarding.
    """

    def __init__(self):
        self.received = []

    def execute(self, sql, params=None):
        if params is not None:
            self.received.append(params)
        return _StubCursor()


class _StubCursor:
    description = ()

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class TestLibsqlConnParamCoercion:
    """Guards the Turso/libsql param-type fix (list -> tuple)."""

    def test_list_params_coerced_to_tuple(self):
        stub = _RecordingConn()
        wrapped = journal_db._LibsqlConn(stub)
        wrapped.execute("SELECT * FROM trades WHERE symbol = ? LIMIT ?", ["IDEA", 50])
        assert stub.received, "underlying execute was not called with params"
        forwarded = stub.received[-1]
        assert isinstance(forwarded, tuple), (
            f"libsql wrapper must forward a tuple, got {type(forwarded).__name__}"
        )
        assert forwarded == ("IDEA", 50)

    def test_tuple_params_passed_through_unchanged(self):
        stub = _RecordingConn()
        wrapped = journal_db._LibsqlConn(stub)
        wrapped.execute("SELECT * FROM trades WHERE id = ?", ("TRD-1234",))
        assert stub.received[-1] == ("TRD-1234",)
        assert isinstance(stub.received[-1], tuple)

    def test_empty_params_takes_no_arg_path(self):
        stub = _RecordingConn()
        wrapped = journal_db._LibsqlConn(stub)
        # Empty params must use the no-arg execute branch (records nothing).
        wrapped.execute("SELECT 1")
        assert stub.received == []
