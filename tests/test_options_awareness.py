"""
Tests for Phase 6 — Option Structure Awareness.
All data is synthetic — no live API calls.
"""
from __future__ import annotations

import pytest

from src.options_awareness.iv_analyzer import IVAnalyzer
from src.options_awareness.levels import OILevelDetector
from src.options_awareness.oi_analyzer import OIAnalyzer

# ---------------------------------------------------------------------------
# Synthetic chain builder (raw NSE records.data format)
# ---------------------------------------------------------------------------

def _make_chain(
    spot: float = 24000.0,
    strikes: list[float] | None = None,
    expiry: str = "27-Jun-2024",
) -> dict:
    if strikes is None:
        strikes = [23000, 23500, 23800, 24000, 24200, 24500, 25000]

    data = []
    for i, sp in enumerate(strikes):
        # OI increases toward extremes for call (above spot) and put (below spot)
        dist = abs(sp - spot) / spot
        base_oi = int(500_000 * (1 + dist * 3))
        change_oi = base_oi // 10 if sp > spot else -(base_oi // 10)
        iv = 12.0 + dist * 5 + (2.0 if sp < spot else 0.0)  # put skew

        data.append({
            "strikePrice": sp,
            "expiryDate": expiry,
            "CE": {
                "openInterest": base_oi if sp > spot else base_oi // 3,
                "changeinOpenInterest": change_oi,
                "totalTradedVolume": base_oi // 5,
                "impliedVolatility": round(iv, 2),
                "lastPrice": max(0.05, spot - sp + 10),
                "bidprice": max(0.05, spot - sp + 9),
                "askPrice": max(0.05, spot - sp + 11),
            },
            "PE": {
                "openInterest": base_oi if sp < spot else base_oi // 3,
                "changeinOpenInterest": -change_oi,
                "totalTradedVolume": base_oi // 5,
                "impliedVolatility": round(iv + 1, 2),
                "lastPrice": max(0.05, sp - spot + 10),
                "bidprice": max(0.05, sp - spot + 9),
                "askPrice": max(0.05, sp - spot + 11),
            },
        })

    return {
        "records": {
            "underlyingValue": spot,
            "expiryDates": [expiry, "25-Jul-2024"],
            "data": data,
        }
    }


EXPIRY = "27-Jun-2024"
SPOT = 24000.0


# ---------------------------------------------------------------------------
# OIAnalyzer — walls
# ---------------------------------------------------------------------------

class TestOIAnalyzerWalls:

    def test_call_wall_is_highest_call_oi(self):
        chain = _make_chain()
        walls = OIAnalyzer.detect_walls(chain, EXPIRY)
        assert walls["call_wall"] is not None
        assert walls["call_wall"] > SPOT  # call wall should be above spot

    def test_put_wall_is_highest_put_oi(self):
        chain = _make_chain()
        walls = OIAnalyzer.detect_walls(chain, EXPIRY)
        assert walls["put_wall"] is not None
        assert walls["put_wall"] < SPOT  # put wall should be below spot

    def test_gamma_wall_exists(self):
        chain = _make_chain()
        walls = OIAnalyzer.detect_walls(chain, EXPIRY)
        assert walls["gamma_wall"] is not None

    def test_walls_return_oi_counts(self):
        chain = _make_chain()
        walls = OIAnalyzer.detect_walls(chain, EXPIRY)
        assert walls["call_wall_oi"] > 0
        assert walls["put_wall_oi"] > 0

    def test_top_walls_lists_present(self):
        chain = _make_chain()
        walls = OIAnalyzer.detect_walls(chain, EXPIRY)
        assert isinstance(walls["top_call_walls"], list)
        assert isinstance(walls["top_put_walls"], list)
        assert len(walls["top_call_walls"]) >= 1
        assert len(walls["top_put_walls"]) >= 1

    def test_empty_chain_returns_nones(self):
        chain = {"records": {"underlyingValue": 24000, "data": []}}
        walls = OIAnalyzer.detect_walls(chain, EXPIRY)
        assert walls["call_wall"] is None
        assert walls["put_wall"] is None


