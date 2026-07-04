"""
Unit and integration tests for src/dashboard/service.py.

_build_summary is pure — no mocking required.
build_dashboard mocks _analyze_technicals, _load_closes, and get_options_service.

Phase 22F: dashboard output is factual only — no signal/confidence/
trade_setup/strategy fields. _build_summary reads market_structure from
the analysis dict, not a raw regime/signal.
"""
import pytest

from src.dashboard.service import _build_summary, build_dashboard

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_tech_section(rsi=60.0, ema20=100.0, ema50=98.0,
                       adx=18.0, atr=2.0):
    return {
        "rsi": rsi, "ema20": ema20, "ema50": ema50,
        "macd": {"macd": 0.5, "signal": 0.3, "histogram": 0.2},
        "adx": adx, "plus_di": 25.0, "minus_di": 10.0, "atr": atr,
    }


def _make_opts_section(pcr=1.1):
    return {
        "expiry": "26-Jun-2025",
        "pcr": pcr,
        "pcr_interpretation": "mildly bullish",
        "max_pain": 24000.0,
        "distance_from_spot": 0.0,
        "supports": [23000.0],
        "resistances": [25000.0],
        "nearest_support": 23000.0,
        "nearest_resistance": 25000.0,
    }


def _make_analysis_section(adx_note="trend_absent", rsi_note="momentum_elevated"):
    return {
        "market_structure": {
            "price": 101.0, "ema20": 100.0, "ema50": 98.0, "adx": 18.0, "rsi": 60.0,
            "price_above_ema20": True, "ema20_above_ema50": True,
            "adx_above_25": False, "rsi_above_60": False,
            "descriptor": ["price_above_ema20", "ema20_above_ema50"],
            "indicator_interpretation": {
                "type": "INTERPRETATION", "validation_status": "UNVALIDATED",
                "adx_note": adx_note, "rsi_note": rsi_note,
            },
        }
    }


def _tech(rsi=65.0, ema20=100.0, ema50=90.0, adx=30.0, price=101.0,
          atr=2.0, macd_val=0.5, macd_sig=0.3):
    return {
        "symbol": "NIFTY", "last_close": price, "candles_used": 150,
        "rsi_14": rsi, "ema_20": ema20, "ema_50": ema50,
        "macd": {"macd": macd_val, "signal": macd_sig,
                 "histogram": round(macd_val - macd_sig, 4)},
        "adx_14": {"adx": adx, "plus_di": 28.0, "minus_di": 12.0},
        "atr_14": atr,
    }


BULL_TECH = _tech()


# ---------------------------------------------------------------------------
# _build_summary — pure function
# ---------------------------------------------------------------------------

