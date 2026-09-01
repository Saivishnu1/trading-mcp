"""Tests for Phase 16 — Zerodha auto-import (sync_zerodha_orders)."""
import sqlite3
from datetime import datetime, timedelta

import pytest

import src.journal.db as journal_db
from src.journal.service import (
    _parse_order_timestamp,
    _product_to_trade_type,
    get_open_trades,
    get_trade_history,
    sync_zerodha_orders,
)

# Anchored to the real run date, not a hardcoded string (2026-07-23 bug:
# get_trade_history's default 30-day lookback window silently excluded a
# trade whose hardcoded fixture date had aged out of it as real time passed
# — the exact "wall-clock date drift" bug class this codebase has hit
# before, just in a test fixture instead of production code this time).
_TODAY = datetime.now().strftime("%Y-%m-%d")
_YESTERDAY = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def _make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    journal_db._init_schema(conn)
    return conn


def _order(
    order_id="ORD001",
    symbol="RELIANCE",
    txn="BUY",
    price=2500.0,
    qty=10,
    status="COMPLETE",
    product="CNC",
    ts=f"{_TODAY} 10:30:00",
):
    return {
        "order_id": order_id,
        "tradingsymbol": symbol,
        "transaction_type": txn,
        "average_price": price,
        "filled_quantity": qty,
        "status": status,
        "product": product,
        "order_timestamp": ts,
    }


@pytest.fixture(autouse=True)
def fresh_db():
    conn = _make_conn()
    journal_db.reset_connection(conn)
    yield
    journal_db.reset_connection(None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestParseOrderTimestamp:
    def test_space_separated(self):
        d, t = _parse_order_timestamp("2026-06-19 10:30:00")
        assert d == "2026-06-19"
        assert t == "10:30:00"

    def test_iso_format(self):
        d, t = _parse_order_timestamp("2026-06-19T10:30:00")
        assert d == "2026-06-19"
        assert t == "10:30:00"

    def test_empty_returns_today(self):
        d, t = _parse_order_timestamp("")
        assert len(d) == 10  # YYYY-MM-DD


class TestProductToTradeType:
    def test_cnc_equity(self):
        assert _product_to_trade_type("CNC", "RELIANCE") == "EQUITY"

    def test_mis_equity(self):
        assert _product_to_trade_type("MIS", "INFY") == "EQUITY"

    def test_options_ce(self):
        assert _product_to_trade_type("NRML", "NIFTY24JUN24000CE") == "OPTIONS"

    def test_options_pe(self):
        assert _product_to_trade_type("NRML", "BANKNIFTY24JUN50000PE") == "OPTIONS"

    def test_futures(self):
        assert _product_to_trade_type("NRML", "RELIANCE24JUNFUT") == "FUTURES"


# ---------------------------------------------------------------------------
# sync_zerodha_orders
# ---------------------------------------------------------------------------

class TestSyncBuyOrders:
    def test_buy_creates_open_long(self):
        result = sync_zerodha_orders([_order()])
        assert result["imported"] == 1
        trades = get_open_trades()["trades"]
        assert len(trades) == 1
        assert trades[0]["symbol"] == "RELIANCE"
        assert trades[0]["direction"] == "LONG"

    def test_buy_sets_external_id(self):
        sync_zerodha_orders([_order(order_id="ORD999")])
        trades = get_open_trades()["trades"]
        assert trades[0]["external_id"] == "ORD999"

    def test_buy_sets_created_by_zerodha_sync(self):
        sync_zerodha_orders([_order()])
        trades = get_open_trades()["trades"]
        assert trades[0]["created_by"] == "ZERODHA_SYNC"

    def test_buy_uses_order_timestamp(self):
        sync_zerodha_orders([_order(ts=f"{_YESTERDAY} 09:15:00")])
        trades = get_open_trades()["trades"]
        assert trades[0]["entry_date"] == _YESTERDAY

    def test_buy_dedup_skips_already_imported(self):
        sync_zerodha_orders([_order(order_id="ORD001")])
        result = sync_zerodha_orders([_order(order_id="ORD001")])
        assert result["imported"] == 0
        assert result["skipped"] == 1
        assert get_open_trades()["count"] == 1  # still only one trade

    def test_non_complete_order_skipped(self):
        result = sync_zerodha_orders([_order(status="OPEN")])
        assert result["skipped"] == 1
        assert result["imported"] == 0


class TestSyncSellOrders:
    def test_sell_closes_open_long(self):
        sync_zerodha_orders([_order(order_id="B1", txn="BUY", price=2500.0)])
        result = sync_zerodha_orders([_order(order_id="S1", txn="SELL", price=2600.0)])
        assert result["closed"] == 1
        history = get_trade_history(status="CLOSED")["trades"]
        assert len(history) == 1
        assert history[0]["pnl"] == 1000.0  # (2600-2500) * 10

    def test_sell_no_open_long_goes_to_unmatched(self):
        result = sync_zerodha_orders([_order(txn="SELL", price=2600.0)])
        assert result["unmatched_sells"] == 1
        assert result["imported"] == 0

    def test_sell_idempotent_after_close(self):
        sync_zerodha_orders([_order(order_id="B1", txn="BUY")])
        sync_zerodha_orders([_order(order_id="S1", txn="SELL", price=2600.0)])
        # run sell again — LONG is now CLOSED, no match found
        result = sync_zerodha_orders([_order(order_id="S1", txn="SELL", price=2600.0)])
        assert result["unmatched_sells"] == 1
        assert result["closed"] == 0


class TestSyncIntraday:
    def test_buy_then_sell_same_symbol_same_batch(self):
        orders = [
            _order(order_id="B1", txn="BUY",  price=2500.0, ts=f"{_TODAY} 09:30:00"),
            _order(order_id="S1", txn="SELL", price=2550.0, ts=f"{_TODAY} 15:00:00"),
        ]
        result = sync_zerodha_orders(orders)
        assert result["imported"] == 1
        assert result["closed"] == 1
        assert result["errors"] == 0

    def test_multiple_symbols(self):
        orders = [
            _order(order_id="B1", symbol="INFY",     txn="BUY", price=1800.0),
            _order(order_id="B2", symbol="RELIANCE",  txn="BUY", price=2500.0),
        ]
        result = sync_zerodha_orders(orders)
        assert result["imported"] == 2
        assert get_open_trades()["count"] == 2


class TestSyncEdgeCases:
    def test_empty_order_list(self):
        result = sync_zerodha_orders([])
        assert result["imported"] == 0
        assert result["errors"] == 0

    def test_invalid_price_skipped(self):
        order = _order()
        order["average_price"] = 0
        result = sync_zerodha_orders([order])
        assert result["skipped"] == 1

    def test_schema_has_external_id_column(self):
        conn = journal_db._get_connection()
        cols = {row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()}
        assert "external_id" in cols

    def test_schema_version_is_7(self):
        conn = journal_db._get_connection()
        version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
        assert version == 7