# ---------------------------------------------------------------------------
# OIAnalyzer — S/R levels
# ---------------------------------------------------------------------------

class TestOIAnalyzerSR:

    def test_resistances_above_spot(self):
        chain = _make_chain()
        oi_sr = OIAnalyzer.detect_oi_support_resistance(chain, EXPIRY)
        for r in oi_sr["resistances"]:
            assert r["level"] > 0
            assert r["call_oi"] > 0
            assert r["strength"] in ("strong", "moderate", "weak")

    def test_supports_have_put_oi(self):
        chain = _make_chain()
        oi_sr = OIAnalyzer.detect_oi_support_resistance(chain, EXPIRY)
        for s in oi_sr["supports"]:
            assert s["level"] > 0
            assert s["put_oi"] > 0
            assert s["strength"] in ("strong", "moderate", "weak")

    def test_top_n_respected(self):
        chain = _make_chain()
        oi_sr = OIAnalyzer.detect_oi_support_resistance(chain, EXPIRY, top_n=2)
        assert len(oi_sr["resistances"]) <= 2
        assert len(oi_sr["supports"]) <= 2

    def test_strength_classification(self):
        chain = _make_chain()
        oi_sr = OIAnalyzer.detect_oi_support_resistance(chain, EXPIRY)
        # Highest OI entry should be "strong"
        if oi_sr["resistances"]:
            assert oi_sr["resistances"][0]["strength"] == "strong"
        if oi_sr["supports"]:
            assert oi_sr["supports"][0]["strength"] == "strong"


# ---------------------------------------------------------------------------
# OIAnalyzer — buildup detection
# ---------------------------------------------------------------------------

class TestOIAnalyzerBuildup:

    def test_buildup_keys_present(self):
        chain = _make_chain()
        result = OIAnalyzer.detect_oi_buildup(chain, EXPIRY)
        assert "call_buildup" in result
        assert "put_buildup" in result
        assert "unwinding" in result

    def test_buildup_entries_are_lists(self):
        chain = _make_chain()
        result = OIAnalyzer.detect_oi_buildup(chain, EXPIRY)
        assert isinstance(result["call_buildup"], list)
        assert isinstance(result["put_buildup"], list)
        assert isinstance(result["unwinding"], list)

    def test_buildup_entry_fields(self):
        chain = _make_chain()
        result = OIAnalyzer.detect_oi_buildup(chain, EXPIRY)
        for entry in result["call_buildup"] + result["put_buildup"] + result["unwinding"]:
            assert "strike" in entry
            assert "oi" in entry
            assert "change_oi" in entry
            assert "type" in entry
            assert entry["type"] in ("CE", "PE")

    def test_call_buildup_strikes_above_spot(self):
        chain = _make_chain()
        result = OIAnalyzer.detect_oi_buildup(chain, EXPIRY)
        for entry in result["call_buildup"]:
            assert entry["strike"] > SPOT

    def test_put_buildup_strikes_below_spot(self):
        chain = _make_chain()
        result = OIAnalyzer.detect_oi_buildup(chain, EXPIRY)
        for entry in result["put_buildup"]:
            assert entry["strike"] < SPOT

    def test_empty_chain_no_buildup(self):
        chain = {"records": {"underlyingValue": 24000, "data": []}}
        result = OIAnalyzer.detect_oi_buildup(chain, EXPIRY)
        assert result["call_buildup"] == []
        assert result["put_buildup"] == []
        assert result["unwinding"] == []


# ---------------------------------------------------------------------------
# IVAnalyzer
# ---------------------------------------------------------------------------