class TestBuildSummary:

    def test_above_both_emas_clause(self):
        tech = _make_tech_section(ema20=100.0, ema50=98.0)
        s = _build_summary("NIFTY", spot=101.0, tech=tech,
                            opts=_make_opts_section(), analysis=_make_analysis_section())
        assert "above ema20" in s.lower() and "and ema50" in s.lower()

    def test_below_both_emas_clause(self):
        tech = _make_tech_section(ema20=102.0, ema50=100.0)
        s = _build_summary("NIFTY", spot=99.0, tech=tech,
                            opts=_make_opts_section(), analysis=_make_analysis_section())
        assert "below ema20" in s.lower() and "and ema50" in s.lower()

    def test_pcr_interpretation_included(self):
        tech = _make_tech_section()
        s = _build_summary("NIFTY", spot=101.0, tech=tech,
                            opts=_make_opts_section(pcr=1.4),
                            analysis=_make_analysis_section())
        assert "pcr 1.40" in s.lower()

    def test_no_pcr_unavailable_clause(self):
        opts = _make_opts_section()
        opts["pcr"] = None
        tech = _make_tech_section()
        s = _build_summary("NIFTY", 101.0, tech, opts, _make_analysis_section())
        assert "unavailable" in s.lower()

    def test_rsi_value_present(self):
        tech = _make_tech_section(rsi=70.0)
        s = _build_summary("NIFTY", 101.0, tech, _make_opts_section(),
                            _make_analysis_section())
        assert "rsi 70.0" in s.lower()

    def test_adx_note_present(self):
        tech = _make_tech_section(adx=12.0)
        s = _build_summary("NIFTY", 101.0, tech, _make_opts_section(),
                            _make_analysis_section(adx_note="trend_absent"))
        assert "trend absent" in s.lower()

    def test_macd_positive_clause(self):
        tech = _make_tech_section()
        tech["macd"] = {"macd": 0.5, "signal": 0.3, "histogram": 0.2}
        s = _build_summary("NIFTY", 101.0, tech, _make_opts_section(),
                            _make_analysis_section())
        assert "macd positive" in s.lower()

    def test_macd_negative_clause(self):
        tech = _make_tech_section()
        tech["macd"] = {"macd": 0.1, "signal": 0.3, "histogram": -0.2}
        s = _build_summary("NIFTY", 101.0, tech, _make_opts_section(),
                            _make_analysis_section())
        assert "macd negative" in s.lower()

    def test_no_signal_or_bias_language(self):
        """Phase 22F: summary must not contain directional bias/recommendation language."""
        tech = _make_tech_section()
        s = _build_summary("NIFTY", 101.0, tech, _make_opts_section(),
                            _make_analysis_section())
        lowered = s.lower()
        for forbidden in ("bullish bias", "bearish bias", "overall bias", "signal is"):
            assert forbidden not in lowered

    def test_symbol_in_summary(self):
        tech = _make_tech_section()
        s = _build_summary("NIFTY", 101.0, tech, _make_opts_section(),
                            _make_analysis_section())
        assert "NIFTY" in s

    def test_returns_non_empty_string(self):
        tech = _make_tech_section()
        s = _build_summary("NIFTY", 101.0, tech, _make_opts_section(),
                            _make_analysis_section())
        assert isinstance(s, str)
        assert len(s) > 20

    def test_max_pain_included(self):
        tech = _make_tech_section()
        s = _build_summary("NIFTY", 101.0, tech, _make_opts_section(),
                            _make_analysis_section())
        assert "max pain 24,000" in s.lower()


# ---------------------------------------------------------------------------
# build_dashboard — integration
# ---------------------------------------------------------------------------

def _make_ohlcv(n=200, start=1000.0, step=3.0):
    closes = [start + step * i for i in range(n)]
    highs  = [c + 5.0 for c in closes]
    lows   = [c - 5.0 for c in closes]
    return closes, highs, lows


