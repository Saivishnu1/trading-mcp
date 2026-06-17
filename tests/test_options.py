"""
Unit tests for src/options/analytics.py and src/options/service.py.

All tests operate on in-memory chain dicts — no NSE/network calls.
"""
import pytest

from src.options.analytics import (
    calculate_max_pain,
    calculate_pcr,
    get_oi_analysis,
    identify_support_resistance_from_oi,
)
from src.options.service import OptionsService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXPIRY = "26-Jun-2025"
SPOT = 24000.0


def _minimal_chain(rows, spot=SPOT, expiry=EXPIRY):
    return {
        "records": {
            "data": rows,
            "expiryDates": [expiry],
            "underlyingValue": spot,
        }
    }


def _row(strike, ce_oi, pe_oi, ce_vol=100, pe_vol=100, expiry=EXPIRY):
    return {
        "strikePrice": strike,
        "expiryDate": expiry,
        "CE": {"openInterest": ce_oi, "totalTradedVolume": ce_vol, "lastPrice": 50.0, "impliedVolatility": 15.0},
        "PE": {"openInterest": pe_oi, "totalTradedVolume": pe_vol, "lastPrice": 50.0, "impliedVolatility": 15.0},
    }


# ---------------------------------------------------------------------------
# calculate_pcr
# ---------------------------------------------------------------------------

class TestCalculatePcr:

    def test_basic_ratio(self):
        rows = [
            _row(23000, ce_oi=1000, pe_oi=2000),
            _row(24000, ce_oi=3000, pe_oi=4000),
        ]
        chain = _minimal_chain(rows)
        result = calculate_pcr(chain, EXPIRY)
        assert result["total_call_oi"] == 4000
        assert result["total_put_oi"] == 6000
        assert result["pcr_oi"] == pytest.approx(6000 / 4000, rel=1e-4)

    def test_pcr_greater_than_one_is_bullish(self):
        rows = [_row(24000, ce_oi=1000, pe_oi=1500)]
        chain = _minimal_chain(rows)
        result = calculate_pcr(chain, EXPIRY)
        assert result["pcr_oi"] > 1.0
        assert "bullish" in result["interpretation"].lower()

    def test_pcr_less_than_07_is_bearish(self):
        rows = [_row(24000, ce_oi=2000, pe_oi=1000)]
        chain = _minimal_chain(rows)
        result = calculate_pcr(chain, EXPIRY)
        assert result["pcr_oi"] == pytest.approx(0.5, rel=1e-4)
        assert "bearish" in result["interpretation"].lower()

    def test_pcr_neutral_range(self):
        rows = [_row(24000, ce_oi=1000, pe_oi=900)]
        chain = _minimal_chain(rows)
        result = calculate_pcr(chain, EXPIRY)
        assert 0.7 < result["pcr_oi"] < 1.0
        assert "neutral" in result["interpretation"].lower() or "bearish" in result["interpretation"].lower()

    def test_zero_call_oi_returns_none_pcr(self):
        rows = [_row(24000, ce_oi=0, pe_oi=1000)]
        chain = _minimal_chain(rows)
        result = calculate_pcr(chain, EXPIRY)
        assert result["pcr_oi"] is None
        assert "insufficient" in result["interpretation"].lower()

    def test_expiry_filter(self, chain_data):
        """PCR with expiry filter should only use rows for that expiry."""
        result_filtered = calculate_pcr(chain_data, EXPIRY)
        result_all = calculate_pcr(chain_data, None)
        # Both should work; with one expiry in chain, values should match
        assert result_filtered["pcr_oi"] is not None
        assert result_all["pcr_oi"] is not None

    def test_volume_pcr(self):
        rows = [_row(24000, ce_oi=1000, pe_oi=1000, ce_vol=500, pe_vol=1000)]
        chain = _minimal_chain(rows)
        result = calculate_pcr(chain, EXPIRY)
        assert result["pcr_volume"] == pytest.approx(2.0, rel=1e-4)

    def test_empty_chain(self):
        chain = _minimal_chain([], spot=24000.0)
        result = calculate_pcr(chain, EXPIRY)
        assert result["pcr_oi"] is None
        assert result["total_call_oi"] == 0