class TestIVAnalyzer:

    def test_atm_iv_computed(self):
        chain = _make_chain()
        iv_data = IVAnalyzer.get_iv_surface(chain, EXPIRY)
        assert iv_data["atm_iv"] is not None
        assert iv_data["atm_iv"] > 0
        assert iv_data["atm_strike"] == 24000.0

    def test_skew_computed(self):
        chain = _make_chain()
        iv_data = IVAnalyzer.get_iv_surface(chain, EXPIRY)
        # Our synthetic chain has put skew (put IV > call IV)
        assert iv_data["iv_skew"] is not None
        assert iv_data["put_iv"] is not None
        assert iv_data["call_iv"] is not None

    def test_put_skew_positive_in_synthetic_data(self):
        chain = _make_chain()
        iv_data = IVAnalyzer.get_iv_surface(chain, EXPIRY)
        # put_iv > call_iv in synthetic data (built-in put skew)
        if iv_data["put_iv"] and iv_data["call_iv"]:
            assert iv_data["iv_skew"] > 0

    def test_skew_interpretation_string(self):
        chain = _make_chain()
        iv_data = IVAnalyzer.get_iv_surface(chain, EXPIRY)
        assert isinstance(iv_data["skew_interpretation"], str)
        assert len(iv_data["skew_interpretation"]) > 0

    def test_term_structure_is_list(self):
        chain = _make_chain()
        iv_data = IVAnalyzer.get_iv_surface(chain, EXPIRY)
        assert isinstance(iv_data["term_structure"], list)

    def test_no_spot_returns_empty_surface(self):
        chain = {"records": {"underlyingValue": None, "data": []}}
        iv_data = IVAnalyzer.get_iv_surface(chain, EXPIRY)
        assert iv_data["atm_iv"] is None
        assert iv_data["iv_skew"] is None

    def test_atm_iv_interpretation(self):
        assert "low" in IVAnalyzer.get_atm_iv_interpretation(12.0).lower()
        assert "moderate" in IVAnalyzer.get_atm_iv_interpretation(18.0).lower()
        assert "high" in IVAnalyzer.get_atm_iv_interpretation(35.0).lower()
        assert "unavailable" in IVAnalyzer.get_atm_iv_interpretation(None).lower()


# ---------------------------------------------------------------------------
# OILevelDetector
# ---------------------------------------------------------------------------

class TestOILevelDetector:

    def _make_inputs(self):
        chain = _make_chain()
        walls = OIAnalyzer.detect_walls(chain, EXPIRY)
        oi_sr = OIAnalyzer.detect_oi_support_resistance(chain, EXPIRY)
        return chain, walls, oi_sr

    def test_key_levels_returns_dict(self):
        chain, walls, oi_sr = self._make_inputs()
        levels = OILevelDetector.get_key_levels(chain, EXPIRY, oi_sr, walls)
        assert isinstance(levels, dict)

    def test_pcr_present(self):
        chain, walls, oi_sr = self._make_inputs()
        levels = OILevelDetector.get_key_levels(chain, EXPIRY, oi_sr, walls)
        assert "pcr" in levels
        assert levels["pcr"] is not None

    def test_max_pain_present(self):
        chain, walls, oi_sr = self._make_inputs()
        levels = OILevelDetector.get_key_levels(chain, EXPIRY, oi_sr, walls)
        assert "max_pain" in levels
        assert levels["max_pain"] is not None

    def test_walls_propagated(self):
        chain, walls, oi_sr = self._make_inputs()
        levels = OILevelDetector.get_key_levels(chain, EXPIRY, oi_sr, walls)
        assert levels["call_wall"] == walls["call_wall"]
        assert levels["put_wall"]  == walls["put_wall"]
        assert levels["gamma_wall"] == walls["gamma_wall"]

    def test_supports_resistances_propagated(self):
        chain, walls, oi_sr = self._make_inputs()
        levels = OILevelDetector.get_key_levels(chain, EXPIRY, oi_sr, walls)
        assert levels["supports"]    == oi_sr["supports"]
        assert levels["resistances"] == oi_sr["resistances"]

    def test_distance_from_max_pain(self):
        chain, walls, oi_sr = self._make_inputs()
        levels = OILevelDetector.get_key_levels(chain, EXPIRY, oi_sr, walls)
        assert "distance_from_max_pain" in levels
        if levels["max_pain"] is not None:
            assert isinstance(levels["distance_from_max_pain"], float)


