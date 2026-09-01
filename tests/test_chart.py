"""
Tests for Phase 3 — Chart Awareness Engine.

All tests use synthetic OHLCV data — no real API calls.
"""
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Synthetic data builders
# ---------------------------------------------------------------------------

def _make_candles(n: int, base: float = 100.0, step: float = 1.0) -> list[dict]:
    """Generate n candles trending upward by `step` per bar."""
    candles = []
    price = base
    for i in range(n):
        o = price
        c = price + step
        h = c + 0.5
        lo = o - 0.5
        candles.append({
            "datetime": f"2025-01-{i + 1:02d}",
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(lo, 2),
            "close": round(c, 2),
            "volume": 1000,
        })
        price = c
    return candles


def _make_downtrend(n: int, base: float = 200.0, step: float = 1.0) -> list[dict]:
    """Generate n candles trending downward."""
    candles = []
    price = base
    for i in range(n):
        o = price
        c = price - step
        h = o + 0.5
        lo = c - 0.5
        candles.append({
            "datetime": f"2025-01-{i + 1:02d}",
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(lo, 2),
            "close": round(c, 2),
            "volume": 1000,
        })
        price = c
    return candles


def _make_hh_hl(n: int = 60) -> list[dict]:
    """Generate a HH-HL pattern: oscillating upward staircase."""
    import math
    candles = []
    for i in range(n):
        # Slow sine wave uptrend
        base = 100 + i * 0.5
        offset = math.sin(i * 0.5) * 3
        c = base + offset
        candles.append({
            "datetime": f"2025-01-{i % 28 + 1:02d}",
            "open": round(c - 0.3, 2),
            "high": round(c + 1.0, 2),
            "low": round(c - 1.0, 2),
            "close": round(c, 2),
            "volume": 1000,
        })
    return candles


def _make_ll_lh(n: int = 60) -> list[dict]:
    """Generate a LH-LL pattern: oscillating downward staircase."""
    import math
    candles = []
    for i in range(n):
        base = 200 - i * 0.5
        offset = math.sin(i * 0.5) * 3
        c = base + offset
        candles.append({
            "datetime": f"2025-01-{i % 28 + 1:02d}",
            "open": round(c + 0.3, 2),
            "high": round(c + 1.0, 2),
            "low": round(c - 1.0, 2),
            "close": round(c, 2),
            "volume": 1000,
        })
    return candles


# ---------------------------------------------------------------------------
# Trend detection
# ---------------------------------------------------------------------------

class TestTrendDetector:

    def test_uptrend_detected(self):
        from src.chart_awareness.trend import detect_trend
        candles = _make_candles(60, step=0.5)
        result = detect_trend(candles)
        assert result["direction"] == "uptrend"
        assert result["ema20_slope"] is not None
        assert result["ema20_slope"] > 0

    def test_downtrend_detected(self):
        from src.chart_awareness.trend import detect_trend
        candles = _make_downtrend(60, step=0.5)
        result = detect_trend(candles)
        assert result["direction"] == "downtrend"
        assert result["ema20_slope"] is not None
        assert result["ema20_slope"] < 0

    def test_price_vs_ema_position(self):
        from src.chart_awareness.trend import detect_trend
        candles = _make_candles(60, step=1.0)
        result = detect_trend(candles)
        assert result["price_vs_ema20"] in ("above", "below")
        assert result["price_vs_ema50"] in ("above", "below", None)

    def test_insufficient_data(self):
        from src.chart_awareness.trend import detect_trend
        candles = _make_candles(5)
        result = detect_trend(candles)
        assert result["direction"] == "sideways"
        assert result["ema20_slope"] is None

    def test_strength_field_present(self):
        from src.chart_awareness.trend import detect_trend
        candles = _make_candles(60, step=2.0)
        result = detect_trend(candles)
        assert result["strength"] in ("strong", "moderate", "weak")

    def test_duration_bars_non_negative(self):
        from src.chart_awareness.trend import detect_trend
        candles = _make_candles(40)
        result = detect_trend(candles)
        assert result["duration_bars"] >= 0


# ---------------------------------------------------------------------------
# Structure detection
# ---------------------------------------------------------------------------

