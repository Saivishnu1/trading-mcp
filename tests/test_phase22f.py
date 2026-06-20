"""
Phase 22F tests — field deletion, market_structure conversion, schema_version 5.

All tests use the _CapturingMCP pattern to drive the tool layer (not the service
layer), so results are always {"data": ..., "meta": ...}.

The patch_analyze fixture (conftest.py) injects deterministic technicals without
live yfinance calls.  BULL_TREND_TECH is the default fixture snapshot.
"""
import inspect

import pytest

from tests.conftest import (
    BULL_TREND_TECH,
    RANGE_BOUND_TECH,
    NEUTRAL_BULLISH_TECH,
    NEUTRAL_BEARISH_TECH,
    BEAR_TREND_TECH,
)


# ---------------------------------------------------------------------------
# _CapturingMCP helper (mirrors pattern in test_technicals.py)
# ---------------------------------------------------------------------------

class _CapturingMCP:
    def __init__(self):
        self.tools: dict = {}

    def tool(self, *args, **kwargs):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


def _get_tools():
    import src.tools.analysis as mod
    cap = _CapturingMCP()
    mod.register(cap)
    return cap.tools


# ---------------------------------------------------------------------------
# Deletion tests — confidence / signal / trade_quality must be absent
# ---------------------------------------------------------------------------

