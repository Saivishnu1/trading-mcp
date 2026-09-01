"""Tests for Phase 22 trust-metadata layer — src/meta.py."""
from __future__ import annotations

import math
from unittest.mock import patch

import pytest

from src.meta import (
    DQ_INVALID,
    DQ_NAN,
    DQ_STALE,
    DQ_VALID,
    RS_EXPERIMENTAL,
    RS_NOT_TESTED,
    TYPE_FACT,
    TYPE_INDICATOR,
    TYPE_INTERPRETATION,
    TYPE_PREDICTION,
    VALIDATION_COMPUTED,
    VALIDATION_UNVALIDATED,
    VALIDATION_VERIFIED,
    build_meta,
    detect_data_quality,
    indicator_meta,
    interpretation_meta,
    is_market_hours,
    journal_meta,
    market_meta,
    wrap,
)

# ---------------------------------------------------------------------------
# is_market_hours
# ---------------------------------------------------------------------------

class TestIsMarketHours:
    def _patch_now(self, hour, minute):
        from datetime import datetime, timedelta, timezone
        IST = timezone(timedelta(hours=5, minutes=30))
        dt = datetime(2026, 6, 19, hour, minute, 0, tzinfo=IST)
        return patch("src.meta.datetime", wraps=__import__("datetime").datetime)

    def test_inside_session(self):
        from datetime import datetime, timedelta, timezone
        IST = timezone(timedelta(hours=5, minutes=30))
        dt = datetime(2026, 6, 19, 10, 30, 0, tzinfo=IST)
        with patch("src.meta.datetime") as mock_dt:
            mock_dt.now.return_value = dt
            mock_dt.now.side_effect = None
            assert is_market_hours() is True

    def test_before_open(self):
        from datetime import datetime, timedelta, timezone
        IST = timezone(timedelta(hours=5, minutes=30))
        dt = datetime(2026, 6, 19, 9, 0, 0, tzinfo=IST)
        with patch("src.meta.datetime") as mock_dt:
            mock_dt.now.return_value = dt
            assert is_market_hours() is False

    def test_after_close(self):
        from datetime import datetime, timedelta, timezone
        IST = timezone(timedelta(hours=5, minutes=30))
        dt = datetime(2026, 6, 19, 16, 0, 0, tzinfo=IST)
        with patch("src.meta.datetime") as mock_dt:
            mock_dt.now.return_value = dt
            assert is_market_hours() is False

    def test_at_open_exact(self):
        from datetime import datetime, timedelta, timezone
        IST = timezone(timedelta(hours=5, minutes=30))
        dt = datetime(2026, 6, 19, 9, 15, 0, tzinfo=IST)
        with patch("src.meta.datetime") as mock_dt:
            mock_dt.now.return_value = dt
            assert is_market_hours() is True

    def test_at_close_exact(self):
        from datetime import datetime, timedelta, timezone
        IST = timezone(timedelta(hours=5, minutes=30))
        dt = datetime(2026, 6, 19, 15, 30, 0, tzinfo=IST)
        with patch("src.meta.datetime") as mock_dt:
            mock_dt.now.return_value = dt
            assert is_market_hours() is True


# ---------------------------------------------------------------------------
# detect_data_quality
# ---------------------------------------------------------------------------

class TestDetectDataQuality:
    def test_valid_data(self):
        data = {"last_price": 1500.0, "volume": 100000}
        assert detect_data_quality(data) == DQ_VALID

    def test_nan_detected(self):
        data = {"rsi": float("nan"), "ema": 100.0}
        assert detect_data_quality(data) == DQ_NAN

    def test_nan_nested(self):
        data = {"macd": {"value": float("nan"), "signal": 0.5}}
        assert detect_data_quality(data) == DQ_NAN

    def test_error_key_returns_invalid(self):
        data = {"error": "no data"}
        assert detect_data_quality(data) == DQ_INVALID

    def test_usd_ticker_price_under_1(self):
        data = {"last_price": 0.003, "volume": 100}
        assert detect_data_quality(data) == DQ_INVALID

    def test_stale_via_data_basis(self):
        data = {
            "close": 1500.0,
            "data_basis": {"staleness_days": 10},
        }
        assert detect_data_quality(data) == DQ_STALE

    def test_staleness_within_threshold(self):
        data = {
            "close": 1500.0,
            "data_basis": {"staleness_days": 3},
        }
        assert detect_data_quality(data) == DQ_VALID

    def test_list_data_valid(self):
        data = [{"close": 100.0}, {"close": 101.0}]
        assert detect_data_quality(data) == DQ_VALID

    def test_empty_dict(self):
        assert detect_data_quality({}) == DQ_VALID


