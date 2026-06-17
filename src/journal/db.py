import os
import sqlite3
import threading
from datetime import datetime, timezone

_DB_PATH = os.environ.get("JOURNAL_DB", "journal.db")
_INIT_LOCK = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA_VERSION = 2

_DDL_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_version (
    version  INTEGER NOT NULL,
    applied  TEXT    NOT NULL
)
"""

_DDL_TRADES = """
CREATE TABLE IF NOT EXISTS trades (
    id                      TEXT    PRIMARY KEY,
    symbol                  TEXT    NOT NULL,
    trade_type              TEXT    NOT NULL DEFAULT 'EQUITY',
    direction               TEXT    NOT NULL,
    strategy                TEXT,
    entry_price             REAL    NOT NULL,
    quantity                INTEGER,
    entry_date              TEXT    NOT NULL,
    entry_time              TEXT    NOT NULL,
    rationale               TEXT,
    stoploss                REAL,
    target                  REAL,
    risk_reward             REAL,
    regime                  TEXT,
    signal                  TEXT,
    risk_score              INTEGER,
    analysis_snapshot       TEXT,
    created_by              TEXT    NOT NULL DEFAULT 'MANUAL',
    status                  TEXT    NOT NULL DEFAULT 'OPEN',
    exit_price              REAL,
    exit_date               TEXT,
    exit_time               TEXT,
    exit_reason             TEXT,
    pnl                     REAL,
    pnl_percent             REAL,
    holding_days            INTEGER,
    tags                    TEXT,
    notes                   TEXT,
    risk_amount             REAL,
    capital_at_risk         REAL,
    portfolio_heat_at_entry REAL,
    created_at              TEXT    NOT NULL,
    updated_at              TEXT    NOT NULL
)
"""

# v1 → v2: add entry-time sizing snapshot columns (immutable after creation)
_V2_MIGRATIONS = [
    "ALTER TABLE trades ADD COLUMN risk_amount REAL",
    "ALTER TABLE trades ADD COLUMN capital_at_risk REAL",
    "ALTER TABLE trades ADD COLUMN portfolio_heat_at_entry REAL",
]

_DDL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_trades_symbol     ON trades(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_trades_status     ON trades(status)",
    "CREATE INDEX IF NOT EXISTS idx_trades_entry_date ON trades(entry_date)",
    "CREATE INDEX IF NOT EXISTS idx_trades_trade_type ON trades(trade_type)",
]


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(_DDL_SCHEMA_VERSION)
    conn.execute(_DDL_TRADES)
    for idx_sql in _DDL_INDEXES:
        conn.execute(idx_sql)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    existing_version = _get_schema_version(conn)
    if existing_version is None:
        conn.execute(
            "INSERT INTO schema_version (version, applied) VALUES (?, ?)",
            (_SCHEMA_VERSION, now),
        )
    elif existing_version < _SCHEMA_VERSION:
        if existing_version < 2:
            for sql in _V2_MIGRATIONS:
                try:
                    conn.execute(sql)
                except Exception:
                    pass  # column already exists (idempotent)
        conn.execute(
            "UPDATE schema_version SET version = ?, applied = ?",
            (_SCHEMA_VERSION, now),
        )
    conn.commit()


def _get_schema_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    return row[0] if row else None


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _init_schema(conn)
    return conn


def _get_connection() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        with _INIT_LOCK:
            if _conn is None:
                _conn = _connect(_DB_PATH)
    return _conn


def reset_connection(conn: sqlite3.Connection | None = None) -> None:
    """Inject a connection. Used by tests to swap in an in-memory database."""
    global _conn
    _conn = conn