class TestFieldDeletion:
    def test_confidence_deleted_from_generate_trade_setup(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        result = tools["generate_trade_setup"]("NIFTY")
        assert "confidence" not in result["data"]

    def test_signal_deleted_from_generate_trade_setup(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        result = tools["generate_trade_setup"]("NIFTY")
        assert "signal" not in result["data"]

    def test_trade_quality_deleted_from_generate_trade_setup(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        result = tools["generate_trade_setup"]("NIFTY")
        assert "trade_quality" not in result["data"]

    def test_regime_deleted_from_detect_market_regime(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        result = tools["detect_market_regime"]("NIFTY")
        assert "regime" not in result["data"]

    def test_confidence_deleted_from_detect_market_regime(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        result = tools["detect_market_regime"]("NIFTY")
        assert "confidence" not in result["data"]

    def test_quality_deleted_from_generate_trade_setup(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        result = tools["generate_trade_setup"]("NIFTY")
        assert "quality" not in result["data"]

    def test_bullish_probability_deleted_from_generate_trade_setup(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        result = tools["generate_trade_setup"]("NIFTY")
        assert "bullish_probability" not in result["data"]


# ---------------------------------------------------------------------------
# market_structure presence and structure
# ---------------------------------------------------------------------------

class TestMarketStructurePresent:
    def test_market_structure_key_present(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        result = tools["detect_market_regime"]("NIFTY")
        assert "market_structure" in result["data"]

    def test_numeric_fields_present(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        result = tools["detect_market_regime"]("NIFTY")
        ms = result["data"]["market_structure"]
        for field in ["price", "ema20", "ema50", "adx", "rsi"]:
            assert field in ms

    def test_numeric_values_match_technicals(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        result = tools["detect_market_regime"]("NIFTY")
        ms = result["data"]["market_structure"]
        assert ms["price"] == pytest.approx(101.0)
        assert ms["ema20"] == pytest.approx(100.0)
        assert ms["ema50"] == pytest.approx(90.0)
        assert ms["adx"] == pytest.approx(30.0)
        assert ms["rsi"] == pytest.approx(65.0)


# ---------------------------------------------------------------------------
# Boolean fields — typed and correct
# ---------------------------------------------------------------------------

class TestBooleanFields:
    def test_boolean_fields_present(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        ms = tools["detect_market_regime"]("NIFTY")["data"]["market_structure"]
        for field in ["price_above_ema20", "ema20_above_ema50", "adx_above_25", "rsi_above_60"]:
            assert field in ms

    def test_boolean_fields_typed(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        ms = tools["detect_market_regime"]("NIFTY")["data"]["market_structure"]
        for field in ["price_above_ema20", "ema20_above_ema50", "adx_above_25", "rsi_above_60"]:
            assert isinstance(ms[field], bool)

    def test_bull_trend_booleans_all_true(self, patch_analyze):
        # BULL_TREND_TECH: price=101 > ema20=100, ema20=100 > ema50=90, adx=30>25, rsi=65>60
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        ms = tools["detect_market_regime"]("NIFTY")["data"]["market_structure"]
        assert ms["price_above_ema20"] is True
        assert ms["ema20_above_ema50"] is True
        assert ms["adx_above_25"] is True
        assert ms["rsi_above_60"] is True

    def test_range_bound_adx_false(self, patch_analyze):
        # RANGE_BOUND_TECH: adx=15 → adx_above_25=False; rsi=50 → rsi_above_60=False
        patch_analyze(RANGE_BOUND_TECH)
        tools = _get_tools()
        ms = tools["detect_market_regime"]("NIFTY")["data"]["market_structure"]
        assert ms["adx_above_25"] is False
        assert ms["rsi_above_60"] is False

    def test_bear_trend_booleans(self, patch_analyze):
        # BEAR_TREND_TECH: price=89 < ema20=90 → False; ema20=90 < ema50=100 → False
        patch_analyze(BEAR_TREND_TECH)
        tools = _get_tools()
        ms = tools["detect_market_regime"]("NIFTY")["data"]["market_structure"]
        assert ms["price_above_ema20"] is False
        assert ms["ema20_above_ema50"] is False
        assert ms["adx_above_25"] is True   # adx=28>25
        assert ms["rsi_above_60"] is False  # rsi=35<60


# ---------------------------------------------------------------------------
# Descriptor — auto-generated, mirrors booleans
# ---------------------------------------------------------------------------

class TestDescriptor:
    def test_descriptor_is_list(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        ms = tools["detect_market_regime"]("NIFTY")["data"]["market_structure"]
        assert isinstance(ms["descriptor"], list)

    def test_descriptor_all_four_when_bull(self, patch_analyze):
        # All four booleans True → all four in descriptor
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        ms = tools["detect_market_regime"]("NIFTY")["data"]["market_structure"]
        assert ms["descriptor"] == [
            "price_above_ema20", "ema20_above_ema50", "adx_above_25", "rsi_above_60"
        ]

    def test_descriptor_matches_booleans_positive(self, patch_analyze):
        patch_analyze(RANGE_BOUND_TECH)
        tools = _get_tools()
        ms = tools["detect_market_regime"]("NIFTY")["data"]["market_structure"]
        if ms["price_above_ema20"]:
            assert "price_above_ema20" in ms["descriptor"]
        if ms["ema20_above_ema50"]:
            assert "ema20_above_ema50" in ms["descriptor"]
        if ms["adx_above_25"]:
            assert "adx_above_25" in ms["descriptor"]
        if ms["rsi_above_60"]:
            assert "rsi_above_60" in ms["descriptor"]

    def test_descriptor_matches_booleans_inverse(self, patch_analyze):
        patch_analyze(RANGE_BOUND_TECH)
        tools = _get_tools()
        ms = tools["detect_market_regime"]("NIFTY")["data"]["market_structure"]
        if not ms["price_above_ema20"]:
            assert "price_above_ema20" not in ms["descriptor"]
        if not ms["ema20_above_ema50"]:
            assert "ema20_above_ema50" not in ms["descriptor"]
        if not ms["adx_above_25"]:
            assert "adx_above_25" not in ms["descriptor"]
        if not ms["rsi_above_60"]:
            assert "rsi_above_60" not in ms["descriptor"]

    def test_descriptor_bear_trend_excludes_false_booleans(self, patch_analyze):
        patch_analyze(BEAR_TREND_TECH)
        tools = _get_tools()
        ms = tools["detect_market_regime"]("NIFTY")["data"]["market_structure"]
        assert "price_above_ema20" not in ms["descriptor"]
        assert "ema20_above_ema50" not in ms["descriptor"]
        assert "adx_above_25" in ms["descriptor"]
        assert "rsi_above_60" not in ms["descriptor"]

    def test_descriptor_facts_only_no_forbidden_words(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        ms = tools["detect_market_regime"]("NIFTY")["data"]["market_structure"]
        forbidden = ["bullish", "bearish", "buy", "sell", "high_quality", "high_conviction"]
        for item in ms["descriptor"]:
            for word in forbidden:
                assert word not in item.lower()


# ---------------------------------------------------------------------------
# indicator_interpretation — type and validation_status always set
# ---------------------------------------------------------------------------

class TestIndicatorInterpretation:
    def test_indicator_interpretation_present(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        ms = tools["detect_market_regime"]("NIFTY")["data"]["market_structure"]
        assert "indicator_interpretation" in ms

    def test_indicator_interpretation_typed(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        ii = tools["detect_market_regime"]("NIFTY")["data"]["market_structure"]["indicator_interpretation"]
        assert ii["type"] == "INTERPRETATION"
        assert ii["validation_status"] == "UNVALIDATED"

    def test_adx_note_valid_values(self, patch_analyze):
        valid = {"trend_absent", "trend_weak", "trend_present", "strong_trend_present"}
        for tech in [BULL_TREND_TECH, BEAR_TREND_TECH, RANGE_BOUND_TECH]:
            patch_analyze(tech)
            tools = _get_tools()
            ii = tools["detect_market_regime"]("NIFTY")["data"]["market_structure"]["indicator_interpretation"]
            assert ii["adx_note"] in valid

    def test_rsi_note_valid_values(self, patch_analyze):
        valid = {"oversold", "momentum_low", "momentum_neutral", "momentum_elevated", "overbought"}
        for tech in [BULL_TREND_TECH, BEAR_TREND_TECH, RANGE_BOUND_TECH]:
            patch_analyze(tech)
            tools = _get_tools()
            ii = tools["detect_market_regime"]("NIFTY")["data"]["market_structure"]["indicator_interpretation"]
            assert ii["rsi_note"] in valid

    def test_adx_note_trend_present_at_30(self, patch_analyze):
        # BULL_TREND_TECH: adx=30 → 25<=30<35 → "trend_present"
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        ii = tools["detect_market_regime"]("NIFTY")["data"]["market_structure"]["indicator_interpretation"]
        assert ii["adx_note"] == "trend_present"

    def test_adx_note_trend_weak_at_15(self, patch_analyze):
        # RANGE_BOUND_TECH: adx=15 → 15<25 → "trend_weak" (15 is not < 15)
        patch_analyze(RANGE_BOUND_TECH)
        tools = _get_tools()
        ii = tools["detect_market_regime"]("NIFTY")["data"]["market_structure"]["indicator_interpretation"]
        assert ii["adx_note"] == "trend_weak"

    def test_rsi_note_momentum_elevated_at_65(self, patch_analyze):
        # BULL_TREND_TECH: rsi=65 → 60<=65<70 → "momentum_elevated"
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        ii = tools["detect_market_regime"]("NIFTY")["data"]["market_structure"]["indicator_interpretation"]
        assert ii["rsi_note"] == "momentum_elevated"

    def test_rsi_note_momentum_low_at_35(self, patch_analyze):
        # BEAR_TREND_TECH: rsi=35 → 30<=35<45 → "momentum_low"
        patch_analyze(BEAR_TREND_TECH)
        tools = _get_tools()
        ii = tools["detect_market_regime"]("NIFTY")["data"]["market_structure"]["indicator_interpretation"]
        assert ii["rsi_note"] == "momentum_low"


# ---------------------------------------------------------------------------
# _migration block — temporary, present in both tools
# ---------------------------------------------------------------------------

class TestMigrationBlock:
    def test_migration_in_detect_market_regime(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        data = tools["detect_market_regime"]("NIFTY")["data"]
        m = data["_migration"]
        assert m["regime_removed"] is True
        assert m["replacement"] == "market_structure"
        assert m["schema_version"] == 5

    def test_migration_in_generate_trade_setup(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        data = tools["generate_trade_setup"]("NIFTY")["data"]
        m = data["_migration"]
        assert m["regime_removed"] is True
        assert m["replacement"] == "market_structure"
        assert m["schema_version"] == 5


# ---------------------------------------------------------------------------
# schema_version: 5 in meta
# ---------------------------------------------------------------------------

class TestSchemaVersion:
    def test_schema_version_in_detect_market_regime_meta(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        result = tools["detect_market_regime"]("NIFTY")
        assert result["meta"]["schema_version"] == 5

    def test_schema_version_in_generate_trade_setup_meta(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        result = tools["generate_trade_setup"]("NIFTY")
        assert result["meta"]["schema_version"] == 5


# ---------------------------------------------------------------------------
# Forbidden words — nowhere in generate_trade_setup data output
# ---------------------------------------------------------------------------

class TestForbiddenWords:
    FORBIDDEN = [
        "high_quality", "high_conviction",
        "strong_buy", "strong_sell",
        "HIGH_QUALITY", "NEUTRAL_BULLISH",
        "NEUTRAL_BEARISH", "MODERATE_QUALITY",
    ]

    def test_no_forbidden_words_bull_setup(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        output = str(tools["generate_trade_setup"]("NIFTY")["data"])
        for word in self.FORBIDDEN:
            assert word not in output, f"Forbidden word '{word}' found in output"

    def test_no_forbidden_words_neutral_bullish_setup(self, patch_analyze):
        patch_analyze(NEUTRAL_BULLISH_TECH)
        tools = _get_tools()
        output = str(tools["generate_trade_setup"]("NIFTY")["data"])
        for word in self.FORBIDDEN:
            assert word not in output, f"Forbidden word '{word}' found in output"

    def test_no_forbidden_words_neutral_bearish_setup(self, patch_analyze):
        patch_analyze(NEUTRAL_BEARISH_TECH)
        tools = _get_tools()
        output = str(tools["generate_trade_setup"]("NIFTY")["data"])
        for word in self.FORBIDDEN:
            assert word not in output, f"Forbidden word '{word}' found in output"

    def test_no_forbidden_words_detect_regime(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        output = str(tools["detect_market_regime"]("NIFTY")["data"])
        for word in self.FORBIDDEN:
            assert word not in output, f"Forbidden word '{word}' found in output"


# ---------------------------------------------------------------------------
# deprecated_fields_present returns [] since fields are deleted
# ---------------------------------------------------------------------------

class TestDeprecatedFieldsEmpty:
    def test_deprecated_fields_empty_generate_trade_setup(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        result = tools["generate_trade_setup"]("NIFTY")
        assert result["meta"]["deprecated_fields_present"] == []

    def test_deprecated_fields_empty_detect_market_regime(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        result = tools["detect_market_regime"]("NIFTY")
        assert result["meta"]["deprecated_fields_present"] == []


# ---------------------------------------------------------------------------
# Docstring tests — Phase 20A / 21 findings embedded in tool docstrings
# ---------------------------------------------------------------------------

class TestDocstrings:
    def test_generate_trade_setup_docstring_has_phase20a(self):
        tools = _get_tools()
        doc = inspect.getdoc(tools["generate_trade_setup"])
        assert "Phase 20A" in doc

    def test_generate_trade_setup_docstring_has_phase21(self):
        tools = _get_tools()
        doc = inspect.getdoc(tools["generate_trade_setup"])
        assert "Phase 21" in doc

    def test_detect_market_regime_docstring_has_phase20a(self):
        tools = _get_tools()
        doc = inspect.getdoc(tools["detect_market_regime"])
        assert "Phase 20A" in doc

    def test_detect_market_regime_docstring_has_unvalidated(self):
        tools = _get_tools()
        doc = inspect.getdoc(tools["detect_market_regime"])
        assert "UNVALIDATED" in doc


# ---------------------------------------------------------------------------
# Regression — kept fields must remain untouched
# ---------------------------------------------------------------------------

class TestRegressionKeptFields:
    def test_entry_stoploss_target_present(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        data = tools["generate_trade_setup"]("NIFTY")["data"]
        for field in ["entry", "stoploss", "target"]:
            assert field in data

    def test_zone_fields_present(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        data = tools["generate_trade_setup"]("NIFTY")["data"]
        for field in ["entry_above", "entry_below", "bull_target", "bear_target"]:
            assert field in data

    def test_reasoning_present_and_list(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        data = tools["generate_trade_setup"]("NIFTY")["data"]
        assert "reasoning" in data
        assert isinstance(data["reasoning"], list)

    def test_symbol_present_in_detect_regime(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        data = tools["detect_market_regime"]("NIFTY")["data"]
        assert "symbol" in data

    def test_meta_wrapper_fields_present(self, patch_analyze):
        patch_analyze(BULL_TREND_TECH)
        tools = _get_tools()
        result = tools["generate_trade_setup"]("NIFTY")
        for field in ["type", "data_quality", "as_of", "validation", "schema_version"]:
            assert field in result["meta"]