# ---------------------------------------------------------------------------
# build_meta
# ---------------------------------------------------------------------------

class TestBuildMeta:
    def test_required_fields_present(self):
        m = build_meta()
        assert "type" in m
        assert "validation" in m
        assert "data_quality" in m
        assert "market_hours" in m
        assert "source" in m
        assert "account_type" in m
        assert "zerodha_connected" in m
        assert "as_of" in m
        assert "limitations" in m
        assert "deprecated_fields_present" in m
        assert "deprecation_note" in m
        assert "symbol_corrected" in m
        assert "symbol_original" in m
        assert "bootstrap_period" in m
        assert "warning" in m

    def test_default_type_is_fact(self):
        m = build_meta()
        assert m["type"] == TYPE_FACT

    def test_validation_subfields(self):
        m = build_meta()
        v = m["validation"]
        assert "status" in v
        assert "backtested" in v
        assert "production_validated" in v
        assert "research_status" in v

    def test_indicator_type(self):
        m = build_meta(type_=TYPE_INDICATOR, validation_status=VALIDATION_COMPUTED)
        assert m["type"] == TYPE_INDICATOR
        assert m["validation"]["status"] == VALIDATION_COMPUTED

    def test_deprecated_fields_populated(self):
        m = build_meta(
            deprecated_fields_present=["confidence"],
            deprecation_note="Test note",
        )
        assert "confidence" in m["deprecated_fields_present"]
        assert m["deprecation_note"] == "Test note"

    def test_symbol_correction_fields(self):
        m = build_meta(symbol_corrected=True, symbol_original="IDEA")
        assert m["symbol_corrected"] is True
        assert m["symbol_original"] == "IDEA"

    def test_as_of_is_iso_string(self):
        m = build_meta()
        assert "T" in m["as_of"]
        assert "Z" in m["as_of"]


# ---------------------------------------------------------------------------
# wrap
# ---------------------------------------------------------------------------

class TestWrap:
    def test_wrap_returns_data_and_meta(self):
        data = {"symbol": "INFY", "last_price": 1500.0}
        m = build_meta()
        result = wrap(data, m)
        assert "data" in result
        assert "meta" in result
        assert result["data"] == data
        assert result["meta"] == m

    def test_wrap_preserves_data_unchanged(self):
        data = {"a": 1, "b": [1, 2, 3], "c": None}
        result = wrap(data, build_meta())
        assert result["data"]["a"] == 1
        assert result["data"]["b"] == [1, 2, 3]
        assert result["data"]["c"] is None

    def test_wrap_with_list_data(self):
        data = [{"close": 100}, {"close": 101}]
        result = wrap(data, build_meta())
        assert result["data"] == data

    def test_no_extra_top_level_keys(self):
        result = wrap({}, build_meta())
        assert set(result.keys()) == {"data", "meta"}


# ---------------------------------------------------------------------------
# Convenience meta builders
# ---------------------------------------------------------------------------

class TestConvenienceBuilders:
    def test_market_meta_type_fact(self):
        m = market_meta({"last_price": 1500.0})
        assert m["type"] == TYPE_FACT
        assert m["source"] == "NSELive"

    def test_market_meta_usd_ticker(self):
        m = market_meta({"last_price": 0.002})
        assert m["data_quality"] == DQ_INVALID

    def test_indicator_meta_type(self):
        m = indicator_meta({"rsi_14": 65.0})
        assert m["type"] == TYPE_INDICATOR
        assert m["validation"]["status"] == VALIDATION_COMPUTED

    def test_indicator_meta_nan(self):
        m = indicator_meta({"rsi_14": float("nan")})
        assert m["data_quality"] == DQ_NAN

    def test_interpretation_meta_type(self):
        m = interpretation_meta()
        assert m["type"] == TYPE_INTERPRETATION
        assert m["validation"]["status"] == VALIDATION_UNVALIDATED
        assert m["validation"]["research_status"] == RS_EXPERIMENTAL

    def test_interpretation_meta_with_deprecated(self):
        m = interpretation_meta(deprecated_fields=["confidence"])
        assert "confidence" in m["deprecated_fields_present"]
        assert m["deprecation_note"] is not None

    def test_journal_meta_account_type(self):
        m = journal_meta()
        assert m["account_type"] == "PAPER_JOURNAL"
        assert m["source"] == "internal_journal"
        assert m["warning"] is not None
