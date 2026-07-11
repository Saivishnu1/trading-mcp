"""Tests for project_carry_cost (Priority B12, 2026-07-11) —
src/options/analytics.py and its MCP tool wrapper in src/tools/trade_planner.py.

Simple linear time-decay approximation (premium / dte per day) — no
Black-Scholes/Greeks model. Pure function, no mocking needed for the core
math; the tool wrapper test confirms the meta envelope.
"""
from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP as _FastMCP

from src.options.analytics import project_carry_cost


class TestProjectCarryCost:
    def test_basic_decay_calculation(self):
        # premium=100, dte=10 -> daily_decay=10; holding 3 more days -> 30
        result = project_carry_cost(premium=100.0, dte=10, days_held=3)
        assert result["estimated_decay_cost"] == 30.0
        assert result["decay_pct_of_premium"] == 30.0

    def test_days_held_capped_at_dte(self):
        """Can't decay past zero extrinsic value — holding past expiry
        doesn't project more cost than the entire premium."""
        result = project_carry_cost(premium=100.0, dte=5, days_held=10)
        assert result["estimated_decay_cost"] == 100.0
        assert result["decay_pct_of_premium"] == 100.0

    def test_days_held_equals_dte(self):
        result = project_carry_cost(premium=200.0, dte=7, days_held=7)
        assert result["estimated_decay_cost"] == 200.0

    def test_note_is_factual_not_predictive(self):
        result = project_carry_cost(premium=100.0, dte=10, days_held=3)
        assert "approximately" in result["note"]
        assert "consider" not in result["note"].lower()
        assert "should" not in result["note"].lower()

    def test_zero_premium_yields_no_projection(self):
        result = project_carry_cost(premium=0.0, dte=10, days_held=3)
        assert result["estimated_decay_cost"] == 0.0
        assert "No projection" in result["note"]

    def test_zero_dte_yields_no_projection(self):
        result = project_carry_cost(premium=100.0, dte=0, days_held=3)
        assert result["estimated_decay_cost"] == 0.0

    def test_zero_days_held_yields_no_projection(self):
        result = project_carry_cost(premium=100.0, dte=10, days_held=0)
        assert result["estimated_decay_cost"] == 0.0

    def test_negative_premium_yields_no_projection(self):
        result = project_carry_cost(premium=-50.0, dte=10, days_held=3)
        assert result["estimated_decay_cost"] == 0.0

    def test_single_day_hold(self):
        result = project_carry_cost(premium=50.0, dte=5, days_held=1)
        assert result["estimated_decay_cost"] == 10.0


class TestProjectCarryCostTool:
    def _tools(self):
        from src.tools import trade_planner
        mcp = _FastMCP("test")
        trade_planner.register(mcp)
        return {t.name: t for t in mcp._tool_manager.list_tools()}

    def test_tool_wraps_data_and_meta(self):
        tools = self._tools()
        result = tools["project_carry_cost"].fn(premium=100.0, dte=10, days_held=3)
        assert result["data"]["estimated_decay_cost"] == 30.0
        assert result["meta"]["source"] == "internal_approximation"
        assert any("Black-Scholes" in lim for lim in result["meta"]["limitations"])