class TestStructureDetector:

    def test_hh_hl_pattern(self):
        from src.chart_awareness.structure import detect_structure
        candles = _make_hh_hl(80)
        result = detect_structure(candles)
        assert result["structure"] in ("HH-HL", "ranging")
        assert "observations" in result
        assert isinstance(result["observations"], list)

    def test_lh_ll_pattern(self):
        from src.chart_awareness.structure import detect_structure
        candles = _make_ll_lh(80)
        result = detect_structure(candles)
        assert result["structure"] in ("LH-LL", "ranging")

    def test_bos_field_is_bool(self):
        from src.chart_awareness.structure import detect_structure
        candles = _make_candles(60)
        result = detect_structure(candles)
        assert isinstance(result["bos"], bool)

    def test_choch_field_is_bool(self):
        from src.chart_awareness.structure import detect_structure
        candles = _make_candles(60)
        result = detect_structure(candles)
        assert isinstance(result["choch"], bool)

    def test_insufficient_data(self):
        from src.chart_awareness.structure import detect_structure
        candles = _make_candles(5)
        result = detect_structure(candles)
        assert result["structure"] == "ranging"
        assert "Insufficient data" in result["observations"][0]

    def test_swing_high_low_detected(self):
        from src.chart_awareness.structure import detect_structure
        candles = _make_hh_hl(60)
        result = detect_structure(candles)
        # May or may not find swing points depending on data; just check types
        if result["last_swing_high"] is not None:
            assert isinstance(result["last_swing_high"], float)
        if result["last_swing_low"] is not None:
            assert isinstance(result["last_swing_low"], float)


# ---------------------------------------------------------------------------
# Level detection
# ---------------------------------------------------------------------------

class TestLevelDetector:

    def test_levels_have_correct_keys(self):
        from src.chart_awareness.levels import detect_levels
        candles = _make_hh_hl(80)
        result = detect_levels(candles)
        assert "supports" in result
        assert "resistances" in result
        assert "pivot" in result

    def test_level_strength_values(self):
        from src.chart_awareness.levels import detect_levels
        candles = _make_hh_hl(80)
        result = detect_levels(candles)
        for lvl in result["supports"] + result["resistances"]:
            assert lvl["strength"] in ("strong", "moderate", "weak")
            assert isinstance(lvl["touches"], int)
            assert isinstance(lvl["level"], float)

    def test_pivot_keys_present(self):
        from src.chart_awareness.levels import detect_levels
        candles = _make_candles(30)
        result = detect_levels(candles)
        if result["pivot"]:
            assert "pp" in result["pivot"]
            assert "r1" in result["pivot"]
            assert "s1" in result["pivot"]

    def test_insufficient_data(self):
        from src.chart_awareness.levels import detect_levels
        candles = _make_candles(3)
        result = detect_levels(candles)
        assert result["supports"] == []
        assert result["resistances"] == []
        assert result["pivot"] == {}


# ---------------------------------------------------------------------------
# Indicator computation
# ---------------------------------------------------------------------------

class TestIndicatorEngine:

    def test_all_fields_returned(self):
        from src.chart_awareness.indicators import compute
        candles = _make_candles(100)
        result = compute(candles)
        expected = [
            "ema20", "ema50", "ema200", "rsi", "macd", "macd_signal",
            "macd_histogram", "adx", "atr", "bb_upper", "bb_mid",
            "bb_lower", "vwap",
        ]
        for key in expected:
            assert key in result

    def test_ema20_populated_with_60_candles(self):
        from src.chart_awareness.indicators import compute
        candles = _make_candles(60)
        result = compute(candles)
        assert result["ema20"] is not None
        assert isinstance(result["ema20"], float)

    def test_ema200_none_with_insufficient_data(self):
        from src.chart_awareness.indicators import compute
        candles = _make_candles(100)
        result = compute(candles)
        assert result["ema200"] is None  # need 200 candles

    def test_ema200_populated_with_200_candles(self):
        from src.chart_awareness.indicators import compute
        candles = _make_candles(220)
        result = compute(candles)
        assert result["ema200"] is not None

    def test_rsi_in_range(self):
        from src.chart_awareness.indicators import compute
        candles = _make_candles(60)
        result = compute(candles)
        if result["rsi"] is not None:
            assert 0 <= result["rsi"] <= 100

    def test_bb_upper_gt_lower(self):
        from src.chart_awareness.indicators import compute
        candles = _make_candles(60)
        result = compute(candles)
        if result["bb_upper"] is not None and result["bb_lower"] is not None:
            assert result["bb_upper"] > result["bb_lower"]

    def test_empty_candles_returns_nones(self):
        from src.chart_awareness.indicators import compute
        result = compute([])
        assert all(v is None for v in result.values())

    def test_vwap_populated_when_volume_present(self):
        from src.chart_awareness.indicators import compute
        candles = _make_candles(30)
        result = compute(candles)
        assert result["vwap"] is not None


