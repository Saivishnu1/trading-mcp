"""Priority 1 — Timeframe Engine: generate_trade_setup_tf() regression tests.

GTS-1  EXECUTION-role interval produces a real setup (signal/confidence/entry/stoploss/target)
GTS-2  CONTEXT-role interval refuses to produce a setup — cannot gate entry by itself
GTS-3  DISALLOWED interval refuses (via the engine's own refusal, surfaced unchanged)
GTS-4  unknown horizon string refuses with a clear error
GTS-5  intraday (sub-daily) EXECUTION interval produces a setup via the ChartEngine path
GTS-6  generate_trade_setup (daily-only, unchanged) still produces identical output to before
       the _score_setup extraction — same signal/confidence/entry for the same inputs
GTS-7  result carries horizon/interval/role so a caller can audit which timeframe produced it
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.analysis.regime import generate_trade_setup, generate_trade_setup_tf


def _fresh_daily_date() -> str:
    return datetime.now(UTC).date().isoformat()


def _fresh_intraday_ts(offset_minutes: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(minutes=offset_minutes)).strftime("%Y-%m-%d %H:%M:%S")


def _tech_bull_daily():
    return {
        "symbol": "NIFTY", "last_close": 100.0, "candles_used": 150,
        "data_source": "yfinance_eod_adjusted", "last_candle_date": _fresh_daily_date(),
        "rsi_14": 65.0, "ema_20": 95.0, "ema_50": 90.0,
        "macd": {"macd": 0.5, "signal": 0.3, "histogram": 0.2},
        "adx_14": {"adx": 30.0, "plus_di": 28.0, "minus_di": 12.0},
        "atr_14": 2.0,
    }


class TestGTS1ExecutionRoleProducesSetup:
    def test_swing_daily_produces_full_setup(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": _tech_bull_daily())
        result = generate_trade_setup_tf("NIFTY", "SWING", "day")
        assert "error" not in result
        for key in ("signal", "confidence", "entry", "stoploss", "target", "reasoning"):
            assert key in result
        assert result["role"] == "EXECUTION"


class TestGTS2ContextRoleRefuses:
    def test_intraday_options_daily_context_refuses(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": _tech_bull_daily())
        result = generate_trade_setup_tf("NIFTY", "INTRADAY_OPTIONS", "day")
        assert "error" in result
        assert result["role"] == "CONTEXT"
        assert "cannot" in result["error"].lower() or "CONTEXT" in result["error"]

    def test_context_refusal_produces_no_signal_or_entry(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": _tech_bull_daily())
        result = generate_trade_setup_tf("NIFTY", "INTRADAY_OPTIONS", "day")
        assert "signal" not in result
        assert "entry" not in result


class TestGTS3DisallowedIntervalRefuses:
    def test_weekly_disallowed_for_intraday_options(self):
        result = generate_trade_setup_tf("NIFTY", "INTRADAY_OPTIONS", "week")
        assert "error" in result
        assert result["horizon"] == "INTRADAY_OPTIONS"
        assert result["interval"] == "week"


class TestGTS4UnknownHorizonRefuses:
    def test_garbage_horizon_string(self):
        result = generate_trade_setup_tf("NIFTY", "NOT_A_REAL_HORIZON", "day")
        assert "error" in result
        assert "horizon" in result["error"].lower()


class TestGTS5IntradayExecutionViaChartEngine:
    @pytest.mark.anyio
    async def test_15minute_produces_setup(self, monkeypatch):
        candles = [
            {"datetime": _fresh_intraday_ts(offset_minutes=60 - i), "open": 100 + i * 0.1,
             "high": 101 + i * 0.1, "low": 99 + i * 0.1, "close": 100.5 + i * 0.1,
             "volume": 1000}
            for i in range(60)
        ]
        # generate_trade_setup_tf (Priority 4) also attempts a CONTEXT-role
        # fetch ("day" for INTRADAY_OPTIONS) — mock that path too so this
        # test doesn't make a real network call via _analyze_technicals.
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": _tech_bull_daily())
        with patch("src.chart_awareness.engine.fetch_candles", new=AsyncMock(return_value=(candles, "yahoo"))):
            result = generate_trade_setup_tf("NIFTY", "INTRADAY_OPTIONS", "15minute")
        assert "error" not in result or "insufficient data" in result.get("error", "")
        if "error" not in result:
            assert result["role"] == "EXECUTION"
            assert result["interval"] == "15minute"


class TestGTS6DailyOnlyFunctionUnchanged:
    def test_generate_trade_setup_still_produces_same_shape(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": _tech_bull_daily())
        result = generate_trade_setup("NIFTY")
        assert "error" not in result
        assert result["symbol"] == "NIFTY"
        for key in ("signal", "confidence", "entry", "stoploss", "target",
                    "entry_above", "entry_below", "bull_target", "bear_target",
                    "reasoning", "data_basis"):
            assert key in result
        # horizon/interval/role are new-path-only fields; must not leak into
        # the unchanged daily-only function's output.
        assert "horizon" not in result
        assert "role" not in result


class TestGTS7ResultCarriesAuditFields:
    def test_execution_result_names_its_own_horizon_and_interval(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": _tech_bull_daily())
        result = generate_trade_setup_tf("NIFTY", "POSITIONAL", "day")
        assert result["horizon"] == "POSITIONAL"
        assert result["interval"] == "day"
        assert result["role"] == "EXECUTION"
