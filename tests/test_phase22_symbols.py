"""Tests for Phase 22 normalize_symbol() — src/market/symbols.py."""
from __future__ import annotations

import pytest

from src.market.symbols import normalize_symbol


class TestNormalizeSymbol:
    # get_quote → NSE:{symbol}
    def test_quote_bare_symbol(self):
        result, corrected = normalize_symbol("INFY", "get_quote")
        assert result == "NSE:INFY"
        assert corrected is True

    def test_quote_already_prefixed(self):
        result, corrected = normalize_symbol("NSE:INFY", "get_quote")
        assert result == "NSE:INFY"
        assert corrected is False

    def test_quote_strips_ns_suffix(self):
        result, corrected = normalize_symbol("INFY.NS", "get_quote")
        assert result == "NSE:INFY"
        assert corrected is True

    # analyze_technicals → {symbol}.NS
    def test_technicals_bare_symbol(self):
        result, corrected = normalize_symbol("IDEA", "analyze_technicals")
        assert result == "IDEA.NS"
        assert corrected is True

    def test_technicals_already_ns(self):
        result, corrected = normalize_symbol("IDEA.NS", "analyze_technicals")
        assert result == "IDEA.NS"
        assert corrected is False

    def test_technicals_strips_nse_prefix(self):
        result, corrected = normalize_symbol("NSE:IDEA", "analyze_technicals")
        assert result == "IDEA.NS"
        assert corrected is True

    # detect_market_regime → bare {symbol}
    def test_regime_bare_symbol(self):
        result, corrected = normalize_symbol("RELIANCE", "detect_market_regime")
        assert result == "RELIANCE"
        assert corrected is False

    # Index aliases — pass through canonical yfinance resolution
    def test_nifty_index_passthrough(self):
        result, corrected = normalize_symbol("NIFTY", "get_quote")
        assert result == "^NSEI"

    def test_banknifty_index_passthrough(self):
        result, corrected = normalize_symbol("BANKNIFTY", "analyze_technicals")
        assert result == "^NSEBANK"

    # Unknown tool → pass through unchanged
    def test_unknown_tool_passthrough(self):
        result, corrected = normalize_symbol("INFY", "unknown_tool")
        assert result == "INFY"
        assert corrected is False

    # Upper-casing
    def test_lowercase_symbol_uppercased(self):
        result, _ = normalize_symbol("idea", "analyze_technicals")
        assert result == "IDEA.NS"

    def test_get_historical_data_format(self):
        result, _ = normalize_symbol("TCS", "get_historical_data")
        assert result == "TCS.NS"

    def test_generate_trade_setup_format(self):
        result, _ = normalize_symbol("HDFCBANK", "generate_trade_setup")
        assert result == "HDFCBANK.NS"