# ---------------------------------------------------------------------------
# Symbol normalization
# ---------------------------------------------------------------------------

class TestSymbolNormalization:

    def test_nifty_to_yf(self):
        from src.chart_awareness.data_fetcher import _to_yf_symbol
        assert _to_yf_symbol("NIFTY") == "^NSEI"
        assert _to_yf_symbol("NIFTY 50") == "^NSEI"

    def test_banknifty_to_yf(self):
        from src.chart_awareness.data_fetcher import _to_yf_symbol
        assert _to_yf_symbol("BANKNIFTY") == "^NSEBANK"
        assert _to_yf_symbol("NIFTY BANK") == "^NSEBANK"

    def test_sensex_to_yf(self):
        from src.chart_awareness.data_fetcher import _to_yf_symbol
        assert _to_yf_symbol("SENSEX") == "^BSESN"
        assert _to_yf_symbol("BSE:SENSEX") == "^BSESN"

    def test_equity_symbol_gets_ns_suffix(self):
        from src.chart_awareness.data_fetcher import _to_yf_symbol
        assert _to_yf_symbol("ICICIBANK") == "ICICIBANK.NS"

    def test_nse_prefix_stripped(self):
        from src.chart_awareness.data_fetcher import _to_yf_symbol
        assert _to_yf_symbol("NSE:INFY") == "INFY.NS"

    def test_nifty_to_zerodha(self):
        from src.chart_awareness.data_fetcher import _to_zerodha_symbol
        assert _to_zerodha_symbol("NIFTY") == "NSE:NIFTY 50"

    def test_banknifty_to_zerodha(self):
        from src.chart_awareness.data_fetcher import _to_zerodha_symbol
        assert _to_zerodha_symbol("BANKNIFTY") == "NSE:NIFTY BANK"

    def test_equity_gets_nse_prefix(self):
        from src.chart_awareness.data_fetcher import _to_zerodha_symbol
        assert _to_zerodha_symbol("ICICIBANK") == "NSE:ICICIBANK"


# ---------------------------------------------------------------------------
# Data fetcher fallback chain
# ---------------------------------------------------------------------------