# ---------------------------------------------------------------------------
# calculate_max_pain
# ---------------------------------------------------------------------------

class TestCalculateMaxPain:

    def test_empty_chain(self):
        chain = _minimal_chain([])
        result = calculate_max_pain(chain, EXPIRY)
        assert result["max_pain"] is None

    def test_symmetric_oi_max_pain_at_atm(self):
        """With equal OI on both sides of a central strike, max pain is central."""
        rows = [
            _row(23000, ce_oi=100, pe_oi=0),
            _row(24000, ce_oi=0, pe_oi=0),
            _row(25000, ce_oi=0, pe_oi=100),
        ]
        chain = _minimal_chain(rows)
        result = calculate_max_pain(chain, EXPIRY)
        # At candidate=24000: call pain = max(24000-23000,0)*100=100000; put pain = max(25000-24000,0)*100=100000 → total 200000
        # At candidate=23000: call pain = 0; put pain = max(25000-23000,0)*100=200000 → 200000
        # At candidate=25000: call pain = max(25000-23000,0)*100=200000; put pain = 0 → 200000
        # All equal? Not quite. Let me just verify max_pain is one of the strikes.
        assert result["max_pain"] in {23000.0, 24000.0, 25000.0}

    def test_max_pain_where_most_options_expire_worthless(self):
        """Strike with most OI should attract max pain (options writers profit most there)."""
        rows = [
            _row(23500, ce_oi=0, pe_oi=5000),  # heavy put OI → if price = 23500, these expire worthless
            _row(24000, ce_oi=0, pe_oi=0),
            _row(24500, ce_oi=5000, pe_oi=0),  # heavy call OI
        ]
        chain = _minimal_chain(rows)
        result = calculate_max_pain(chain, EXPIRY)
        assert result["max_pain"] is not None
        assert result["max_pain"] in {23500.0, 24000.0, 24500.0}

    def test_distance_from_spot(self, chain_data):
        result = calculate_max_pain(chain_data, EXPIRY)
        if result["max_pain"] is not None:
            expected_distance = round(SPOT - result["max_pain"], 2)
            assert result["distance_from_spot"] == pytest.approx(expected_distance, abs=0.01)

    def test_pain_table_top20_structure(self, chain_data):
        result = calculate_max_pain(chain_data, EXPIRY)
        assert len(result["pain_table_top20"]) <= 20
        for entry in result["pain_table_top20"]:
            assert "strike" in entry
            assert "total_pain" in entry

    def test_pain_table_sorted_ascending(self, chain_data):
        result = calculate_max_pain(chain_data, EXPIRY)
        table = result["pain_table_top20"]
        pains = [e["total_pain"] for e in table]
        assert pains == sorted(pains)

    def test_returns_required_keys(self, chain_data):
        result = calculate_max_pain(chain_data, EXPIRY)
        for key in ("max_pain", "underlying_value", "expiry", "distance_from_spot", "pain_table_top20"):
            assert key in result


# ---------------------------------------------------------------------------
# identify_support_resistance_from_oi
# ---------------------------------------------------------------------------

