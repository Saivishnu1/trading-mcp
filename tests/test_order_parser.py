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


class TestSlTargetTrail:

    def test_sl_only_defaults_limit_to_trigger(self):
        r = _ok(["RELIANCE", "1", "SL", "2820"])
        assert r.sl_trigger_price == 2820.0
        assert r.sl_limit_price == 2820.0
        assert r.tgt_trigger_price is None
        assert r.is_smart_order

    def test_sl_with_explicit_limit(self):
        r = _ok(["RELIANCE", "1", "SL", "2820", "2810"])
        assert r.sl_trigger_price == 2820.0
        assert r.sl_limit_price == 2810.0

    def test_target_only(self):
        r = _ok(["RELIANCE", "1", "TARGET", "2950"])
        assert r.tgt_trigger_price == 2950.0
        assert r.tgt_limit_price == 2950.0
        assert r.is_smart_order

    def test_sl_and_target_together(self):
        r = _ok(["RELIANCE", "1", "LIMIT", "2870", "SL", "2820", "TARGET", "2950"])
        assert r.limit_price == 2870.0
        assert r.sl_trigger_price == 2820.0
        assert r.tgt_trigger_price == 2950.0

    def test_trail_with_sl(self):
        r = _ok(["RELIANCE", "1", "SL", "2820", "TRAIL", "5"])
        assert r.trailing_sl_points == 5.0
        assert r.sl_trigger_price == 2820.0

    def test_trail_without_sl_is_error(self):
        assert isinstance(parse_order_args(["RELIANCE", "1", "TRAIL", "5"], "BUY"), ParseError)

    def test_no_legs_not_smart_order(self):
        r = _ok(["RELIANCE", "1"])
        assert not r.is_smart_order

    def test_sl_requires_price(self):
        assert isinstance(parse_order_args(["RELIANCE", "1", "SL"], "BUY"), ParseError)

    def test_sl_bad_price(self):
        assert isinstance(parse_order_args(["RELIANCE", "1", "SL", "abc"], "BUY"), ParseError)

    def test_target_requires_price(self):
        assert isinstance(parse_order_args(["RELIANCE", "1", "TARGET"], "BUY"), ParseError)

    def test_trail_requires_value(self):
        assert isinstance(parse_order_args(["RELIANCE", "1", "SL", "2820", "TRAIL"], "BUY"), ParseError)

    def test_trail_bad_value(self):
        assert isinstance(parse_order_args(["RELIANCE", "1", "SL", "2820", "TRAIL", "abc"], "BUY"), ParseError)


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

    def test_hyphenated_index_option_symbols(self):
        # Confirmed bug (2026-07-12): INDstocks' own TRADING_SYMBOL for index
        # options is hyphenated ("NIFTY-JUL2026-24250-CE"), not the compact
        # Telegram-typed format this regex was originally written for. Every
        # option order placed via the web dropdown was silently misclassified
        # as segment="EQUITY" and rejected by INDstocks with an opaque 512
        # Internal Server Error as a result.
        assert _is_derivative_symbol("NIFTY-JUL2026-24250-CE")
        assert _is_derivative_symbol("NIFTY-JUL2026-27500-PE")