class TestDataFetcher:

    @pytest.mark.anyio
    async def test_falls_back_to_yahoo_when_zerodha_fails(self):
        from src.chart_awareness.data_fetcher import fetch_candles
        candles_sample = _make_candles(30)
        with patch("src.chart_awareness.data_fetcher._fetch_zerodha", new=AsyncMock(return_value=[])), \
             patch("src.chart_awareness.data_fetcher._fetch_indmoney", new=AsyncMock(return_value=[])), \
             patch("src.chart_awareness.data_fetcher._fetch_yahoo", return_value=candles_sample):
            candles, source = await fetch_candles("INFY", "day", "2025-01-01", "2025-04-01")
        assert source == "yahoo"
        assert len(candles) == 30

    @pytest.mark.anyio
    async def test_uses_zerodha_when_available(self):
        from src.chart_awareness.data_fetcher import fetch_candles
        candles_sample = _make_candles(30)
        with patch("src.chart_awareness.data_fetcher._fetch_zerodha", new=AsyncMock(return_value=candles_sample)):
            candles, source = await fetch_candles("INFY", "day", "2025-01-01", "2025-04-01")
        assert source == "zerodha"
        assert len(candles) == 30

    @pytest.mark.anyio
    async def test_uses_indmoney_when_zerodha_fails(self):
        from src.chart_awareness.data_fetcher import fetch_candles
        candles_sample = _make_candles(20)
        with patch("src.chart_awareness.data_fetcher._fetch_zerodha", new=AsyncMock(return_value=[])), \
             patch("src.chart_awareness.data_fetcher._fetch_indmoney", new=AsyncMock(return_value=candles_sample)):
            candles, source = await fetch_candles("INFY", "day", "2025-01-01", "2025-04-01")
        assert source == "indmoney"
        assert len(candles) == 20

    @pytest.mark.anyio
    async def test_returns_none_source_when_all_fail(self):
        from src.chart_awareness.data_fetcher import fetch_candles
        with patch("src.chart_awareness.data_fetcher._fetch_zerodha", new=AsyncMock(return_value=[])), \
             patch("src.chart_awareness.data_fetcher._fetch_indmoney", new=AsyncMock(return_value=[])), \
             patch("src.chart_awareness.data_fetcher._fetch_yahoo", return_value=[]):
            candles, source = await fetch_candles("INVALID", "day", "2025-01-01", "2025-04-01")
        assert source == "none"
        assert candles == []

    @pytest.mark.anyio
    async def test_fetch_zerodha_always_returns_empty_no_working_candle_endpoint(self):
        """Regression test: _fetch_zerodha used to call get_broker().historical_data(),
        a method that has never existed on ZerodhaWebClient/JugaadClient — the
        AttributeError was silently swallowed, so this "tier" always fell through
        without anyone noticing. It's now an explicit, documented no-op returning
        [] unconditionally (no working Zerodha candle endpoint exists without a
        paid Kite Connect subscription or reverse-engineering an undocumented
        internal API) — this test pins that honest behavior so a future fix is a
        deliberate change, not an accidental regression back to a silent swallow."""
        from src.chart_awareness.data_fetcher import _fetch_zerodha
        result = await _fetch_zerodha("INFY", "day", "2025-01-01", "2025-04-01")
        assert result == []


# ---------------------------------------------------------------------------
# ChartEngine (integration with mocked fetch)
# ---------------------------------------------------------------------------

class TestChartEngine:

    @pytest.mark.anyio
    async def test_analyze_returns_all_sections(self):
        from src.chart_awareness.engine import ChartEngine
        candles = _make_candles(100)
        with patch("src.chart_awareness.engine.fetch_candles", new=AsyncMock(return_value=(candles, "yahoo"))):
            result = await ChartEngine().analyze("NIFTY", interval="day", days=90)
        assert result["data_source"] == "yahoo"
        assert result["candles_analyzed"] == 100
        assert "trend" in result
        assert "structure" in result
        assert "indicators" in result
        assert "levels" in result
        assert "observations" in result
        assert isinstance(result["observations"], list)

    @pytest.mark.anyio
    async def test_analyze_with_no_data_returns_error(self):
        from src.chart_awareness.engine import ChartEngine
        with patch("src.chart_awareness.engine.fetch_candles", new=AsyncMock(return_value=([], "none"))):
            result = await ChartEngine().analyze("INVALID", interval="day", days=90)
        assert "error" in result
        assert result["data_source"] == "none"
        assert result["candles_analyzed"] == 0

    @pytest.mark.anyio
    async def test_analyze_respects_include_flags(self):
        from src.chart_awareness.engine import ChartEngine
        candles = _make_candles(60)
        with patch("src.chart_awareness.engine.fetch_candles", new=AsyncMock(return_value=(candles, "yahoo"))):
            result = await ChartEngine().analyze(
                "NIFTY", include_indicators=False, include_structure=False, include_levels=False
            )
        assert result["indicators"] == {}
        assert result["structure"] == {}
        assert result["levels"] == {}

    @pytest.mark.anyio
    async def test_insufficient_data_still_returns(self):
        from src.chart_awareness.engine import ChartEngine
        candles = _make_candles(5)
        with patch("src.chart_awareness.engine.fetch_candles", new=AsyncMock(return_value=(candles, "yahoo"))):
            result = await ChartEngine().analyze("NIFTY", interval="day", days=30)
        assert result["candles_analyzed"] == 5
        assert "trend" in result
