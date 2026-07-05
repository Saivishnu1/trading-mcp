from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.market_awareness.engine import MarketAwarenessEngine


@pytest.mark.anyio
async def test_market_awareness_full_success():
    # 1. Mock ChartEngine
    mock_chart_engine = MagicMock()
    mock_chart_engine.analyze = AsyncMock(return_value={
        "data_source": "yfinance",
        "trend": {"direction": "uptrend", "strength": "strong", "price_vs_ema20": "above", "price_vs_ema50": "above"},
        "indicators": {"adx": 30.0, "rsi": 65.0, "ema20": 24000.0, "ema50": 23800.0, "ema200": 23000.0, "atr": 150.0},
        "levels": {
            "supports": [{"level": 23900.0, "strength": "strong", "touches": 4}],
            "resistances": [{"level": 24500.0, "strength": "strong", "touches": 3}],
            "pivot": {"pp": 24200.0, "r1": 24350.0, "s1": 24050.0}
        },
        "observations": ["Price is in a strong uptrend", "Price is above EMA20 and EMA50"]
    })

    # 2. Mock OptionsAwarenessEngine
    mock_options_engine = MagicMock()
    mock_options_engine.analyze = MagicMock(return_value={
        "spot": 24270.0,
        "pcr": 1.15,
        "pcr_interpretation": "moderately bullish",
        "max_pain": 24200.0,
        "walls": {"call_wall": 24300.0, "call_wall_oi": 200000.0, "put_wall": 24000.0, "put_wall_oi": 210000.0},
        "iv": {"atm_iv": 8.3, "iv_skew": 0.5},
        "oi_levels": {"supports": [24000.0], "resistances": [24300.0]},
        "observations": ["Call wall at 24,300 — 2.0L OI", "Put wall at 24,000 — 2.1L OI", "Max pain 24,200 — spot 70 pts above"]
    })

    # 3. Mock Global pulse, VIX, and Calendar
    mock_global_pulse = MagicMock(return_value={
        "assets": {
            "gold": {"change_pct": 1.81, "india_impact": "mild risk-off globally"},
            "crude_oil": {"change_pct": -0.5, "india_impact": "Crude stable"},
            "dxy": {"change_pct": 0.1, "india_impact": "Dollar stable"}
        },
        "overall_sentiment": "NEUTRAL"
    })
    mock_vix = MagicMock(return_value={
        "level": 11.8,
        "interpretation": "complacency, historically precedes corrections",
        "caution_level": "LOW"
    })
    mock_calendar = MagicMock(return_value={
        "nse_session_active": True,
        "expiries": {"nifty": "2026-07-07"},
        "days_to_expiry": {"nifty": 2},
        "nse": {
            "upcoming_holidays": [{"date": "2026-08-15", "name": "Independence Day"}]
        }
    })

    # 4. Mock Regime Detection
    mock_regime = MagicMock(return_value={
        "price": 24270.0,
        "regime": "BULL_TREND",
        "adx": 30.0,
        "rsi": 65.0,
        "ema20": 24000.0,
        "ema50": 23800.0,
        "atr": 150.0
    })

    # 5. Mock Pattern detectors
    mock_fetch_candles = AsyncMock(return_value=([{"datetime": "2026-07-05T09:15:00", "open": 24200.0, "high": 24300.0, "low": 24100.0, "close": 24250.0, "volume": 100000}], "yfinance"))
    
    mock_chart_pattern_detector = MagicMock()
    mock_chart_pattern_detector.detect_all = MagicMock(return_value=[
        {"pattern": "Double Bottom", "status": "complete", "direction": "bullish", "neckline": 24000.0, "end_date": "2026-07-05"}
    ])

    with patch("src.market_awareness.aggregator.ChartEngine", return_value=mock_chart_engine), \
         patch("src.market_awareness.aggregator.OptionsAwarenessEngine", return_value=mock_options_engine), \
         patch("src.market_awareness.aggregator.get_global_pulse", mock_global_pulse), \
         patch("src.market_awareness.aggregator.get_india_vix", mock_vix), \
         patch("src.market_awareness.aggregator.get_market_calendar", mock_calendar), \
         patch("src.market_awareness.engine.detect_market_regime", mock_regime), \
         patch("src.market_awareness.aggregator.fetch_candles", mock_fetch_candles), \
         patch("src.market_awareness.aggregator.ChartPatternDetector", return_value=mock_chart_pattern_detector):

        engine = MarketAwarenessEngine()
        res = await engine.analyze("NIFTY")

        # Verify Structure
        assert res["symbol"] == "NIFTY"
        assert res["spot"] == 24270.0
        assert res["expiry"]["next"] == "2026-07-07"
        assert res["expiry"]["days_to_expiry"] == 2
        assert res["expiry"]["expiry_today"] is False
        assert res["market_structure"]["trend"] == "uptrend"
        assert res["market_structure"]["regime"] == "TRENDING"
        assert res["market_structure"]["price_vs_ema200"] == "above"
        assert res["indicators"]["rsi"] == 65.0
        assert res["levels"]["supports"] == [23900.0]
        assert res["levels"]["resistances"] == [24500.0]
        assert res["options"]["pcr"] == 1.15
        assert res["global"]["vix"] == 11.8
        assert res["global"]["gold_change_pct"] == 1.81
        assert res["calendar"]["next_expiry"] == "2026-07-07"
        assert res["data_sources"]["chart"] == "yfinance"
        assert len(res["missing_data"]) == 0
        
        # Verify Narration Factual Observations
        assert "Price is in a strong uptrend" in res["observations"]
        assert "VIX 11.8 — complacency, historically precedes corrections" in res["observations"]
        assert "Gold +1.81% — mild risk-off globally" in res["observations"]
        assert "Double Bottom (complete) — neckline at 24,000.00 — as of 2026-07-05" in res["observations"]


