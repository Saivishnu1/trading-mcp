"""Regression tests for Audit-H2/H6 — get_market_awareness must not present
a failed data fetch as DQ_VALID with a silent 0.0, nor let the narrator stay
silent about it.

Finding: when the options or global-pulse fetch failed, engine.py manufactured
0.0 for pcr/atm_iv/vix/etc, and tools/market_awareness.py's data_quality
computation only checked for a top-level "error" key (which engine.analyze()
never sets) and spot_outside_range — never `missing_data`. A caller reading
data_quality=VALID had no signal anything failed.

MD-1  missing_data non-empty -> data_quality is at most DQ_SUSPECT, never DQ_VALID
MD-2  missing_data non-empty -> a warning naming the missing source is present
MD-3  missing_data empty -> data_quality stays DQ_VALID (no false positive)
MD-4  narrator.narrate() emits an explicit caveat line when missing_data is passed
MD-5  narrator.narrate() emits no caveat line when missing_data is empty/None
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src import meta as _meta
from src.market_awareness.narrator import MarketNarrator


def _base_result(**overrides):
    result = {
        "symbol": "NIFTY",
        "spot": 24000.0,
        "day_high": 24100.0,
        "day_low": 23900.0,
        "options": {"pcr": None},
        "missing_data": [],
    }
    result.update(overrides)
    return result


class TestMD1And2MissingDataDowngradesQuality:
    @pytest.mark.anyio
    async def test_missing_options_data_is_not_valid(self):
        from src.tools import market_awareness as mkt_tools

        mock_mcp = MagicMock()
        registered = {}

        def _tool_decorator():
            def _wrap(fn):
                registered["get_market_awareness"] = fn
                return fn
            return _wrap
        mock_mcp.tool = _tool_decorator

        mkt_tools.register(mock_mcp)
        fn = registered["get_market_awareness"]

        fake_result = _base_result(missing_data=["options"])
        with patch.object(mkt_tools, "MarketAwarenessEngine") as MockEngine:
            MockEngine.return_value.analyze = AsyncMock(return_value=fake_result)
            wrapped = await fn(symbol="NIFTY")

        assert wrapped["meta"]["data_quality"] != _meta.DQ_VALID
        assert "options" in (wrapped["meta"].get("warning") or "")

    @pytest.mark.anyio
    async def test_no_missing_data_stays_valid(self):
        from src.tools import market_awareness as mkt_tools

        mock_mcp = MagicMock()
        registered = {}

        def _tool_decorator():
            def _wrap(fn):
                registered["get_market_awareness"] = fn
                return fn
            return _wrap
        mock_mcp.tool = _tool_decorator

        mkt_tools.register(mock_mcp)
        fn = registered["get_market_awareness"]

        fake_result = _base_result(missing_data=[])
        with patch.object(mkt_tools, "MarketAwarenessEngine") as MockEngine, \
             patch.object(_meta, "is_market_hours", return_value=True):
            MockEngine.return_value.analyze = AsyncMock(return_value=fake_result)
            wrapped = await fn(symbol="NIFTY")

        assert wrapped["meta"]["data_quality"] == _meta.DQ_VALID


class TestMD4And5NarratorCaveat:
    def test_caveat_present_when_missing_data_given(self):
        narrator = MarketNarrator()
        obs = narrator.narrate({"symbol": "NIFTY"}, missing_data=["options", "global"])
        assert any("options" in o and "global" in o for o in obs)

    def test_no_caveat_when_missing_data_empty(self):
        narrator = MarketNarrator()
        obs = narrator.narrate({"symbol": "NIFTY"}, missing_data=[])
        assert not any("unavailable" in o.lower() for o in obs)

    def test_no_caveat_when_missing_data_omitted(self):
        narrator = MarketNarrator()
        obs = narrator.narrate({"symbol": "NIFTY"})
        assert not any("unavailable" in o.lower() for o in obs)
