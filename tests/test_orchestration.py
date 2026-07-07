"""
Tool cleanup + orchestration layer tests.

Covers: MCP_MANIFEST structure, get_capabilities() manifest exposure,
routing_rules coverage, get_kite_mcp_status(), and get_tool_health()
orchestration summary.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP as _FastMCP

from src.orchestration.manifest import MCP_MANIFEST, get_kite_mcp_status


def _meta_mcp():
    from src.tools import meta_tools
    mcp = _FastMCP("test")
    meta_tools.register(mcp)
    return {t.name: t for t in mcp._tool_manager.list_tools()}


# ---------------------------------------------------------------------------
# MCP_MANIFEST structure
# ---------------------------------------------------------------------------

class TestManifestStructure:
    def test_has_required_top_level_sections(self):
        required = {
            "name", "version", "description", "tool_capabilities",
            "data_boundaries", "companion_mcps", "routing_rules",
            "recommended_workflows",
        }
        assert required <= MCP_MANIFEST.keys()

    def test_data_boundaries_has_handles_and_does_not_handle(self):
        assert "handles" in MCP_MANIFEST["data_boundaries"]
        assert "does_not_handle" in MCP_MANIFEST["data_boundaries"]
        assert len(MCP_MANIFEST["data_boundaries"]["handles"]) > 0
        assert len(MCP_MANIFEST["data_boundaries"]["does_not_handle"]) > 0

    def test_companion_mcps_has_indmoney_and_kite(self):
        assert "indmoney_mcp" in MCP_MANIFEST["companion_mcps"]
        assert "kite_mcp" in MCP_MANIFEST["companion_mcps"]

    def test_kite_mcp_marked_unavailable_with_note(self):
        kite = MCP_MANIFEST["companion_mcps"]["kite_mcp"]
        assert kite["status"] == "unavailable"
        assert "note" in kite and len(kite["note"]) > 0


# ---------------------------------------------------------------------------
# routing_rules coverage
# ---------------------------------------------------------------------------

class TestRoutingRules:
    def test_covers_major_use_cases(self):
        expected = {
            "live_quotes", "holdings", "historical_data", "order_placement",
            "gtt_orders", "stock_details", "networth", "mutual_funds",
            "symbol_lookup", "option_analysis", "chart_analysis",
            "pattern_detection", "market_awareness", "position_monitoring",
            "trade_journal",
        }
        assert expected <= MCP_MANIFEST["routing_rules"].keys()

    def test_order_placement_unavailable_when_kite_down(self):
        rule = MCP_MANIFEST["routing_rules"]["order_placement"]
        assert "kite_mcp_unavailable" in rule
        assert "NOT AVAILABLE" in rule["kite_mcp_unavailable"]

    def test_unique_capabilities_always_route_to_us(self):
        for key in ("option_analysis", "chart_analysis", "pattern_detection",
                    "market_awareness", "position_monitoring", "trade_journal"):
            assert "always" in MCP_MANIFEST["routing_rules"][key]


# ---------------------------------------------------------------------------
# get_kite_mcp_status
# ---------------------------------------------------------------------------

class TestKiteMcpStatus:
    def test_returns_valid_status_string(self):
        status = get_kite_mcp_status()
        assert status in ("available", "unavailable")


# ---------------------------------------------------------------------------
# get_capabilities() — full manifest exposure
# ---------------------------------------------------------------------------

class TestGetCapabilitiesManifest:
    def test_returns_full_manifest_sections(self):
        tools = _meta_mcp()
        result = tools["get_capabilities"].fn()
        data = result["data"]
        for key in ("tool_capabilities", "data_boundaries", "companion_mcps",
                    "routing_rules", "recommended_workflows", "generated_at"):
            assert key in data, f"missing {key}"

    def test_preserves_legacy_capability_flags(self):
        tools = _meta_mcp()
        result = tools["get_capabilities"].fn()
        data = result["data"]
        assert data["capabilities"]["market_calendar"] is True
        assert isinstance(data["data_lag"], dict)
        assert isinstance(data["known_broken"], list)
        assert isinstance(data["time_gated"], list)
        assert data["meta"]["total_tools"] > 0

    def test_kite_mcp_status_present_in_companion_mcps(self):
        tools = _meta_mcp()
        result = tools["get_capabilities"].fn()
        kite = result["data"]["companion_mcps"]["kite_mcp"]
        assert kite["status"] in ("available", "unavailable")


# ---------------------------------------------------------------------------
# get_tool_health() — orchestration summary
# ---------------------------------------------------------------------------

class TestToolHealthOrchestration:
    def test_includes_orchestration_section(self):
        tools = _meta_mcp()
        result = tools["get_tool_health"].fn()
        data = result["data"]
        assert "orchestration" in data
        orch = data["orchestration"]
        assert orch["companion_mcps"]["indmoney_mcp"] == "available"
        assert orch["companion_mcps"]["kite_mcp"] in ("available", "unavailable")
        assert orch["routing_active"] is True
        assert orch["manifest_version"] == MCP_MANIFEST["version"]


# ---------------------------------------------------------------------------
# Removed tools stay removed
# ---------------------------------------------------------------------------

class TestRemovedToolsAbsent:
    def test_six_redundant_tools_not_registered(self):
        import importlib
        mods = [
            "auth", "portfolio", "market", "instruments", "options",
            "technicals", "analysis", "dashboard", "trade_planner",
            "strategy_builder", "trade_review", "intelligence",
            "portfolio_intelligence", "catalyst", "journal",
            "recommendations", "sizer", "meta_tools", "brokers", "chart",
            "candles", "chart_patterns", "options_awareness",
            "market_awareness", "charts", "monitor",
        ]
        mcp = _FastMCP("test")
        for m in mods:
            mod = importlib.import_module(f"src.tools.{m}")
            mod.register(mcp)
        names = {t.name for t in mcp._tool_manager.list_tools()}
        removed = {
            "get_indmoney_raw", "get_indmoney_greeks", "get_daily_brief",
            "get_market_risk_score", "detect_market_regime",
            "get_regime_alignment",
        }
        assert not (removed & names)