@pytest.mark.anyio
async def test_market_awareness_disabled_features():
    mock_chart_engine = MagicMock()
    mock_chart_engine.analyze = AsyncMock(return_value={"trend": {}, "indicators": {}, "levels": {}})
    mock_calendar = MagicMock(return_value={})
    mock_regime = MagicMock(return_value={})

    with patch("src.market_awareness.aggregator.ChartEngine", return_value=mock_chart_engine), \
         patch("src.market_awareness.aggregator.get_market_calendar", mock_calendar), \
         patch("src.market_awareness.engine.detect_market_regime", mock_regime):

        engine = MarketAwarenessEngine()
        # Disable options, global indicators and pattern recognition
        res = await engine.analyze("NIFTY", include_options=False, include_global=False, include_patterns=False)

        assert res["symbol"] == "NIFTY"
        # Features should be empty/default values
        assert res["options"]["pcr"] == 0.0
        assert len(res["options"]["oi_supports"]) == 0
        assert res["global"]["vix"] == 0.0
        assert len(res["patterns"]["candlestick"]) == 0
        assert len(res["patterns"]["chart"]) == 0
        assert len(res["missing_data"]) == 0


@pytest.mark.anyio
async def test_market_awareness_partial_failure():
    # Chart engine succeeds
    mock_chart_engine = MagicMock()
    mock_chart_engine.analyze = AsyncMock(return_value={
        "trend": {"direction": "sideways"},
        "indicators": {},
        "levels": {},
    })

    # Options throws an exception
    mock_options_engine = MagicMock()
    mock_options_engine.analyze = MagicMock(side_effect=RuntimeError("NSE Connection Timeout"))

    mock_global_pulse = MagicMock(return_value={})
    mock_vix = MagicMock(return_value={})
    mock_calendar = MagicMock(return_value={})
    mock_regime = MagicMock(return_value={})

    with patch("src.market_awareness.aggregator.ChartEngine", return_value=mock_chart_engine), \
         patch("src.market_awareness.aggregator.OptionsAwarenessEngine", return_value=mock_options_engine), \
         patch("src.market_awareness.aggregator.get_global_pulse", mock_global_pulse), \
         patch("src.market_awareness.aggregator.get_india_vix", mock_vix), \
         patch("src.market_awareness.aggregator.get_market_calendar", mock_calendar), \
         patch("src.market_awareness.engine.detect_market_regime", mock_regime):

        engine = MarketAwarenessEngine()
        res = await engine.analyze("NIFTY")

        # Verify that overall call did not crash, returned partial data, and logged options as missing
        assert res["symbol"] == "NIFTY"
        assert res["market_structure"]["trend"] == "sideways"
        assert "options" in res["missing_data"]
        # Options values should fall back to default
        assert res["options"]["pcr"] == 0.0
