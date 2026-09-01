"""Priority 1 — Timeframe Engine: get_technicals() gateway tests.

TE-1  a disallowed (horizon, interval) pair refuses with an error, no fetch attempted
TE-2  an EXECUTION-role daily fetch for SWING routes through _analyze_technicals and tags role
TE-3  a CONTEXT-role daily fetch for INTRADAY_OPTIONS is tagged role=CONTEXT, can_gate_entry=False
TE-4  a sub-daily interval routes through ChartEngine, not _analyze_technicals
TE-5  ChartEngine failure surfaces as an error dict, never raises
TE-6  _analyze_technicals failure (no data) passes through as an error dict unchanged
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.timeframe.engine import get_technicals
from src.timeframe.policy import HoldingHorizon


def _fresh_daily_date() -> str:
    return datetime.now(UTC).date().isoformat()


def _fresh_intraday_ts() -> str:
    return (datetime.now(UTC) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")


class TestTE1DisallowedPairRefusesWithoutFetching:
    def test_refuses_without_calling_any_fetcher(self, monkeypatch):
        called = {"regime": False, "chart": False}

        def _boom_regime(*a, **kw):
            called["regime"] = True
            return {}

        monkeypatch.setattr("src.analysis.regime._analyze_technicals", _boom_regime)
        result = get_technicals("NIFTY", HoldingHorizon.INTRADAY_OPTIONS, "week")
        assert "error" in result
        assert called["regime"] is False

    def test_error_names_the_horizon_and_interval(self):
        result = get_technicals("NIFTY", HoldingHorizon.INTRADAY_OPTIONS, "month")
        assert "error" in result
        assert result["horizon"] == "INTRADAY_OPTIONS"
        assert result["interval"] == "month"


class TestTE2DailyExecutionRoutesToAnalyzeTechnicals:
    def test_swing_daily_routes_to_analyze_technicals(self, monkeypatch):
        fake = {
            "symbol": "NIFTY", "last_close": 100.0, "candles_used": 150,
            "data_source": "yfinance_eod_adjusted", "last_candle_date": _fresh_daily_date(),
            "rsi_14": 55.0, "ema_20": 99.0, "ema_50": 95.0,
            "macd": {"macd": 0.1, "signal": 0.05, "histogram": 0.05},
            "adx_14": {"adx": 20.0, "plus_di": 18.0, "minus_di": 15.0},
            "atr_14": 2.0,
        }
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": fake)
        result = get_technicals("NIFTY", HoldingHorizon.SWING, "day")
        assert result["role"] == "EXECUTION"
        assert result["can_gate_entry"] is True
        assert result["last_close"] == 100.0


class TestTE3ContextRoleTaggedCorrectly:
    def test_intraday_options_daily_is_context_and_cannot_gate(self, monkeypatch):
        fake = {
            "symbol": "NIFTY", "last_close": 100.0, "candles_used": 150,
            "data_source": "yfinance_eod_adjusted", "last_candle_date": _fresh_daily_date(),
            "rsi_14": 55.0, "ema_20": 99.0, "ema_50": 95.0,
            "macd": {"macd": 0.1, "signal": 0.05, "histogram": 0.05},
            "adx_14": {"adx": 20.0, "plus_di": 18.0, "minus_di": 15.0},
            "atr_14": 2.0,
        }
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": fake)
        result = get_technicals("NIFTY", HoldingHorizon.INTRADAY_OPTIONS, "day")
        assert result["role"] == "CONTEXT"
        assert result["can_gate_entry"] is False


class TestTE4SubDailyRoutesToChartEngine:
    @pytest.mark.anyio
    async def test_15minute_uses_chart_engine_not_regime(self, monkeypatch):
        regime_called = {"value": False}

        def _boom(*a, **kw):
            regime_called["value"] = True
            return {}
        monkeypatch.setattr("src.analysis.regime._analyze_technicals", _boom)

        candles = [
            {"datetime": _fresh_intraday_ts(), "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000}
            for _ in range(30)
        ]
        with patch("src.chart_awareness.engine.fetch_candles", new=AsyncMock(return_value=(candles, "yahoo"))):
            result = get_technicals("NIFTY", HoldingHorizon.INTRADAY_OPTIONS, "15minute")

        assert regime_called["value"] is False
        assert result["role"] == "EXECUTION"
        assert result["can_gate_entry"] is True
        assert result["data_source"] == "yahoo"

    @pytest.mark.anyio
    async def test_1minute_is_fine_entry_role(self):
        candles = [
            {"datetime": _fresh_intraday_ts(), "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000}
            for _ in range(30)
        ]
        with patch("src.chart_awareness.engine.fetch_candles", new=AsyncMock(return_value=(candles, "yahoo"))):
            result = get_technicals("NIFTY", HoldingHorizon.INTRADAY_OPTIONS, "1minute")
        assert result["role"] == "FINE_ENTRY"
        assert result["can_gate_entry"] is True


class TestTE5ChartEngineFailureSurfacesAsError:
    @pytest.mark.anyio
    async def test_no_candles_returns_error_dict(self):
        with patch("src.chart_awareness.engine.fetch_candles", new=AsyncMock(return_value=([], "none"))):
            result = get_technicals("NOTASYMBOL", HoldingHorizon.INTRADAY_OPTIONS, "5minute")
        assert "error" in result
        assert result["horizon"] == "INTRADAY_OPTIONS"
        assert result["interval"] == "5minute"


class TestTE6AnalyzeTechnicalsFailurePassesThrough:
    def test_no_price_data_error_passes_through(self, monkeypatch):
        error_result = {"symbol": "NIFTY", "error": "no price data available"}
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": error_result)
        result = get_technicals("NIFTY", HoldingHorizon.SWING, "day")
        assert result == error_result
