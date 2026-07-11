"""Phase 23 — /buy /sell argument parser tests (pure, Telegram-free)."""
from __future__ import annotations

from src.telegram_admin.order_parser import parse_order_args, ParseError, _is_derivative_symbol


def _ok(args, side="BUY"):
    r = parse_order_args(args, side)
    assert not isinstance(r, ParseError), r
    return r


class TestParseOrderArgs:

    def test_minimal_market_defaults(self):
        r = _ok(["RELIANCE", "1"])
        assert r.symbol == "RELIANCE"
        assert r.quantity == 1
        assert r.order_type == "MARKET"
        assert r.product == "INTRADAY"
        assert r.exchange == "NSE"
        assert r.segment == "EQUITY"
        assert r.transaction_type == "BUY"
        assert r.security_id == ""  # resolved later

    def test_limit_with_price(self):
        r = _ok(["TCS", "5", "LIMIT", "3900"], side="SELL")
        assert r.transaction_type == "SELL"
        assert r.order_type == "LIMIT"
        assert r.limit_price == 3900.0

    def test_product_and_exchange_flags(self):
        r = _ok(["TCS", "5", "LIMIT", "3900", "CNC", "BSE"])
        assert r.product == "CNC"
        assert r.exchange == "BSE"

    def test_flags_order_independent(self):
        r = _ok(["TCS", "5", "BSE", "CNC", "LIMIT", "10"])
        assert r.product == "CNC" and r.exchange == "BSE" and r.limit_price == 10.0

    def test_lowercase_symbol_uppercased(self):
        assert _ok(["reliance", "1"]).symbol == "RELIANCE"

    # --- errors ---

    def test_too_few_args(self):
        assert isinstance(parse_order_args([], "BUY"), ParseError)
        assert isinstance(parse_order_args(["RELIANCE"], "BUY"), ParseError)

    def test_non_integer_qty(self):
        assert isinstance(parse_order_args(["RELIANCE", "x"], "BUY"), ParseError)

    def test_zero_or_negative_qty(self):
        assert isinstance(parse_order_args(["RELIANCE", "0"], "BUY"), ParseError)
        assert isinstance(parse_order_args(["RELIANCE", "-3"], "BUY"), ParseError)

    def test_limit_without_price(self):
        assert isinstance(parse_order_args(["RELIANCE", "1", "LIMIT"], "BUY"), ParseError)

    def test_limit_bad_price(self):
        assert isinstance(parse_order_args(["RELIANCE", "1", "LIMIT", "abc"], "BUY"), ParseError)

    def test_unknown_token(self):
        assert isinstance(parse_order_args(["RELIANCE", "1", "WAT"], "BUY"), ParseError)


class TestDerivativeDetection:

    def test_equity_ending_in_ce_pe_stays_equity(self):
        # RELIANCE ends in "CE" but is not an option.
        assert not _is_derivative_symbol("RELIANCE")
        assert not _is_derivative_symbol("ONGC")
        assert _ok(["RELIANCE", "1"]).segment == "EQUITY"

    def test_option_symbols(self):
        assert _is_derivative_symbol("NIFTY24200CE")
        assert _is_derivative_symbol("BANKNIFTY52000PE")
        assert _ok(["NIFTY24200CE", "75"]).segment == "DERIVATIVE"

    def test_futures(self):
        assert _is_derivative_symbol("NIFTYNXT50FUT")