class TestBuildDashboard:

    def _patch_all(self, monkeypatch, chain_data, tech=None):
        t = tech or BULL_TECH
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: t)
        closes, highs, lows = _make_ohlcv()
        monkeypatch.setattr("src.dashboard.service._load_closes",
                            lambda symbol, lookback_days=150: (closes, highs, lows))
        from unittest.mock import MagicMock
        svc = MagicMock()
        svc.get_option_chain.return_value = chain_data
        monkeypatch.setattr("src.dashboard.service.get_options_service", lambda: svc)
        monkeypatch.setattr("src.planner.trade_plan.get_options_service",
                            lambda: _raise_svc())

    def test_returns_required_top_level_keys(self, monkeypatch, chain_data):
        self._patch_all(monkeypatch, chain_data)
        r = build_dashboard("NIFTY")
        for key in ("symbol", "spot_price", "options", "technicals",
                    "analysis", "intelligence", "summary"):
            assert key in r

    def test_no_deleted_fields_at_top_level(self, monkeypatch, chain_data):
        """Phase 22F: trade_setup/strategy must not be present on the dashboard."""
        self._patch_all(monkeypatch, chain_data)
        r = build_dashboard("NIFTY")
        assert "trade_setup" not in r
        assert "strategy" not in r

    def test_analysis_has_no_signal_or_confidence(self, monkeypatch, chain_data):
        self._patch_all(monkeypatch, chain_data)
        r = build_dashboard("NIFTY")
        assert "signal" not in r["analysis"]
        assert "confidence" not in r["analysis"]
        assert "regime" not in r["analysis"]

    def test_symbol_uppercased(self, monkeypatch, chain_data):
        self._patch_all(monkeypatch, chain_data)
        r = build_dashboard("nifty")
        assert r["symbol"] == "NIFTY"

    def test_spot_price_from_chain(self, monkeypatch, chain_data):
        self._patch_all(monkeypatch, chain_data)
        r = build_dashboard("NIFTY")
        # Chain spot=24000; technicals spot is from last_close of OHLCV
        # build_dashboard uses chain spot first (spot_chain)
        assert r["spot_price"] == 24000.0

    def test_options_section_has_pcr(self, monkeypatch, chain_data):
        self._patch_all(monkeypatch, chain_data)
        r = build_dashboard("NIFTY")
        assert "pcr" in r["options"]

    def test_technicals_section_has_rsi(self, monkeypatch, chain_data):
        self._patch_all(monkeypatch, chain_data)
        r = build_dashboard("NIFTY")
        assert "rsi" in r["technicals"]
        assert r["technicals"]["rsi"] is not None

    def test_analysis_section_has_market_structure(self, monkeypatch, chain_data):
        self._patch_all(monkeypatch, chain_data)
        r = build_dashboard("NIFTY")
        assert "market_structure" in r["analysis"]
        assert r["analysis"]["market_structure"] is not None

    def test_summary_is_non_empty_string(self, monkeypatch, chain_data):
        self._patch_all(monkeypatch, chain_data)
        r = build_dashboard("NIFTY")
        assert isinstance(r["summary"], str)
        assert len(r["summary"]) > 20

    def test_options_failure_isolated(self, monkeypatch, chain_data):
        """A failed options section must NOT prevent technicals/analysis."""
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: BULL_TECH)
        closes, highs, lows = _make_ohlcv()
        monkeypatch.setattr("src.dashboard.service._load_closes",
                            lambda symbol, lookback_days=150: (closes, highs, lows))
        monkeypatch.setattr("src.dashboard.service.get_options_service",
                            lambda: _raise_svc())
        monkeypatch.setattr("src.planner.trade_plan.get_options_service",
                            lambda: _raise_svc())
        r = build_dashboard("NIFTY")
        # Options failed → error key in options section
        assert "error" in r["options"]
        # But technicals and analysis should still be present and not errored
        assert "rsi" in r["technicals"]
        assert "market_structure" in r["analysis"]

    def test_technicals_failure_isolated(self, monkeypatch, chain_data):
        """A failed technicals section must NOT prevent options/analysis."""
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: BULL_TECH)
        # Return empty OHLCV → technicals section returns error dict
        monkeypatch.setattr("src.dashboard.service._load_closes",
                            lambda symbol, lookback_days=150: (None, None, None))
        from unittest.mock import MagicMock
        svc = MagicMock()
        svc.get_option_chain.return_value = chain_data
        monkeypatch.setattr("src.dashboard.service.get_options_service", lambda: svc)
        monkeypatch.setattr("src.planner.trade_plan.get_options_service",
                            lambda: _raise_svc())
        r = build_dashboard("NIFTY")
        assert "error" in r["technicals"]
        assert "market_structure" in r["analysis"]


class _raise_svc:
    def get_option_chain(self, *a, **kw):
        raise RuntimeError("NSE unavailable in tests")


# ---------------------------------------------------------------------------
# Tool registration — get_sensex_dashboard
# ---------------------------------------------------------------------------

class TestDashboardToolRegistration:
    def test_get_sensex_dashboard_is_registered(self):
        from mcp.server.fastmcp import FastMCP
        from src.tools import dashboard as dashboard_tools

        mcp = FastMCP("test")
        dashboard_tools.register(mcp)
        tools = {t.name for t in mcp._tool_manager.list_tools()}

        assert "get_nifty_dashboard" in tools
        assert "get_banknifty_dashboard" in tools
        assert "get_sensex_dashboard" in tools

    def test_get_sensex_dashboard_calls_build_dashboard_with_sensex(self, monkeypatch):
        from mcp.server.fastmcp import FastMCP
        from src.tools import dashboard as dashboard_tools

        calls = []
        monkeypatch.setattr(
            "src.tools.dashboard.build_dashboard",
            lambda symbol: calls.append(symbol) or {"symbol": symbol},
        )

        mcp = FastMCP("test")
        dashboard_tools.register(mcp)
        tool = next(t for t in mcp._tool_manager.list_tools() if t.name == "get_sensex_dashboard")
        result = tool.fn()

        assert calls == ["SENSEX"]
        assert result == {"symbol": "SENSEX"}
