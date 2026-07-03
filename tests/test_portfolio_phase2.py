"""
Phase 2 — Portfolio Intelligence tests.

Covers: sector_map, AssetAllocator, RiskAnalyzer, PortfolioAnalyzer.
No real network calls — all broker interactions are mocked.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from src.brokers.models import Holding, Position, Fund
from src.portfolio.analyzer import PortfolioAnalyzer
from src.portfolio.allocator import AssetAllocator
from src.portfolio.risk import RiskAnalyzer
from src.portfolio.sector_map import get_sector, SECTOR_MAP


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_holdings():
    return [
        Holding("HDFCBANK", "NSE", 100, 1500.0, 1600.0, 10000.0, 6.67, "zerodha"),
        Holding("INFY",     "NSE",  50, 1400.0, 1500.0,  5000.0, 7.14, "zerodha"),
        Holding("RELIANCE", "NSE",  30, 2800.0, 3000.0,  6000.0, 7.14, "indmoney"),
        Holding("TCS",      "NSE",  20, 3500.0, 3800.0,  6000.0, 8.57, "indmoney"),
        Holding("UNKNOWN_CO","NSE", 10,  100.0,  120.0,   200.0,20.0,  "zerodha"),
    ]


@pytest.fixture
def sample_positions():
    return [
        Position("NIFTY25JUNFUT", "NFO", "FUTURES", 50, 23000.0, 23500.0, 25000.0, "zerodha"),
    ]


@pytest.fixture
def sample_funds():
    return [
        Fund(50000.0, 20000.0, 70000.0, "zerodha"),
        Fund(30000.0, 10000.0, 40000.0, "indmoney"),
    ]


# ---------------------------------------------------------------------------
# TestSectorMap
# ---------------------------------------------------------------------------

class TestSectorMap:

    def test_known_symbol_returns_sector(self):
        assert get_sector("HDFCBANK") == "Banking"
        assert get_sector("INFY") == "IT"
        assert get_sector("RELIANCE") == "Energy"

    def test_unknown_symbol_returns_other(self):
        assert get_sector("UNKNOWN_CO") == "Other"
        assert get_sector("XYZ123") == "Other"

    def test_exchange_prefix_stripped(self):
        assert get_sector("NSE:INFY") == "IT"
        assert get_sector("BSE:TCS") == "IT"

    def test_case_insensitive(self):
        assert get_sector("infy") == "IT"
        assert get_sector("hdfcbank") == "Banking"
        assert get_sector("Reliance") == "Energy"

    def test_dot_suffix_stripped(self):
        assert get_sector("INFY.NS") == "IT"
        assert get_sector("TCS.BO") == "IT"

    def test_sector_map_has_entries(self):
        assert len(SECTOR_MAP) >= 50

    def test_combined_prefix_and_suffix(self):
        assert get_sector("NSE:INFY.NS") == "IT"


# ---------------------------------------------------------------------------
# TestAssetAllocator
# ---------------------------------------------------------------------------

class TestAssetAllocator:

    def test_by_broker_splits_correctly(self, sample_holdings):
        result = AssetAllocator().by_broker(sample_holdings)
        # zerodha: HDFCBANK(160000) + INFY(75000) + UNKNOWN(1200) = 236200
        # indmoney: RELIANCE(90000) + TCS(76000) = 166000
        assert "zerodha" in result
        assert "indmoney" in result
        assert result["zerodha"]["value"] == pytest.approx(236200.0, rel=1e-3)
        assert result["indmoney"]["value"] == pytest.approx(166000.0, rel=1e-3)

    def test_by_broker_percents_sum_to_100(self, sample_holdings):
        result = AssetAllocator().by_broker(sample_holdings)
        total_pct = sum(v["percent"] for v in result.values())
        assert total_pct == pytest.approx(100.0, rel=1e-3)

    def test_by_sector_groups_banking(self, sample_holdings):
        result = AssetAllocator().by_sector(sample_holdings)
        assert "Banking" in result
        assert result["Banking"]["value"] == pytest.approx(160000.0, rel=1e-3)

    def test_by_sector_unknown_goes_to_other(self, sample_holdings):
        result = AssetAllocator().by_sector(sample_holdings)
        assert "Other" in result
        assert result["Other"]["value"] == pytest.approx(1200.0, rel=1e-3)

    def test_by_sector_percents_sum_to_100(self, sample_holdings):
        result = AssetAllocator().by_sector(sample_holdings)
        total_pct = sum(v["percent"] for v in result.values())
        assert total_pct == pytest.approx(100.0, rel=1e-3)

    def test_by_asset_class_with_positions(self, sample_holdings, sample_positions):
        result = AssetAllocator().by_asset_class(sample_holdings, sample_positions)
        assert "equity" in result
        assert "derivatives" in result
        assert result["equity"]["value"] > 0

    def test_by_asset_class_no_positions(self, sample_holdings):
        result = AssetAllocator().by_asset_class(sample_holdings, [])
        assert result["equity"]["percent"] == pytest.approx(100.0, rel=1e-3)
        assert result["derivatives"]["value"] == 0.0

    def test_empty_holdings_returns_empty(self):
        result = AssetAllocator().by_broker([])
        assert result == {}

    def test_by_exchange_groups_correctly(self, sample_holdings):
        result = AssetAllocator().by_exchange(sample_holdings)
        assert "NSE" in result
        total_pct = sum(v["percent"] for v in result.values())
        assert total_pct == pytest.approx(100.0, rel=1e-3)

    def test_by_sector_sorted_descending(self, sample_holdings):
        result = AssetAllocator().by_sector(sample_holdings)
        values = [v["value"] for v in result.values()]
        assert values == sorted(values, reverse=True)


# ---------------------------------------------------------------------------
# TestRiskAnalyzer
# ---------------------------------------------------------------------------

class TestRiskAnalyzer:

    def _make_holdings(self, values: list[tuple[str, float]]) -> list[Holding]:
        """Build minimal Holding list from (symbol, value) pairs."""
        return [
            Holding(sym, "NSE", 1, val, val, 0.0, 0.0, "zerodha")
            for sym, val in values
        ]

    def test_low_risk_when_largest_under_20pct(self):
        # Each of 6 equal positions = 16.7% — all below the 20% threshold
        holdings = self._make_holdings([
            ("A", 10.0), ("B", 10.0), ("C", 10.0),
            ("D", 10.0), ("E", 10.0), ("F", 10.0),
        ])
        result = RiskAnalyzer().concentration_risk(holdings)
        assert result["risk_level"] == "low"

    def test_medium_risk_when_largest_20_to_40pct(self):
        # Largest = 35/(35+35+30) = 35% → medium (>20 but <=40)
        holdings = self._make_holdings([("A", 35.0), ("B", 35.0), ("C", 30.0)])
        result = RiskAnalyzer().concentration_risk(holdings)
        assert result["risk_level"] == "medium"
        assert result["largest_position_percent"] == pytest.approx(35.0, rel=1e-3)

    def test_high_risk_when_largest_over_40pct(self):
        holdings = self._make_holdings([("BIGCO", 60.0), ("SMALL", 40.0)])
        result = RiskAnalyzer().concentration_risk(holdings)
        assert result["risk_level"] == "high"
        assert result["largest_position"] == "BIGCO"

    def test_largest_positions_sorted_by_value(self, sample_holdings):
        result = RiskAnalyzer().largest_positions(sample_holdings)
        values = [p["value"] for p in result]
        assert values == sorted(values, reverse=True)

    def test_largest_positions_top_n_respected(self, sample_holdings):
        result = RiskAnalyzer().largest_positions(sample_holdings, top_n=3)
        assert len(result) == 3

    def test_largest_positions_default_top5(self, sample_holdings):
        result = RiskAnalyzer().largest_positions(sample_holdings)
        assert len(result) == 5  # fixture has exactly 5

    def test_empty_holdings_returns_safe_defaults(self):
        result = RiskAnalyzer().concentration_risk([])
        assert result["largest_position"] == ""
        assert result["largest_position_percent"] == 0.0
        assert result["top5_percent"] == 0.0
        assert result["risk_level"] == "low"

    def test_empty_holdings_largest_positions_empty(self):
        assert RiskAnalyzer().largest_positions([]) == []

    def test_concentration_risk_fields_present(self, sample_holdings):
        result = RiskAnalyzer().concentration_risk(sample_holdings)
        for key in ("largest_position", "largest_position_percent", "top5_percent", "risk_level"):
            assert key in result

    def test_single_stock_exposure_sums_to_100(self, sample_holdings):
        result = RiskAnalyzer().single_stock_exposure(sample_holdings)
        assert sum(result.values()) == pytest.approx(100.0, rel=1e-3)


# ---------------------------------------------------------------------------
# TestPortfolioAnalyzer
# ---------------------------------------------------------------------------

class TestPortfolioAnalyzer:

    @pytest.mark.anyio
    async def test_full_portfolio_returns_all_fields(
        self, sample_holdings, sample_positions, sample_funds
    ):
        result = await PortfolioAnalyzer().get_unified_portfolio(
            sample_holdings, sample_positions, sample_funds
        )
        for key in (
            "broker_exposure", "asset_allocation", "sector_exposure",
            "networth", "pnl", "concentration_risk", "largest_positions",
            "broker_data", "observations",
        ):
            assert key in result, f"Missing key: {key}"

    @pytest.mark.anyio
    async def test_networth_calculation(
        self, sample_holdings, sample_positions, sample_funds
    ):
        result = await PortfolioAnalyzer().get_unified_portfolio(
            sample_holdings, sample_positions, sample_funds
        )
        nw = result["networth"]
        # holdings_value = 100*1600 + 50*1500 + 30*3000 + 20*3800 + 10*120
        # = 160000 + 75000 + 90000 + 76000 + 1200 = 402200
        assert nw["holdings_value"] == pytest.approx(402200.0, rel=1e-3)
        assert nw["available_cash"] == pytest.approx(80000.0, rel=1e-3)  # 50000+30000
        assert nw["positions_pnl"] == pytest.approx(25000.0, rel=1e-3)
        assert nw["total"] == pytest.approx(402200.0 + 25000.0 + 80000.0, rel=1e-3)

    @pytest.mark.anyio
    async def test_pnl_calculation(
        self, sample_holdings, sample_positions, sample_funds
    ):
        result = await PortfolioAnalyzer().get_unified_portfolio(
            sample_holdings, sample_positions, sample_funds
        )
        pnl = result["pnl"]
        # unrealized = sum of h.pnl = 10000+5000+6000+6000+200 = 27200
        assert pnl["unrealized"] == pytest.approx(27200.0, rel=1e-3)
        assert "unrealized_percent" in pnl
        assert "realized_today" in pnl

    @pytest.mark.anyio
    async def test_observations_not_empty(
        self, sample_holdings, sample_positions, sample_funds
    ):
        result = await PortfolioAnalyzer().get_unified_portfolio(
            sample_holdings, sample_positions, sample_funds
        )
        assert isinstance(result["observations"], list)
        assert len(result["observations"]) > 0

    @pytest.mark.anyio
    async def test_observations_factual_only(
        self, sample_holdings, sample_positions, sample_funds
    ):
        result = await PortfolioAnalyzer().get_unified_portfolio(
            sample_holdings, sample_positions, sample_funds
        )
        forbidden = {"recommend", "buy", "sell", "target", "confidence"}
        for obs in result["observations"]:
            words = set(obs.lower().split())
            overlap = words & forbidden
            assert not overlap, f"Observation contains forbidden word: {overlap!r} in {obs!r}"

    @pytest.mark.anyio
    async def test_empty_holdings_does_not_crash(self):
        result = await PortfolioAnalyzer().get_unified_portfolio([], [], [])
        assert result["networth"]["holdings_value"] == 0.0
        assert result["networth"]["total"] == 0.0
        assert result["observations"] == ["No holdings data available."]

    @pytest.mark.anyio
    async def test_multi_broker_merging(
        self, sample_holdings, sample_positions, sample_funds
    ):
        result = await PortfolioAnalyzer().get_unified_portfolio(
            sample_holdings, sample_positions, sample_funds
        )
        be = result["broker_exposure"]
        assert "zerodha" in be
        assert "indmoney" in be

    @pytest.mark.anyio
    async def test_sector_exposure_present(
        self, sample_holdings, sample_positions, sample_funds
    ):
        result = await PortfolioAnalyzer().get_unified_portfolio(
            sample_holdings, sample_positions, sample_funds
        )
        se = result["sector_exposure"]
        assert "Banking" in se
        assert "IT" in se
        assert "Energy" in se

    @pytest.mark.anyio
    async def test_concentration_risk_in_result(
        self, sample_holdings, sample_positions, sample_funds
    ):
        result = await PortfolioAnalyzer().get_unified_portfolio(
            sample_holdings, sample_positions, sample_funds
        )
        cr = result["concentration_risk"]
        assert "risk_level" in cr
        assert "largest_position" in cr

    @pytest.mark.anyio
    async def test_largest_positions_list(
        self, sample_holdings, sample_positions, sample_funds
    ):
        result = await PortfolioAnalyzer().get_unified_portfolio(
            sample_holdings, sample_positions, sample_funds
        )
        lp = result["largest_positions"]
        assert isinstance(lp, list)
        assert len(lp) <= 5
        # First entry should be the largest by value
        assert lp[0]["symbol"] == "HDFCBANK"  # 100*1600 = 160000 is largest


# ---------------------------------------------------------------------------
# TestAnalyzePortfolioTool
# ---------------------------------------------------------------------------

class TestAnalyzePortfolioTool:

    @pytest.mark.anyio
    async def test_tool_returns_wrapped_response(self):
        """analyze_portfolio wraps result with data + meta."""
        from src.tools.portfolio import register
        from mcp.server.fastmcp import FastMCP
        from unittest.mock import AsyncMock, MagicMock

        captured = {}

        class _FakeMCP:
            def tool(self):
                def decorator(fn):
                    captured[fn.__name__] = fn
                    return fn
                return decorator

        register(_FakeMCP())
        tool_fn = captured.get("analyze_portfolio")
        assert tool_fn is not None, "analyze_portfolio tool not registered"

        # Patch broker adapters to return empty data (unauthenticated)
        with (
            patch("src.brokers.zerodha.ZerodhaBroker.is_authenticated", new=AsyncMock(return_value=False)),
            patch("src.brokers.indmoney.INDmoneyBroker.is_authenticated", new=AsyncMock(return_value=False)),
        ):
            result = await tool_fn(broker="all")

        assert "data" in result
        assert "meta" in result
        assert "networth" in result["data"]

    @pytest.mark.anyio
    async def test_tool_handles_broker_error_gracefully(self):
        """If a broker raises, the tool still returns a valid response."""
        from src.tools.portfolio import register

        captured = {}

        class _FakeMCP:
            def tool(self):
                def decorator(fn):
                    captured[fn.__name__] = fn
                    return fn
                return decorator

        register(_FakeMCP())
        tool_fn = captured["analyze_portfolio"]

        with (
            patch("src.brokers.zerodha.ZerodhaBroker.is_authenticated", new=AsyncMock(side_effect=RuntimeError("network error"))),
            patch("src.brokers.indmoney.INDmoneyBroker.is_authenticated", new=AsyncMock(side_effect=RuntimeError("network error"))),
        ):
            result = await tool_fn(broker="all")

        assert "data" in result
        assert result["data"]["networth"]["holdings_value"] == 0.0