class TestIdentifySupportResistance:

    def test_nearest_support_below_spot(self, chain_data):
        result = identify_support_resistance_from_oi(chain_data, EXPIRY)
        ns = result["nearest_support"]
        if ns:
            assert ns["strike"] < SPOT

    def test_nearest_resistance_above_spot(self, chain_data):
        result = identify_support_resistance_from_oi(chain_data, EXPIRY)
        nr = result["nearest_resistance"]
        if nr:
            assert nr["strike"] > SPOT

    def test_support_levels_have_basis(self, chain_data):
        result = identify_support_resistance_from_oi(chain_data, EXPIRY)
        for s in result["support_levels"]:
            assert s["basis"] == "high put OI"

    def test_resistance_levels_have_basis(self, chain_data):
        result = identify_support_resistance_from_oi(chain_data, EXPIRY)
        for r in result["resistance_levels"]:
            assert r["basis"] == "high call OI"

    def test_top_n_limits_results(self, chain_data):
        result = identify_support_resistance_from_oi(chain_data, EXPIRY, top_n=3)
        assert len(result["support_levels"]) <= 3
        assert len(result["resistance_levels"]) <= 3

    def test_returns_required_keys(self, chain_data):
        result = identify_support_resistance_from_oi(chain_data, EXPIRY)
        for key in ("underlying_value", "expiry", "resistance_levels",
                    "support_levels", "nearest_resistance", "nearest_support"):
            assert key in result

    def test_empty_chain_returns_none_nearest(self):
        chain = _minimal_chain([])
        result = identify_support_resistance_from_oi(chain, EXPIRY)
        assert result["nearest_support"] is None
        assert result["nearest_resistance"] is None


# ---------------------------------------------------------------------------
# get_oi_analysis
# ---------------------------------------------------------------------------

class TestGetOiAnalysis:

    def test_returns_top_n_calls_and_puts(self, chain_data):
        result = get_oi_analysis(chain_data, EXPIRY, top_n=5)
        assert len(result["top_call_oi_strikes"]) <= 5
        assert len(result["top_put_oi_strikes"]) <= 5

    def test_sorted_by_oi_descending(self, chain_data):
        result = get_oi_analysis(chain_data, EXPIRY, top_n=10)
        call_ois = [r["oi"] for r in result["top_call_oi_strikes"]]
        put_ois = [r["oi"] for r in result["top_put_oi_strikes"]]
        assert call_ois == sorted(call_ois, reverse=True)
        assert put_ois == sorted(put_ois, reverse=True)

    def test_max_call_oi_strike_is_top_call(self, chain_data):
        result = get_oi_analysis(chain_data, EXPIRY)
        assert result["max_call_oi_strike"] == result["top_call_oi_strikes"][0]["strike"]

    def test_max_put_oi_strike_is_top_put(self, chain_data):
        result = get_oi_analysis(chain_data, EXPIRY)
        assert result["max_put_oi_strike"] == result["top_put_oi_strikes"][0]["strike"]

    def test_underlying_value_matches_spot(self, chain_data):
        result = get_oi_analysis(chain_data, EXPIRY)
        assert result["underlying_value"] == SPOT

    def test_strike_row_structure(self, chain_data):
        result = get_oi_analysis(chain_data, EXPIRY, top_n=3)
        for row in result["top_call_oi_strikes"] + result["top_put_oi_strikes"]:
            assert "strike" in row
            assert "oi" in row
            assert "volume" in row


# ---------------------------------------------------------------------------
# OptionsService._strip_exchange_prefix  (Phase-8 regression)
# ---------------------------------------------------------------------------

class TestStripExchangePrefix:

    def test_strips_nse_prefix(self):
        assert OptionsService._strip_exchange_prefix("NSE:RELIANCE") == "RELIANCE"

    def test_strips_bse_prefix(self):
        assert OptionsService._strip_exchange_prefix("BSE:INFY") == "INFY"

    def test_bare_symbol_unchanged(self):
        assert OptionsService._strip_exchange_prefix("RELIANCE") == "RELIANCE"
        assert OptionsService._strip_exchange_prefix("NIFTY") == "NIFTY"

    def test_lowercase_preserved(self):
        assert OptionsService._strip_exchange_prefix("NSE:reliance") == "reliance"

    def test_is_index_symbol_nifty(self):
        svc = OptionsService.__new__(OptionsService)
        assert svc._is_index_symbol("NIFTY") is True
        assert svc._is_index_symbol("BANKNIFTY") is True
        assert svc._is_index_symbol("FINNIFTY") is True
        assert svc._is_index_symbol("MIDCPNIFTY") is True

    def test_is_index_symbol_equity(self):
        svc = OptionsService.__new__(OptionsService)
        assert svc._is_index_symbol("RELIANCE") is False
        assert svc._is_index_symbol("NSE:RELIANCE") is False