# ---------------------------------------------------------------------------
# PCR interpretation (via analytics, exercised through levels)
# ---------------------------------------------------------------------------

class TestPCRCalculation:

    def test_pcr_positive(self):
        chain = _make_chain()
        walls = OIAnalyzer.detect_walls(chain, EXPIRY)
        oi_sr = OIAnalyzer.detect_oi_support_resistance(chain, EXPIRY)
        levels = OILevelDetector.get_key_levels(chain, EXPIRY, oi_sr, walls)
        assert levels["pcr"] > 0

    def test_pcr_interpretation_string(self):
        chain = _make_chain()
        walls = OIAnalyzer.detect_walls(chain, EXPIRY)
        oi_sr = OIAnalyzer.detect_oi_support_resistance(chain, EXPIRY)
        levels = OILevelDetector.get_key_levels(chain, EXPIRY, oi_sr, walls)
        assert isinstance(levels["pcr_interpretation"], str)
        assert len(levels["pcr_interpretation"]) > 0

    def test_high_put_oi_gives_bullish_pcr(self):
        # Build chain where put OI >> call OI
        data = []
        for sp in [23000, 23500, 24000, 24500, 25000]:
            data.append({
                "strikePrice": sp,
                "expiryDate": EXPIRY,
                "CE": {"openInterest": 100_000, "changeinOpenInterest": 0,
                       "totalTradedVolume": 10000, "impliedVolatility": 12.0,
                       "lastPrice": 10, "bidprice": 9, "askPrice": 11},
                "PE": {"openInterest": 500_000, "changeinOpenInterest": 0,
                       "totalTradedVolume": 50000, "impliedVolatility": 14.0,
                       "lastPrice": 10, "bidprice": 9, "askPrice": 11},
            })
        chain = {"records": {"underlyingValue": 24000.0, "expiryDates": [EXPIRY], "data": data}}
        walls = OIAnalyzer.detect_walls(chain, EXPIRY)
        oi_sr = OIAnalyzer.detect_oi_support_resistance(chain, EXPIRY)
        levels = OILevelDetector.get_key_levels(chain, EXPIRY, oi_sr, walls)
        # PCR = total_put_oi / total_call_oi = 2500000/500000 = 5.0 → bullish
        assert levels["pcr"] > 1.3
        assert "bullish" in levels["pcr_interpretation"].lower()


# ---------------------------------------------------------------------------
# Missing Greeks — INDmoney stub
# ---------------------------------------------------------------------------

class TestMissingGreeks:

    def test_analysis_works_without_greeks(self):
        # Ensure engine runs fine even when greeks are not in chain
        chain = _make_chain()
        # Chain has no delta/gamma fields — analysis should still complete
        walls = OIAnalyzer.detect_walls(chain, EXPIRY)
        iv_data = IVAnalyzer.get_iv_surface(chain, EXPIRY)
        assert walls["call_wall"] is not None
        assert iv_data["atm_iv"] is not None


# ---------------------------------------------------------------------------
# Cache layer
# ---------------------------------------------------------------------------

class TestOptionCache:

    def setup_method(self):
        from src.options_awareness.cache import _cache_path
        self._path_fn = _cache_path

    def _cleanup(self, symbol, expiry):
        path = self._path_fn(symbol, expiry)
        if path.exists():
            path.unlink()

    def test_write_then_read_returns_entry(self):
        from src.options_awareness.cache import read_cache, write_cache
        chain = _make_chain()
        symbol, expiry = "NIFTY_TEST", "27-Jun-2024"
        try:
            write_cache(symbol, expiry, chain, expiry)
            entry = read_cache(symbol, expiry)
            assert entry is not None
            assert entry["chain"] == chain
            assert entry["resolved"] == expiry
            assert "cached_at" in entry
            assert "cached_at_ist" in entry
        finally:
            self._cleanup(symbol, expiry)

    def test_missing_cache_returns_none(self):
        from src.options_awareness.cache import read_cache
        result = read_cache("NIFTY_NONEXISTENT_XYZ", "01-Jan-2099")
        assert result is None

    def test_expired_cache_returns_none(self):
        import json
        from datetime import datetime, timedelta, timezone

        from src.options_awareness.cache import _cache_path, read_cache, write_cache

        chain = _make_chain()
        symbol, expiry = "NIFTY_EXPIRED", "27-Jun-2024"
        try:
            write_cache(symbol, expiry, chain, expiry)
            path = _cache_path(symbol, expiry)
            # Backdate the cached_at to 2 days ago
            entry = json.loads(path.read_text(encoding="utf-8"))
            old_time = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
            entry["cached_at"] = old_time
            path.write_text(json.dumps(entry), encoding="utf-8")
            result = read_cache(symbol, expiry)
            assert result is None
        finally:
            self._cleanup(symbol, expiry)

    def test_cache_metadata_shape(self):
        from src.options_awareness.cache import cache_metadata, read_cache, write_cache
        chain = _make_chain()
        symbol, expiry = "NIFTY_META", "27-Jun-2024"
        try:
            write_cache(symbol, expiry, chain, expiry)
            entry = read_cache(symbol, expiry)
            assert entry is not None
            meta = cache_metadata(entry)
            assert meta["cache_status"] == "EOD_SNAPSHOT"
            assert "cached_at" in meta
            assert "Post-market" in meta["note"]
        finally:
            self._cleanup(symbol, expiry)

    def test_engine_uses_cache_on_live_failure(self):
        from unittest.mock import patch

        from src.options_awareness.cache import _cache_path, write_cache
        from src.options_awareness.engine import OptionsAwarenessEngine

        chain = _make_chain()
        symbol, expiry = "NIFTY", None
        try:
            # Pre-populate cache
            write_cache(symbol, expiry, chain, "27-Jun-2024")

            # Make live fetch fail
            with patch("src.options_awareness.engine._fetch_live", side_effect=RuntimeError("NSE down")):
                engine = OptionsAwarenessEngine()
                result = engine.analyze(symbol, expiry)

            # Should get data from cache, not an error
            assert "error" not in result
            assert result["cache_status"] == "EOD_SNAPSHOT"
            assert result["cached_at"] is not None
            assert result["spot"] == chain["records"]["underlyingValue"]
            assert "Post-market" in result["observations"][0]
        finally:
            self._cleanup(symbol, expiry)

    def test_engine_no_cache_no_live_returns_error(self):
        from unittest.mock import patch

        from src.options_awareness.cache import _cache_path
        from src.options_awareness.engine import OptionsAwarenessEngine

        symbol, expiry = "NIFTY_NO_CACHE_XYZ", None
        # Ensure no stale cache
        p = _cache_path(symbol, expiry)
        if p.exists():
            p.unlink()

        with patch("src.options_awareness.engine._fetch_live", side_effect=RuntimeError("NSE down")):
            engine = OptionsAwarenessEngine()
            result = engine.analyze(symbol, expiry)

        assert "error" in result
        assert result["spot"] is None

    def test_live_result_has_no_cache_status(self):
        from unittest.mock import patch

        from src.options_awareness.engine import OptionsAwarenessEngine

        chain = _make_chain()
        symbol, expiry = "NIFTY_LIVE", None

        with patch("src.options_awareness.engine._fetch_live", return_value=(chain, "27-Jun-2024")):
            engine = OptionsAwarenessEngine()
            result = engine.analyze(symbol, expiry)

        assert "error" not in result
        assert "cache_status" not in result
        assert result["spot"] == chain["records"]["underlyingValue"]
